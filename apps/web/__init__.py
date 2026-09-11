"""Small operator-facing views composed by the AgentHub API."""

from importlib.resources import files
from pathlib import Path


def registry_page_path() -> Path:
    return Path(str(files("apps.web").joinpath("registry.html")))


def evaluation_page_path() -> Path:
    return Path(str(files("apps.web").joinpath("evaluations.html")))


def observability_page_path() -> Path:
    return Path(str(files("apps.web").joinpath("observability.html")))


def governance_page_path() -> Path:
    return Path(str(files("apps.web").joinpath("governance.html")))


def delivery_page_path() -> Path:
    return Path(str(files("apps.web").joinpath("delivery.html")))


def incident_page_path() -> Path:
    return Path(str(files("apps.web").joinpath("incidents.html")))
