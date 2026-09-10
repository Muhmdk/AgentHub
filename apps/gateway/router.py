"""FastAPI router for authenticated agent invocation."""

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from apps.gateway.identity import CallerIdentity, GatewayAuthenticationError, GatewayAuthenticator
from packages.contracts.retrieval import GroundedAgentResponse
from packages.contracts.runtime import AgentRequest, AgentResponse
from packages.observability.conventions import Attribute
from packages.observability.telemetry import Telemetry


class AgentTarget(Protocol):
    """Agent capability exposed through the gateway."""

    async def invoke(self, request: AgentRequest) -> AgentResponse: ...


def create_gateway_router(
    *,
    authenticator: GatewayAuthenticator,
    targets: dict[str, AgentTarget],
    telemetry: Telemetry,
) -> APIRouter:
    """Build the authenticated data-plane ingress router."""
    router = APIRouter(prefix="/gateway", tags=["gateway"])

    async def authenticate_caller(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        claimed_identity: Annotated[str | None, Header(alias="X-AgentHub-Identity")] = None,
    ) -> CallerIdentity:
        try:
            identity = authenticator.authenticate(
                authorization=authorization,
                claimed_identity=claimed_identity,
            )
        except GatewayAuthenticationError as exc:
            raise HTTPException(
                status_code=401,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        request.state.caller_identity = identity
        return identity

    @router.post(
        "/agents/{agent_name}/invoke",
        response_model=GroundedAgentResponse | AgentResponse,
    )
    async def invoke_agent(
        agent_name: str,
        agent_request: AgentRequest,
        request: Request,
        _caller: Annotated[CallerIdentity, Depends(authenticate_caller)],
    ) -> AgentResponse:
        target = targets.get(agent_name)
        if target is None:
            raise HTTPException(status_code=404, detail="Agent is not available")
        with telemetry.span(
            "gateway.request",
            {
                Attribute.AGENT_NAME: agent_name,
                Attribute.CORRELATION_ID: request.state.correlation_id,
                Attribute.RELEASE_ID: request.state.release_id,
            },
        ):
            response = await target.invoke(agent_request)
        return response

    return router
