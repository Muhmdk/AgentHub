"""Public portfolio remains available without a running database."""

from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from apps.web.portfolio import PAGES


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
