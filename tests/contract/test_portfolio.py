"""Public portfolio remains available without a running database."""

from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from apps.web.portfolio import PAGES
from scripts.export_portfolio import export


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        url = values.get("src") if tag == "script" else values.get("href")
        if url and url.startswith("/"):
            self.urls.add(url)


@pytest.mark.contract
def test_portfolio_routes_and_assets_are_available_without_database() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    client = TestClient(app)
    for path in PAGES:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert 'id="main-content"' in response.text
        links = Links()
        links.feed(response.text)
        for url in links.urls:
            assert client.get(url).status_code == 200, (path, url)


@pytest.mark.contract
def test_static_mount_cannot_read_application_source() -> None:
    client = TestClient(create_app(Settings(environment="test", _env_file=None)))
    assert client.get("/assets/%2e%2e/portfolio.py").status_code == 404
    assert (
        client.get("/assets/demo.js")
        .headers["content-type"]
        .startswith(("text/javascript", "application/javascript"))
    )


@pytest.mark.contract
def test_public_export_has_working_internal_links_and_no_live_controls(tmp_path: Path) -> None:
    export(tmp_path, "/AgentHub")
    for route in PAGES:
        page = tmp_path / route.removeprefix("/") / "index.html"
        html = page.read_text(encoding="utf-8")
        assert 'data-static="true"' in html
        links = Links()
        links.feed(html)
        for url in links.urls:
            assert url.startswith("/AgentHub/"), (route, url)
            target = tmp_path / url.removeprefix("/AgentHub/")
            assert target.is_file() or (target / "index.html").is_file(), (route, url)
    assert "Run the full system locally" in (tmp_path / "console/index.html").read_text()
    assert "publicPreview" in (tmp_path / "assets/demo.js").read_text()
