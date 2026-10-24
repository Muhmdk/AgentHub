"""Export the read-only portfolio for a project-path static host."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from apps.web.portfolio import PAGES, render_page

ROOT = Path(__file__).parents[1]
LOCAL_ATTRIBUTE = re.compile(r'(?P<attribute>href|src)="(?P<url>/[^"]*)"')


def static_url(url: str, base_path: str) -> str:
    """Map application routes to the static copy without exposing API paths."""
    parsed = urlsplit(url)
    if parsed.path.startswith(("/assets/", "/images/")):
        return f"{base_path}{parsed.path}"
    if parsed.path in PAGES:
        suffix = "" if parsed.path == "/" else f"{parsed.path.removeprefix('/')}/"
        return f"{base_path}/{suffix}"
    return f"{base_path}/try-locally/"


def export(output_dir: Path, base_path: str = "/AgentHub") -> None:
    if base_path and (
        not base_path.startswith("/")
        or base_path.endswith("/")
        or ".." in base_path
        or "//" in base_path
    ):
        raise ValueError(
            "base path must be empty or a clean absolute path without a trailing slash"
        )
    for route in PAGES:
        document = render_page(route, public=True)
        document = LOCAL_ATTRIBUTE.sub(
            lambda match: (
                f'{match.group("attribute")}="{static_url(match.group("url"), base_path)}"'
            ),
            document,
        )
        page_dir = output_dir if route == "/" else output_dir / route.removeprefix("/")
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(document, encoding="utf-8")

    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for asset in (ROOT / "apps/web/assets").iterdir():
        if asset.suffix in {".css", ".js"}:
            shutil.copy2(asset, assets / asset.name)

    images = output_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    for image in (ROOT / "docs/images").glob("*.png"):
        shutil.copy2(image, images / image.name)
    (output_dir / ".nojekyll").touch()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/portfolio")
    parser.add_argument("--base-path", default="/AgentHub")
    args = parser.parse_args()
    export(args.output, args.base_path)
    print(f"Exported {len(PAGES)} read-only pages to {args.output}")


if __name__ == "__main__":
    main()
