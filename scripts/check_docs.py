"""Validate local Markdown targets, documented Make targets, and image formats."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
MAKE_COMMAND = re.compile(r"\bmake\s+([a-zA-Z0-9][a-zA-Z0-9_-]*)")
MAKE_TARGET = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9_-]*):", re.MULTILINE)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def markdown_files() -> list[Path]:
    """Return authored Markdown without traversing caches or virtual environments."""
    return sorted({*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md")})


def local_target(source: Path, raw_target: str) -> Path | None:
    """Resolve a local Markdown target, ignoring URLs and same-document anchors."""
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = target.split(maxsplit=1)[0]
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    path_text = unquote(target.split("#", maxsplit=1)[0])
    if not path_text:
        return None
    return (source.parent / path_text).resolve()


def validate() -> list[str]:
    """Return deterministic validation failures."""
    failures: list[str] = []
    for source in markdown_files():
        text = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = local_target(source, raw_target)
            if target is not None and not target.exists():
                failures.append(f"{source.relative_to(ROOT)}: missing local target {raw_target}")

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = set(MAKE_TARGET.findall(makefile))
    for source in (ROOT / "README.md", ROOT / "docs/demos/final-walkthrough.md"):
        for command in MAKE_COMMAND.findall(source.read_text(encoding="utf-8")):
            if command not in targets:
                failures.append(f"{source.relative_to(ROOT)}: unknown Make target {command}")

    for image in sorted((ROOT / "docs/images").glob("*.png")):
        if image.read_bytes()[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
            failures.append(f"{image.relative_to(ROOT)}: extension does not match PNG data")
    return failures


def main() -> int:
    failures = validate()
    if failures:
        print("Documentation smoke test failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        f"Documentation smoke test passed for {len(markdown_files())} Markdown files "
        "and all documented Make targets."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
