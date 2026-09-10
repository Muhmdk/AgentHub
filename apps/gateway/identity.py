"""Caller authentication at the AgentHub data-plane boundary."""

import hmac
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import SecretStr

Environment = Literal["local", "test", "staging", "production"]
AuthenticationMethod = Literal["local-explicit", "bearer"]

_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,127}$")
_LOCAL_PREFIX = "local/"


class GatewayAuthenticationError(RuntimeError):
    """Safe authentication failure with no credential details."""


@dataclass(frozen=True)
class CallerIdentity:
    """Authenticated caller propagated to later authorization decisions."""

    subject: str
    method: AuthenticationMethod
    environment: Environment


class GatewayAuthenticator:
    """Authenticate explicit local identities or configured service credentials."""

    def __init__(
        self,
        *,
        environment: Environment,
        service_tokens: dict[str, SecretStr],
    ) -> None:
        self._environment = environment
        self._service_tokens = dict(service_tokens)

    def authenticate(
        self,
        *,
        authorization: str | None,
        claimed_identity: str | None,
    ) -> CallerIdentity:
        """Return a verified identity or one generic authentication failure."""
        identity = self._normalize_identity(claimed_identity)
        token = self._bearer_token(authorization)

        if token is not None:
            expected = self._service_tokens.get(identity)
            if expected is not None and hmac.compare_digest(token, expected.get_secret_value()):
                return CallerIdentity(
                    subject=identity,
                    method="bearer",
                    environment=self._environment,
                )
            raise GatewayAuthenticationError("Gateway authentication required")

        if self._environment in {"local", "test"} and identity.startswith(_LOCAL_PREFIX):
            return CallerIdentity(
                subject=identity,
                method="local-explicit",
                environment=self._environment,
            )

        raise GatewayAuthenticationError("Gateway authentication required")

    @staticmethod
    def _normalize_identity(candidate: str | None) -> str:
        if candidate is None:
            raise GatewayAuthenticationError("Gateway authentication required")
        identity = candidate.strip()
        if not _IDENTITY_PATTERN.fullmatch(identity):
            raise GatewayAuthenticationError("Gateway authentication required")
        return identity

    @staticmethod
    def _bearer_token(authorization: str | None) -> str | None:
        if authorization is None:
            return None
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token or token.strip() != token:
            raise GatewayAuthenticationError("Gateway authentication required")
        return token
