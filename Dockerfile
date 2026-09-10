ARG PYTHON_BUILDER=cgr.dev/chainguard/python:latest-dev@sha256:725c9da49a8d07f1449f7f9751432eef57801376258b223e3951c67245824085
ARG PYTHON_RUNTIME=cgr.dev/chainguard/python:latest@sha256:fd502ec3300f98c4a7c4fb57314116c139291661cbff6b657e2297f2ada76930

FROM ${PYTHON_BUILDER} AS builder

ARG UV_VERSION=0.12.11
USER root
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:${PATH}
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY agents ./agents
COPY apps ./apps
COPY packages ./packages
COPY data ./data
COPY migrations ./migrations
COPY alembic.ini ./

RUN python -m venv "${VIRTUAL_ENV}" \
    && python -m pip install "uv==${UV_VERSION}" \
    && uv sync --active --frozen --no-dev --no-editable \
    && python -m pip uninstall --yes uv setuptools pip \
    && python -m compileall -q agents apps packages

FROM ${PYTHON_RUNTIME} AS runtime

ARG SOURCE_SHA=unknown
ARG VERSION=0.3.0-dev
LABEL org.opencontainers.image.title="AgentHub" \
      org.opencontainers.image.description="AgentOps and ModelOps control plane" \
      org.opencontainers.image.source="https://github.com/Muhmdk/AgentHub" \
      org.opencontainers.image.revision="${SOURCE_SHA}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:${PATH} \
    AGENTHUB_API_HOST=0.0.0.0 \
    AGENTHUB_API_PORT=8000

WORKDIR /app
COPY --from=builder --chown=65532:65532 /app /app

USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"]
ENTRYPOINT ["/app/.venv/bin/python", "-m", "apps.api"]
