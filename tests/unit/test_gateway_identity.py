"""Authentication tests for the gateway boundary."""

import pytest
from pydantic import SecretStr

from apps.gateway.identity import GatewayAuthenticationError, GatewayAuthenticator

_TOKEN = "gateway-test-token-with-at-least-32-characters"


@pytest.mark.unit
def test_local_identity_is_explicit_and_marked_non_production() -> None:
    authenticator = GatewayAuthenticator(environment="test", service_tokens={})

    identity = authenticator.authenticate(
        authorization=None,
        claimed_identity="local/contract-test",
    )

    assert identity.subject == "local/contract-test"
    assert identity.method == "local-explicit"
    assert identity.environment == "test"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("authorization", "identity"),
    [
        (None, None),
        (None, "service/runtime"),
        (None, "invalid identity"),
        ("Basic credentials", "service/runtime"),
        ("Bearer wrong-token", "service/runtime"),
        (f"Bearer {_TOKEN}", "service/other"),
    ],
)
def test_invalid_credentials_have_one_safe_failure(
    authorization: str | None,
    identity: str | None,
) -> None:
    authenticator = GatewayAuthenticator(
        environment="production",
        service_tokens={"service/runtime": SecretStr(_TOKEN)},
    )

    with pytest.raises(GatewayAuthenticationError, match="Gateway authentication required"):
        authenticator.authenticate(
            authorization=authorization,
            claimed_identity=identity,
        )


@pytest.mark.unit
def test_bearer_credential_establishes_configured_service_identity() -> None:
    authenticator = GatewayAuthenticator(
        environment="production",
        service_tokens={"service/runtime": SecretStr(_TOKEN)},
    )

    identity = authenticator.authenticate(
        authorization=f"Bearer {_TOKEN}",
        claimed_identity="service/runtime",
    )

    assert identity.subject == "service/runtime"
    assert identity.method == "bearer"
    assert identity.environment == "production"
