"""Managed-identity adapters for Azure OpenAI and Azure AI Search."""

import asyncio
import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from azure.identity import DefaultAzureCredential
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from packages.contracts.retrieval import Chunk, RetrievalTrace, SearchRequest, SearchResult
from packages.contracts.runtime import JsonScalar, JsonValue, ModelRequest, ModelResponse, Usage

AZURE_OPENAI_SCOPE = "https://cognitiveservices.azure.com/.default"
AZURE_SEARCH_SCOPE = "https://search.azure.com/.default"
AZURE_SEARCH_API_VERSION = "2026-04-01"
_FILTER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_INDEX_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,126}[a-z0-9]$")


class AzureProviderError(RuntimeError):
    """Sanitized cloud-boundary failure safe to expose to application logs."""


class AccessTokenProvider(Protocol):
    """Minimal token boundary implemented by Azure Identity in production."""

    def get_token(self, scope: str) -> str: ...

    def close(self) -> None: ...


class JsonHttpTransport(Protocol):
    """Injectable JSON transport that keeps adapter tests offline."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, JsonValue],
        timeout_seconds: float,
    ) -> dict[str, JsonValue]: ...


class DefaultAzureTokenProvider:
    """Acquire Entra tokens through DefaultAzureCredential."""

    def __init__(self, managed_identity_client_id: str | None = None) -> None:
        self._credential = DefaultAzureCredential(
            managed_identity_client_id=managed_identity_client_id
        )

    def get_token(self, scope: str) -> str:
        try:
            return self._credential.get_token(scope).token
        except Exception as exc:
            raise AzureProviderError("Azure identity could not acquire an access token") from exc

    def close(self) -> None:
        self._credential.close()


class UrllibJsonTransport:
    """Small standard-library transport with sanitized error handling."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, JsonValue],
        timeout_seconds: float,
    ) -> dict[str, JsonValue]:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                decoded = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AzureProviderError("Azure provider request failed") from exc
        if not isinstance(decoded, dict):
            raise AzureProviderError("Azure provider returned an invalid response")
        return cast(dict[str, JsonValue], decoded)


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Azure endpoint must be an HTTPS origin or path")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class AzureOpenAIConfig:
    """Explicit connection and accounting settings for one model deployment."""

    endpoint: str
    deployment: str
    token_scope: str = AZURE_OPENAI_SCOPE
    timeout_seconds: float = 10.0
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _validate_endpoint(self.endpoint))
        if not self.deployment.strip():
            raise ValueError("Azure OpenAI deployment is required")
        if not self.token_scope.strip():
            raise ValueError("Azure OpenAI token scope is required")
        if self.timeout_seconds <= 0:
            raise ValueError("Azure OpenAI timeout must be positive")
        if self.input_cost_per_million < 0 or self.output_cost_per_million < 0:
            raise ValueError("Azure OpenAI token costs cannot be negative")


@dataclass(frozen=True)
class AzureSearchConfig:
    """Explicit connection settings for one pre-created search index."""

    endpoint: str
    index_name: str
    api_version: str = AZURE_SEARCH_API_VERSION
    token_scope: str = AZURE_SEARCH_SCOPE
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _validate_endpoint(self.endpoint))
        if not _INDEX_NAME.fullmatch(self.index_name):
            raise ValueError("Azure Search index name is invalid")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.api_version):
            raise ValueError("Azure Search API version is invalid")
        if not self.token_scope.strip():
            raise ValueError("Azure Search API version and token scope are required")
        if self.timeout_seconds <= 0:
            raise ValueError("Azure Search timeout must be positive")


class _OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str


class _OpenAIChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _OpenAIMessage


class _OpenAIUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class _OpenAIResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    choices: list[_OpenAIChoice] = Field(min_length=1)
    usage: _OpenAIUsage


class AzureOpenAIChatModel:
    """OpenAI-compatible Azure model adapter authenticated with Entra ID."""

    def __init__(
        self,
        config: AzureOpenAIConfig,
        token_provider: AccessTokenProvider,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._transport = transport or UrllibJsonTransport()

    @property
    def name(self) -> str:
        return f"azure-openai/{self._config.deployment}"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return await asyncio.to_thread(self._generate, request)

    def _generate(self, request: ModelRequest) -> ModelResponse:
        token = self._token_provider.get_token(self._config.token_scope)
        base = self._config.endpoint
        if not base.endswith("/openai/v1"):
            base = f"{base}/openai/v1"
        raw = self._transport.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            payload={
                "model": self._config.deployment,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in request.messages
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "seed": request.seed,
            },
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            response = _OpenAIResponse.model_validate(raw)
        except ValidationError as exc:
            raise AzureProviderError("Azure OpenAI returned an invalid response") from exc
        content = response.choices[0].message.content.strip()
        if not content:
            raise AzureProviderError("Azure OpenAI returned an empty completion")
        estimated_cost = (
            response.usage.prompt_tokens * self._config.input_cost_per_million
            + response.usage.completion_tokens * self._config.output_cost_per_million
        ) / 1_000_000
        return ModelResponse(
            response_id=response.id,
            model=f"azure-openai/{response.model}",
            content=content,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                estimated_cost_usd=round(estimated_cost, 8),
            ),
        )


class _SearchDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    chunk_index: int = Field(validation_alias=AliasChoices("chunk_index", "index"), ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    search_score: float = Field(alias="@search.score", ge=0.0)


class _SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: list[_SearchDocument]


def _odata_literal(value: JsonScalar) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, int | float) and math.isfinite(value):
        return str(value)
    raise ValueError("Azure Search filters only support finite scalar values")


class AzureSearchRetriever:
    """Azure AI Search adapter normalized to the local retrieval contract."""

    def __init__(
        self,
        config: AzureSearchConfig,
        token_provider: AccessTokenProvider,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._transport = transport or UrllibJsonTransport()

    def search(self, request: SearchRequest) -> tuple[list[SearchResult], RetrievalTrace]:
        started_at = time.perf_counter()
        clauses = [
            f"corpus_id eq {_odata_literal(request.corpus_id)}",
            f"corpus_version eq {_odata_literal(request.corpus_version)}",
        ]
        for name, value in sorted(request.filters.items()):
            if not _FILTER_NAME.fullmatch(name):
                raise ValueError("Azure Search filter name is invalid")
            if isinstance(value, list | dict):
                raise ValueError("Azure Search filters only support scalar values")
            clauses.append(f"metadata/{name} eq {_odata_literal(value)}")

        token = self._token_provider.get_token(self._config.token_scope)
        raw = self._transport.post(
            f"{self._config.endpoint}/indexes/{self._config.index_name}/docs/search"
            f"?api-version={self._config.api_version}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            payload={
                "search": request.query,
                "queryType": "simple",
                "top": request.top_k,
                "filter": " and ".join(clauses),
                "select": ",".join(
                    (
                        "chunk_id",
                        "document_id",
                        "document_title",
                        "content",
                        "content_hash",
                        "chunk_index",
                        "metadata",
                    )
                ),
            },
            timeout_seconds=self._config.timeout_seconds,
        )
        try:
            response = _SearchResponse.model_validate(raw)
        except ValidationError as exc:
            raise AzureProviderError("Azure Search returned an invalid response") from exc

        results = [
            SearchResult(
                chunk=Chunk(
                    chunk_id=document.chunk_id,
                    document_id=document.document_id,
                    document_title=document.document_title,
                    content=document.content,
                    content_hash=document.content_hash,
                    index=document.chunk_index,
                    metadata=document.metadata,
                ),
                score=round(document.search_score / (1.0 + document.search_score), 6),
                rank=rank,
            )
            for rank, document in enumerate(response.value[: request.top_k], start=1)
        ]
        latency_ms = round((time.perf_counter() - started_at) * 1000, 3)
        return results, RetrievalTrace(
            corpus_id=request.corpus_id,
            corpus_version=request.corpus_version,
            query=request.query,
            result_ids=[result.chunk.chunk_id for result in results],
            ranks=[result.rank for result in results],
            scores=[result.score for result in results],
            latency_ms=latency_ms,
        )
