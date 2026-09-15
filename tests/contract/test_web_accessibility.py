"""Static accessibility contracts for the dependency-free operator consoles."""

from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PAGES = sorted((ROOT / "apps" / "web").glob("*.html"))


class LandmarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.main_ids: list[str | None] = []
        self.skip_targets: list[str | None] = []
        self.status_regions: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "main":
            self.main_ids.append(attributes.get("id"))
        if tag == "a" and "skip-link" in (attributes.get("class") or "").split():
            self.skip_targets.append(attributes.get("href"))
        if attributes.get("id") == "status":
            self.status_regions.append(attributes)


@pytest.mark.contract
@pytest.mark.parametrize("page", PAGES, ids=lambda path: path.stem)
def test_console_has_keyboard_and_live_region_landmarks(page: Path) -> None:
    source = page.read_text(encoding="utf-8")
    parser = LandmarkParser()
    parser.feed(source)

    assert parser.main_ids == ["main-content"]
    assert parser.skip_targets == ["#main-content"]
    assert parser.status_regions == [
        {
            "id": "status",
            "role": "status",
            "aria-live": "polite",
            "aria-atomic": "true",
        }
    ]
    assert ":focus-visible" in source
    assert "[hidden] { display: none !important; }" in source
    assert "outline: none" not in source
    assert "aria-busy" in source
    assert "showError" in source


@pytest.mark.contract
def test_data_tables_have_captions_and_column_scopes() -> None:
    for name in ("registry.html", "evaluations.html", "delivery.html", "governance.html"):
        source = (ROOT / "apps" / "web" / name).read_text(encoding="utf-8")
        assert "caption" in source
        assert 'scope="col"' in source or 'scope = "col"' in source


@pytest.mark.contract
def test_cost_console_distinguishes_measurements_from_projections() -> None:
    source = (ROOT / "apps" / "web" / "delivery.html").read_text(encoding="utf-8")

    assert "Observed cost attribution" in source
    assert "measured · last 60m" in source
    assert "What-if model projection" in source
    assert "illustrative rate card" in source
    assert "Decision support only" in source
