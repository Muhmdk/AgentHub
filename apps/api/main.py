"""FastAPI composition root for the AgentHub control plane."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
from packages.contracts.health import HealthResponse, VersionResponse
from packages.contracts.retrieval import GroundedAgentResponse
from packages.contracts.runtime import AgentRequest, AgentResponse

logger = logging.getLogger("agenthub.api")


def create_app(
    settings: Settings | None = None,
    inventory_agent: InventoryAgent | None = None,
    knowledge_agent: KnowledgeAgent | None = None,
    shopping_agent: ShoppingAgent | None = None,
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("service_started")
        yield
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
    app.middleware("http")(correlation_middleware)
    register_error_handlers(app)

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok", service=app_settings.service_name)

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    async def readiness() -> HealthResponse:
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

    return app


app = create_app()
