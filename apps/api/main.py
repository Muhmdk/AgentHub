"""FastAPI composition root for the AgentHub control plane."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from agents.inventory.agent import InventoryAgent
from agents.inventory.data import RetailData
from agents.knowledge.agent import KnowledgeAgent
from agents.shared.corpus import create_retail_retriever
from agents.shared.providers import create_chat_model
from agents.shopping.agent import ShoppingAgent
from agents.shopping.tools import ProductSearchTool
from apps.api.config import Settings, load_settings
from apps.api.errors import register_error_handlers
from apps.api.logging import configure_logging
from apps.api.middleware import correlation_middleware
from apps.web import evaluation_page_path, observability_page_path, registry_page_path
from packages.contracts.evaluation import (
    EvaluationRunReport,
    EvaluationRunSummary,
    GateDecision,
    RunEvaluationRequest,
)
from packages.contracts.health import HealthResponse, VersionResponse
from packages.contracts.manifest import AgentManifest
from packages.contracts.observability import AgentHealth, FleetHealth
from packages.contracts.registry import (
    AgentSummary,
    AgentVersionView,
    AuditEventView,
    LifecycleTransitionRequest,
    RegistrationResult,
)
from packages.contracts.release import (
    CandidateResult,
    CreateCandidateRequest,
    PromoteReleaseRequest,
    ReleaseEventView,
    ReleaseNotes,
    ReleaseView,
)
from packages.contracts.retrieval import GroundedAgentResponse
from packages.contracts.runtime import AgentRequest, AgentResponse
from packages.evaluation.repository import EvaluationRepository, EvaluationStore
from packages.evaluation.service import EvaluationService
from packages.observability.conventions import Attribute
from packages.observability.slos import fleet_health
from packages.observability.telemetry import Telemetry, TelemetryConfig
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository, RegistryStore
from packages.release.repository import ReleaseRepository, ReleaseStore
from packages.release.service import ReleaseService

logger = logging.getLogger("agenthub.api")


def create_app(
    settings: Settings | None = None,
    inventory_agent: InventoryAgent | None = None,
    knowledge_agent: KnowledgeAgent | None = None,
    shopping_agent: ShoppingAgent | None = None,
    database: Database | None = None,
    registry_store: RegistryStore | None = None,
    evaluation_store: EvaluationStore | None = None,
    release_store: ReleaseStore | None = None,
    telemetry_instance: Telemetry | None = None,
) -> FastAPI:
    """Create an application with explicit, testable dependencies."""
    app_settings = settings or load_settings()
    configure_logging(app_settings)
    telemetry = telemetry_instance or Telemetry(
        TelemetryConfig(
            service_name=app_settings.service_name,
            service_version=app_settings.version,
            environment=app_settings.environment,
            enabled=app_settings.otel_enabled,
            endpoint=app_settings.otel_endpoint,
            export_interval_ms=app_settings.otel_export_interval_ms,
            max_queue_size=app_settings.otel_max_queue_size,
        )
    )
    model = create_chat_model(app_settings.model_provider)
    inventory = inventory_agent or InventoryAgent(
        data=RetailData.load(),
        model=model,
        max_steps=app_settings.agent_max_steps,
        tool_timeout_seconds=app_settings.tool_timeout_seconds,
        execution_timeout_seconds=app_settings.agent_timeout_seconds,
        telemetry=telemetry,
    )
    retriever, corpus, _ = create_retail_retriever()
    knowledge = knowledge_agent or KnowledgeAgent(
        retriever=retriever,
        corpus=corpus,
        model=model,
        top_k=app_settings.rag_top_k,
        minimum_score=app_settings.rag_minimum_score,
        timeout_seconds=app_settings.retrieval_timeout_seconds,
        telemetry=telemetry,
    )
    shopping = shopping_agent or ShoppingAgent(
        product_tool=ProductSearchTool(retriever, corpus),
        model=model,
        timeout_seconds=app_settings.agent_timeout_seconds,
        telemetry=telemetry,
    )
    registry_database = database
    owns_registry_database = False
    if registry_store is None:
        if registry_database is None:
            registry_database = Database(app_settings.database_url)
            owns_registry_database = True
        registry: RegistryStore = RegistryRepository(registry_database)
    else:
        registry = registry_store
    evaluations: EvaluationStore
    if evaluation_store is not None:
        evaluations = evaluation_store
    elif registry_database is not None:
        evaluations = EvaluationRepository(registry_database)
    else:  # pragma: no cover - a custom registry should provide an evaluation store
        raise ValueError("An evaluation store is required without a database")
    evaluation_service = EvaluationService(
        registry=registry,
        store=evaluations,
        targets={
            "inventory-agent": inventory,
            "knowledge-agent": knowledge,
            "shopping-agent": shopping,
        },
        telemetry=telemetry,
    )
    releases: ReleaseStore
    if release_store is not None:
        releases = release_store
    elif registry_database is not None:
        releases = ReleaseRepository(registry_database)
    else:  # pragma: no cover - custom stores must be supplied together
        raise ValueError("A release store is required without a database")
    release_service = ReleaseService(registry, evaluations, releases)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("service_started")
        try:
            yield
        finally:
            telemetry.shutdown()
            if owns_registry_database and registry_database is not None:
                registry_database.dispose()
            logger.info("service_stopped")

    app = FastAPI(
        title="AgentHub API",
        version=app_settings.version,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.telemetry = telemetry
    app.state.inventory_agent = inventory
    app.state.knowledge_agent = knowledge
    app.state.shopping_agent = shopping
    app.state.registry = registry
    app.state.evaluations = evaluations
    app.state.releases = releases
    app.state.database = registry_database
    app.middleware("http")(correlation_middleware)
    register_error_handlers(app)

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok", service=app_settings.service_name)

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
        if registry_database is not None:
            try:
                ready = await asyncio.to_thread(registry_database.ping)
            except Exception:
                ready = False
            if not ready:
                raise HTTPException(status_code=503, detail="Database is not ready")
        return HealthResponse(status="ready", service=app_settings.service_name)

    @app.get("/version", response_model=VersionResponse, tags=["metadata"])
    async def service_version() -> VersionResponse:
        return VersionResponse(
            service=app_settings.service_name,
            version=app_settings.version,
            environment=app_settings.environment,
        )

    @app.post(
        "/agents/inventory/invoke",
        response_model=AgentResponse,
        tags=["agents"],
    )
    async def invoke_inventory(request: AgentRequest) -> AgentResponse:
        return await inventory.invoke(request)

    @app.post(
        "/agents/knowledge/invoke",
        response_model=GroundedAgentResponse,
        tags=["agents"],
    )
    async def invoke_knowledge(request: AgentRequest) -> GroundedAgentResponse:
        return await knowledge.invoke(request)

    @app.post(
        "/agents/shopping/invoke",
        response_model=GroundedAgentResponse,
        tags=["agents"],
    )
    async def invoke_shopping(request: AgentRequest) -> GroundedAgentResponse:
        return await shopping.invoke(request)

    @app.post(
        "/registry/agents",
        response_model=RegistrationResult,
        tags=["registry"],
    )
    async def register_agent(
        manifest: AgentManifest,
        request: Request,
        actor: Annotated[
            str,
            Header(alias="X-AgentHub-Actor", min_length=2, max_length=200),
        ],
    ) -> RegistrationResult:
        with telemetry.span(
            "registry.register",
            {
                Attribute.AGENT_NAME: manifest.metadata.name,
                Attribute.AGENT_VERSION: manifest.metadata.version,
                Attribute.RELEASE_ID: request.state.release_id,
            },
        ):
            return await asyncio.to_thread(
                registry.register,
                manifest,
                actor=actor,
                correlation_id=request.state.correlation_id,
            )

    @app.get(
        "/registry/agents",
        response_model=list[AgentSummary],
        tags=["registry"],
    )
    async def list_agents() -> list[AgentSummary]:
        return await asyncio.to_thread(registry.list_agents)

    @app.get(
        "/registry/agents/{agent_name}",
        response_model=AgentSummary,
        tags=["registry"],
    )
    async def get_agent(agent_name: str) -> AgentSummary:
        return await asyncio.to_thread(registry.get_agent, agent_name)

    @app.get(
        "/registry/agents/{agent_name}/versions",
        response_model=list[AgentVersionView],
        tags=["registry"],
    )
    async def list_agent_versions(agent_name: str) -> list[AgentVersionView]:
        return await asyncio.to_thread(registry.list_versions, agent_name)

    @app.get(
        "/registry/agents/{agent_name}/versions/{version}",
        response_model=AgentVersionView,
        tags=["registry"],
    )
    async def get_agent_version(agent_name: str, version: str) -> AgentVersionView:
        return await asyncio.to_thread(registry.get_version, agent_name, version)

    @app.post(
        "/registry/agents/{agent_name}/versions/{version}/transitions",
        response_model=AgentVersionView,
        tags=["registry"],
    )
    async def transition_agent_version(
        agent_name: str,
        version: str,
        change: LifecycleTransitionRequest,
        request: Request,
    ) -> AgentVersionView:
        with telemetry.span(
            "registry.transition",
            {
                Attribute.AGENT_NAME: agent_name,
                Attribute.AGENT_VERSION: version,
                Attribute.RELEASE_ID: request.state.release_id,
            },
        ):
            return await asyncio.to_thread(
                registry.transition,
                agent_name,
                version,
                target=change.target_state,
                actor=change.actor,
                reason=change.reason,
                expected_revision=change.expected_revision,
                correlation_id=request.state.correlation_id,
            )

    @app.get(
        "/registry/agents/{agent_name}/versions/{version}/audit",
        response_model=list[AuditEventView],
        tags=["registry"],
    )
    async def list_version_audit(agent_name: str, version: str) -> list[AuditEventView]:
        return await asyncio.to_thread(registry.list_audit_events, agent_name, version)

    @app.get("/registry", response_class=FileResponse, include_in_schema=False)
    async def registry_console() -> FileResponse:
        return FileResponse(registry_page_path())

    @app.post(
        "/evaluations/runs",
        response_model=EvaluationRunReport,
        tags=["evaluations"],
    )
    async def run_evaluation(
        evaluation_request: RunEvaluationRequest,
        request: Request,
    ) -> EvaluationRunReport:
        with telemetry.span(
            "evaluation.request",
            {
                Attribute.AGENT_NAME: evaluation_request.agent_name,
                Attribute.AGENT_VERSION: evaluation_request.agent_version,
                Attribute.EVALUATION_SUITE: evaluation_request.suite_id,
                Attribute.RELEASE_ID: request.state.release_id,
            },
        ):
            return await evaluation_service.run(evaluation_request)

    @app.get(
        "/evaluations/runs",
        response_model=list[EvaluationRunSummary],
        tags=["evaluations"],
    )
    async def list_evaluations(agent_name: str | None = None) -> list[EvaluationRunSummary]:
        return await asyncio.to_thread(evaluations.list, agent_name)

    @app.get(
        "/evaluations/runs/{run_id}/comparison",
        response_model=GateDecision,
        tags=["evaluations"],
    )
    async def evaluation_comparison(run_id: UUID) -> GateDecision:
        report = await asyncio.to_thread(evaluations.get, run_id)
        return report.gate

    @app.get(
        "/evaluations/runs/{run_id}",
        response_model=EvaluationRunReport,
        tags=["evaluations"],
    )
    async def get_evaluation(run_id: UUID) -> EvaluationRunReport:
        return await asyncio.to_thread(evaluations.get, run_id)

    @app.get("/evaluations", response_class=FileResponse, include_in_schema=False)
    async def evaluation_console() -> FileResponse:
        return FileResponse(evaluation_page_path())

    @app.post(
        "/releases/candidates",
        response_model=CandidateResult,
        tags=["releases"],
    )
    async def create_release_candidate(
        candidate: CreateCandidateRequest,
        request: Request,
    ) -> CandidateResult:
        with telemetry.span(
            "release.candidate",
            {
                Attribute.AGENT_NAME: candidate.agent_name,
                Attribute.AGENT_VERSION: candidate.agent_version,
                Attribute.RELEASE_ID: request.state.release_id,
            },
        ):
            return await asyncio.to_thread(release_service.create_candidate, candidate)

    @app.get("/releases", response_model=list[ReleaseView], tags=["releases"])
    async def list_releases(agent_name: str | None = None) -> list[ReleaseView]:
        return await asyncio.to_thread(releases.list_releases, agent_name)

    @app.get("/releases/{release_id}", response_model=ReleaseView, tags=["releases"])
    async def get_release(release_id: UUID) -> ReleaseView:
        return await asyncio.to_thread(releases.get, release_id)

    @app.post(
        "/releases/{release_id}/transitions",
        response_model=ReleaseView,
        tags=["releases"],
    )
    async def promote_release(
        release_id: UUID,
        change: PromoteReleaseRequest,
        request: Request,
    ) -> ReleaseView:
        with telemetry.span(
            "release.promote",
            {
                Attribute.RELEASE_ID: str(release_id),
                Attribute.CORRELATION_ID: request.state.correlation_id,
            },
        ):
            return await asyncio.to_thread(release_service.promote, release_id, change)

    @app.get(
        "/releases/{release_id}/events",
        response_model=list[ReleaseEventView],
        tags=["releases"],
    )
    async def list_release_events(release_id: UUID) -> list[ReleaseEventView]:
        return await asyncio.to_thread(releases.events, release_id)

    @app.get(
        "/releases/{release_id}/notes",
        response_model=ReleaseNotes,
        tags=["releases"],
    )
    async def release_notes(release_id: UUID) -> ReleaseNotes:
        return await asyncio.to_thread(release_service.notes, release_id)

    async def current_fleet_health() -> FleetHealth:
        summaries = await asyncio.to_thread(registry.list_agents)
        versions = {
            "inventory-agent": "1.0.0",
            "knowledge-agent": "1.0.0",
            "shopping-agent": "1.0.0",
        }
        versions.update({str(summary.name): str(summary.latest_version) for summary in summaries})
        return fleet_health(telemetry, versions)

    @app.get(
        "/observability/fleet",
        response_model=FleetHealth,
        tags=["observability"],
    )
    async def get_fleet_health() -> FleetHealth:
        return await current_fleet_health()

    @app.get(
        "/observability/agents/{agent_name}",
        response_model=AgentHealth,
        tags=["observability"],
    )
    async def get_agent_health(agent_name: str) -> AgentHealth:
        health = await current_fleet_health()
        for agent in health.agents:
            if agent.agent_name == agent_name:
                return agent
        raise HTTPException(status_code=404, detail="Agent observability data was not found")

    @app.get("/observability", response_class=FileResponse, include_in_schema=False)
    async def observability_console() -> FileResponse:
        return FileResponse(observability_page_path())

    return app


app = create_app()
