ARG PYTHON_BASE=python:3.14.3-slim@sha256:5e59aae31ff0e87511226be8e2b94d78c58f05216efda3b07dbbed938ec8583b

FROM ${PYTHON_BASE} AS builder

ARG UV_VERSION=0.12.11
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
    && python -m compileall -q agents apps packages

FROM ${PYTHON_BASE} AS runtime

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

RUN groupadd --gid 10001 agenthub \
    && useradd --uid 10001 --gid agenthub --no-create-home --shell /usr/sbin/nologin agenthub

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app /app

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"]
ENTRYPOINT ["/app/.venv/bin/python", "-m", "apps.api"]
