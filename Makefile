PYTHON ?= python3.14
VENV := .venv
BIN := $(VENV)/bin
UV_VERSION := 0.12.11

.PHONY: setup lock format lint typecheck test test-unit test-contract test-integration test-e2e security run down clean

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
	$(BIN)/mypy apps packages tests

test:
	$(BIN)/pytest

test-unit:
	$(BIN)/pytest -m unit

test-contract:
	$(BIN)/pytest -m contract

test-integration:
	$(BIN)/pytest -m integration

test-e2e:
	$(BIN)/pytest -m e2e

security:
	git ls-files -z | xargs -0 $(BIN)/detect-secrets-hook --baseline .secrets.baseline
	$(BIN)/pip-audit

run:
	$(BIN)/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

down:
	@echo "AgentHub runs in the foreground; press Ctrl-C in the server terminal to stop it."

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache coverage.xml htmlcov
