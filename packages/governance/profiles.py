"""Immutable runtime policy profiles for the demonstration agents."""

from packages.contracts.governance import (
    PolicyAgent,
    PolicyModelGrant,
    PolicyToolGrant,
    ToolAccess,
)


def agent_policy_profiles(model_name: str) -> dict[str, PolicyAgent]:
    """Return the deployed agent facts used for immediate runtime decisions."""
    provider, separator, model = model_name.partition("/")
    if not separator:
        raise ValueError("Model names must include a provider prefix")
    model_grant = PolicyModelGrant(provider=provider, model=model)
    return {
        "inventory-agent": PolicyAgent(
            name="inventory-agent",
            version="1.0.0",
            owner="retail-ai-team",
            risk_tier="medium",
            tools=[
                PolicyToolGrant(name=name, scopes=[scope], access=ToolAccess.READ)
                for name, scope in (
                    ("inventory.read", "inventory:read"),
                    ("sales.read", "sales:read"),
                    ("promotions.read", "promotions:read"),
                    ("weather.read", "weather:read"),
                )
            ],
            model=model_grant,
        ),
        "knowledge-agent": PolicyAgent(
            name="knowledge-agent",
            version="1.0.0",
            owner="retail-ai-team",
            risk_tier="low",
            model=model_grant,
        ),
        "shopping-agent": PolicyAgent(
            name="shopping-agent",
            version="1.0.0",
            owner="retail-ai-team",
            risk_tier="medium",
            tools=[
                PolicyToolGrant(
                    name="product.search",
                    scopes=["catalog:read"],
                    access=ToolAccess.READ,
                )
            ],
            model=model_grant,
        ),
    }
