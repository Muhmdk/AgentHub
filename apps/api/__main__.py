"""Run the AgentHub API from its validated environment configuration."""

import uvicorn as uvicorn

from apps.api.config import load_settings
from apps.api.logging import configure_logging


def main() -> None:
    """Start the local API server."""
    settings = load_settings()
    configure_logging(settings)
    uvicorn.run(
        "apps.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
