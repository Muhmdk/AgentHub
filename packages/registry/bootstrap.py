"""Register the committed demonstration manifests into PostgreSQL."""

import json
from pathlib import Path

from apps.api.config import load_settings
from packages.contracts.manifest import AgentManifest
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository


def main() -> int:
    settings = load_settings()
    database = Database(settings.database_url)
    manifest_paths = sorted((Path(__file__).parents[2] / "data" / "manifests").glob("*.json"))
    try:
        repository = RegistryRepository(database)
        results = [
            repository.register(
                AgentManifest.model_validate_json(path.read_text(encoding="utf-8")),
                actor="demo-manifest-bootstrap",
                correlation_id=f"bootstrap-{path.stem}",
            )
            for path in manifest_paths
        ]
    finally:
        database.dispose()
    print(
        json.dumps(
            {
                "manifest_count": len(results),
                "created_count": sum(result.created for result in results),
                "versions": [
                    {
                        "name": result.agent_version.manifest.metadata.name,
                        "version": result.agent_version.version,
                        "created": result.created,
                    }
                    for result in results
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
