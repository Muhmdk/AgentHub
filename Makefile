PYTHON ?= python3.14
VENV := .venv
BIN := $(VENV)/bin
UV_VERSION := 0.12.11
TERRAFORM ?= terraform
HELM ?= helm
KUBECONFORM ?= kubeconform
HELM_CHART := deploy/helm/agenthub
HELM_CI_VALUES := tests/fixtures/helm/values-ci.yaml

.PHONY: setup lock format lint typecheck test test-unit test-contract test-integration test-e2e security infra-terraform infra-helm infra-validate smoke-deployment up observability-up observability-down migrate seed-registry run demo-inventory demo-knowledge demo-shopping ingest-corpus benchmark-rag evaluate evaluate-bad simulate-release simulate-release-bad down clean

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
	$(BIN)/mypy agents apps packages scripts tests

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

infra-terraform:
	$(TERRAFORM) fmt -check -recursive infra/terraform
	$(TERRAFORM) -chdir=infra/terraform/bootstrap init -backend=false -input=false
	$(TERRAFORM) -chdir=infra/terraform/bootstrap validate
	$(TERRAFORM) -chdir=infra/terraform/modules/foundation init -backend=false -input=false
	$(TERRAFORM) -chdir=infra/terraform/modules/foundation test
	$(TERRAFORM) -chdir=infra/terraform/modules/platform init -backend=false -input=false
	$(TERRAFORM) -chdir=infra/terraform/modules/platform test
	$(TERRAFORM) -chdir=infra/terraform/environments/dev init -backend=false -input=false
	$(TERRAFORM) -chdir=infra/terraform/environments/dev validate

infra-helm:
	$(HELM) lint $(HELM_CHART) --strict
	$(HELM) lint $(HELM_CHART) --strict --values $(HELM_CHART)/values-local.yaml
	$(HELM) lint $(HELM_CHART) --strict --values $(HELM_CHART)/values-dev.yaml --values $(HELM_CI_VALUES)
	@render_dir=$$(mktemp -d); \
	trap 'rm -rf "$$render_dir"' EXIT; \
	$(HELM) template agenthub $(HELM_CHART) --namespace agenthub \
		--values $(HELM_CHART)/values-local.yaml > "$$render_dir/local.yaml"; \
	$(HELM) template agenthub $(HELM_CHART) --namespace agenthub \
		--values $(HELM_CHART)/values-dev.yaml --values $(HELM_CI_VALUES) > "$$render_dir/dev.yaml"; \
	$(KUBECONFORM) -strict -summary -ignore-missing-schemas "$$render_dir/local.yaml" "$$render_dir/dev.yaml"; \
	$(BIN)/python scripts/validate_kubernetes_security.py --require-image-digest "$$render_dir/dev.yaml"

infra-validate: infra-terraform infra-helm

smoke-deployment:
	test -n "$(BASE_URL)"
	$(BIN)/python scripts/smoke_deployment.py --base-url "$(BASE_URL)" $(SMOKE_ARGS)

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

simulate-release:
	$(BIN)/python -m packages.release simulate --pipeline-id local-release-pass

simulate-release-bad:
	$(BIN)/python -m packages.release simulate --pipeline-id local-release-block --candidate-profile regressed

down:
	docker compose down

clean:
	rm -rf .coverage .mypy_cache .pytest_cache .ruff_cache coverage.xml htmlcov
