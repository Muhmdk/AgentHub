PYTHON ?= python3.14
VENV := .venv
BIN := $(VENV)/bin
UV_VERSION := 0.12.11

.PHONY: setup lock format lint typecheck test test-unit test-contract test-integration test-e2e security up observability-up observability-down migrate seed-registry run demo-inventory demo-knowledge demo-shopping ingest-corpus benchmark-rag evaluate evaluate-bad down clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install uv==$(UV_VERSION)
	$(BIN)/uv sync --active --frozen --group dev --inexact

lock:
	$(BIN)/uv lock

format:
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

lint:
	$(BIN)/ruff format --check .
	$(BIN)/ruff check .

typecheck:
	$(BIN)/mypy agents apps packages tests

test:
	$(BIN)/pytest

test-unit:
	$(BIN)/pytest -m unit --no-cov

test-contract:
	$(BIN)/pytest -m contract --no-cov

test-integration:
	$(BIN)/pytest -m integration --no-cov

test-e2e:
	$(BIN)/pytest -m e2e --no-cov

security:
	git ls-files -z | xargs -0 $(BIN)/detect-secrets-hook --baseline .secrets.baseline
	$(BIN)/pip-audit

up:
	docker compose up --detach --wait postgres

observability-up:
	docker compose up --detach postgres tempo otel-collector prometheus grafana

observability-down:
	docker compose stop grafana prometheus otel-collector tempo

migrate:
	$(BIN)/alembic upgrade head

seed-registry:
	$(BIN)/python -m packages.registry.bootstrap

run:
	$(BIN)/python -m apps.api

demo-inventory:
	$(BIN)/python -m agents.inventory

demo-knowledge:
	$(BIN)/python -m agents.knowledge

demo-shopping:
	$(BIN)/python -m agents.shopping

ingest-corpus:
	$(BIN)/python -m agents.shared.ingest

benchmark-rag:
	$(BIN)/python -m agents.shared.benchmark

evaluate:
	$(BIN)/python -m packages.evaluation

evaluate-bad:
	$(BIN)/python -m packages.evaluation --candidate-profile regressed

down:
	docker compose down

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache coverage.xml htmlcov
