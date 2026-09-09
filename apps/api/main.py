"""FastAPI composition root for the AgentHub control plane."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

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
from apps.web import registry_page_path
from packages.contracts.health import HealthResponse, VersionResponse
from packages.contracts.manifest import AgentManifest
from packages.contracts.registry import (
    AgentSummary,
    AgentVersionView,
    AuditEventView,
    LifecycleTransitionRequest,
    RegistrationResult,
)
from packages.contracts.retrieval import GroundedAgentResponse
from packages.contracts.runtime import AgentRequest, AgentResponse
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository, RegistryStore

logger = logging.getLogger("agenthub.api")


def create_app(
    settings: Settings | None = None,
    inventory_agent: InventoryAgent | None = None,
    knowledge_agent: KnowledgeAgent | None = None,
    shopping_agent: ShoppingAgent | None = None,
    database: Database | None = None,
    registry_store: RegistryStore | None = None,
) -> FastAPI:
    """Create an application with explicit, testable dependencies."""
    app_settings = settings or load_settings()
    configure_logging(app_settings)
    model = create_chat_model(app_settings.model_provider)
    inventory = inventory_agent or InventoryAgent(
        data=RetailData.load(),
        model=model,
        max_steps=app_settings.agent_max_steps,
        tool_timeout_seconds=app_settings.tool_timeout_seconds,
        execution_timeout_seconds=app_settings.agent_timeout_seconds,
    )
    retriever, corpus, _ = create_retail_retriever()
    knowledge = knowledge_agent or KnowledgeAgent(
        retriever=retriever,
        corpus=corpus,
        model=model,
        top_k=app_settings.rag_top_k,
        minimum_score=app_settings.rag_minimum_score,
        timeout_seconds=app_settings.retrieval_timeout_seconds,
    )
    shopping = shopping_agent or ShoppingAgent(
        product_tool=ProductSearchTool(retriever, corpus),
        model=model,
        timeout_seconds=app_settings.agent_timeout_seconds,
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("service_started")
        try:
            yield
        finally:
            if owns_registry_database and registry_database is not None:
                registry_database.dispose()
            logger.info("service_stopped")

    app = FastAPI(
        title="AgentHub API",
        version=app_settings.version,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.inventory_agent = inventory
    app.state.knowledge_agent = knowledge
    app.state.shopping_agent = shopping
    app.state.registry = registry
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

    return app


app = create_app()
