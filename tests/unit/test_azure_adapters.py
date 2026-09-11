"""Offline unit tests for the Azure model and retrieval boundaries."""

import asyncio
import json
from collections.abc import Callable, Mapping
from email.message import Message
from types import TracebackType
from urllib.error import HTTPError, URLError

import pytest

from agents.shared.azure import (
    AZURE_OPENAI_SCOPE,
    AZURE_SEARCH_SCOPE,
    AccessTokenProvider,
    AzureOpenAIChatModel,
    AzureOpenAIConfig,
    AzureProviderError,
    AzureSearchConfig,
    AzureSearchRetriever,
    AzureTransientError,
    DefaultAzureTokenProvider,
    UrllibJsonTransport,
)
from packages.contracts.retrieval import SearchRequest
from packages.contracts.runtime import ChatMessage, JsonValue, ModelRequest


class RecordingTokenProvider(AccessTokenProvider):
    def __init__(self) -> None:
        self.scopes: list[str] = []
        self.closed = False

    def get_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return "offline-access-token"  # pragma: allowlist secret

    def close(self) -> None:
        self.closed = True


class RecordingTransport:
    def __init__(self, response: dict[str, JsonValue]) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, str], Mapping[str, JsonValue], float]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, JsonValue],
        timeout_seconds: float,
    ) -> dict[str, JsonValue]:
        self.calls.append((url, headers, payload, timeout_seconds))
        return self.response


class ByteResponse:
    def __init__(self, value: object) -> None:
        self.body = json.dumps(value).encode()

    def __enter__(self) -> ByteResponse:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        return self.body


@pytest.mark.unit
def test_azure_openai_normalizes_request_and_usage() -> None:
    token_provider = RecordingTokenProvider()
    transport = RecordingTransport(
        {
            "id": "completion-1",
            "model": "gpt-test-2026-08-01",
            "choices": [{"message": {"content": " grounded answer "}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    )
    model = AzureOpenAIChatModel(
        AzureOpenAIConfig(
            endpoint="https://agenthub.openai.azure.com/openai/v1/",
            deployment="gpt-test",
            timeout_seconds=7.5,
            input_cost_per_million=2.0,
            output_cost_per_million=4.0,
        ),
        token_provider,
        transport,
    )

    response = asyncio.run(
        model.generate(
            ModelRequest(
                messages=[ChatMessage(role="user", content="Hello")],
                max_tokens=32,
                seed=11,
            )
        )
    )

    assert model.name == "azure-openai/gpt-test"
    assert response.content == "grounded answer"
    assert response.model == "azure-openai/gpt-test-2026-08-01"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.usage.estimated_cost_usd == 0.00004
    assert token_provider.scopes == [AZURE_OPENAI_SCOPE]
    url, headers, payload, timeout = transport.calls[0]
    assert url == "https://agenthub.openai.azure.com/openai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer offline-access-token"
    assert payload["model"] == "gpt-test"
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]
    assert payload["max_tokens"] == 32
    assert payload["seed"] == 11
    assert timeout == 7.5


@pytest.mark.unit
def test_azure_openai_rejects_invalid_response_without_echoing_it() -> None:
    submitted_value = "private submitted prompt"
    model = AzureOpenAIChatModel(
        AzureOpenAIConfig(
            endpoint="https://agenthub.openai.azure.com",
            deployment="gpt-test",
        ),
        RecordingTokenProvider(),
        RecordingTransport({"unsafe": submitted_value}),
    )

    with pytest.raises(AzureProviderError) as raised:
        asyncio.run(
            model.generate(
                ModelRequest(messages=[ChatMessage(role="user", content=submitted_value)])
            )
        )

    assert submitted_value not in str(raised.value)


@pytest.mark.unit
def test_azure_openai_rejects_empty_completion() -> None:
    model = AzureOpenAIChatModel(
        AzureOpenAIConfig(
            endpoint="https://agenthub.openai.azure.com",
            deployment="gpt-test",
        ),
        RecordingTokenProvider(),
        RecordingTransport(
            {
                "id": "completion-1",
                "model": "gpt-test",
                "choices": [{"message": {"content": " "}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0},
            }
        ),
    )

    with pytest.raises(AzureProviderError, match="empty completion"):
        asyncio.run(
            model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
        )


@pytest.mark.unit
def test_azure_search_normalizes_results_and_escapes_filters() -> None:
    token_provider = RecordingTokenProvider()
    transport = RecordingTransport(
        {
            "value": [
                {
                    "chunk_id": "returns:0:abc",
                    "document_id": "returns",
                    "document_title": "Return policy",
                    "content": "Unopened goods may be returned.",
                    "content_hash": "abc",
                    "chunk_index": 0,
                    "metadata": {"region": "Canada"},
                    "@search.score": 3.0,
                }
            ]
        }
    )
    retriever = AzureSearchRetriever(
        AzureSearchConfig(
            endpoint="https://agenthub.search.windows.net/",
            index_name="agenthub-chunks-v1",
            timeout_seconds=6.0,
        ),
        token_provider,
        transport,
    )

    results, trace = retriever.search(
        SearchRequest(
            query="return policy",
            corpus_id="retail-policy",
            corpus_version="2026-09-08",
            top_k=2,
            filters={"region": "O'Brien"},
        )
    )

    assert token_provider.scopes == [AZURE_SEARCH_SCOPE]
    assert results[0].chunk.document_id == "returns"
    assert results[0].score == 0.75
    assert trace.result_ids == ["returns:0:abc"]
    url, headers, payload, timeout = transport.calls[0]
    assert url.endswith("/indexes/agenthub-chunks-v1/docs/search?api-version=2026-04-01")
    assert headers["Authorization"] == "Bearer offline-access-token"
    assert payload["top"] == 2
    assert payload["filter"] == (
        "corpus_id eq 'retail-policy' and corpus_version eq '2026-09-08' "
        "and metadata/region eq 'O''Brien'"
    )
    assert timeout == 6.0


@pytest.mark.unit
@pytest.mark.parametrize("filter_name", ["bad/name", "1bad", "bad-name"])
def test_azure_search_rejects_unsafe_filter_names(filter_name: str) -> None:
    retriever = AzureSearchRetriever(
        AzureSearchConfig(
            endpoint="https://agenthub.search.windows.net",
            index_name="agenthub-chunks-v1",
        ),
        RecordingTokenProvider(),
        RecordingTransport({"value": []}),
    )

    with pytest.raises(ValueError, match="filter name"):
        retriever.search(
            SearchRequest(
                query="return policy",
                corpus_id="retail-policy",
                corpus_version="2026-09-08",
                filters={filter_name: "value"},
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("filter_value", [["one"], {"nested": "value"}, float("inf")])
def test_azure_search_rejects_unsupported_filter_values(filter_value: JsonValue) -> None:
    retriever = AzureSearchRetriever(
        AzureSearchConfig(
            endpoint="https://agenthub.search.windows.net",
            index_name="agenthub-chunks-v1",
        ),
        RecordingTokenProvider(),
        RecordingTransport({"value": []}),
    )

    with pytest.raises(ValueError, match=r"finite scalar|scalar values"):
        retriever.search(
            SearchRequest(
                query="return policy",
                corpus_id="retail-policy",
                corpus_version="2026-09-08",
                filters={"category": filter_value},
            )
        )


@pytest.mark.unit
def test_azure_search_supports_null_boolean_and_numeric_filters() -> None:
    transport = RecordingTransport({"value": []})
    retriever = AzureSearchRetriever(
        AzureSearchConfig(
            endpoint="https://agenthub.search.windows.net",
            index_name="agenthub-chunks-v1",
        ),
        RecordingTokenProvider(),
        transport,
    )

    retriever.search(
        SearchRequest(
            query="return policy",
            corpus_id="retail-policy",
            corpus_version="v1",
            filters={"archived": None, "price": 49.5, "trusted": True},
        )
    )

    filter_expression = transport.calls[0][2]["filter"]
    assert filter_expression == (
        "corpus_id eq 'retail-policy' and corpus_version eq 'v1' "
        "and metadata/archived eq null and metadata/price eq 49.5 "
        "and metadata/trusted eq true"
    )


@pytest.mark.unit
def test_azure_search_rejects_invalid_response() -> None:
    retriever = AzureSearchRetriever(
        AzureSearchConfig(
            endpoint="https://agenthub.search.windows.net",
            index_name="agenthub-chunks-v1",
        ),
        RecordingTokenProvider(),
        RecordingTransport({"not_value": []}),
    )

    with pytest.raises(AzureProviderError, match="invalid response"):
        retriever.search(
            SearchRequest(
                query="return policy",
                corpus_id="retail-policy",
                corpus_version="v1",
            )
        )


@pytest.mark.unit
def test_azure_configs_require_https_endpoints() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        AzureOpenAIConfig(endpoint="http://insecure.example", deployment="gpt-test")
    with pytest.raises(ValueError, match="HTTPS"):
        AzureSearchConfig(endpoint="not-a-url", index_name="chunks")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: AzureOpenAIConfig(endpoint="https://agenthub.openai.azure.com", deployment=""),
            "deployment",
        ),
        (
            lambda: AzureOpenAIConfig(
                endpoint="https://agenthub.openai.azure.com",
                deployment="gpt-test",
                token_scope="",
            ),
            "token scope",
        ),
        (
            lambda: AzureOpenAIConfig(
                endpoint="https://agenthub.openai.azure.com",
                deployment="gpt-test",
                timeout_seconds=0,
            ),
            "timeout",
        ),
        (
            lambda: AzureOpenAIConfig(
                endpoint="https://agenthub.openai.azure.com",
                deployment="gpt-test",
                input_cost_per_million=-1,
            ),
            "costs",
        ),
        (
            lambda: AzureSearchConfig(
                endpoint="https://agenthub.search.windows.net", index_name="INVALID"
            ),
            "index name",
        ),
        (
            lambda: AzureSearchConfig(
                endpoint="https://agenthub.search.windows.net",
                index_name="agenthub-chunks-v1",
                api_version="latest",
            ),
            "API version",
        ),
        (
            lambda: AzureSearchConfig(
                endpoint="https://agenthub.search.windows.net",
                index_name="agenthub-chunks-v1",
                token_scope="",
            ),
            "token scope",
        ),
        (
            lambda: AzureSearchConfig(
                endpoint="https://agenthub.search.windows.net",
                index_name="agenthub-chunks-v1",
                timeout_seconds=0,
            ),
            "timeout",
        ),
    ],
)
def test_azure_configs_reject_invalid_bounds(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


@pytest.mark.unit
def test_default_token_provider_wraps_and_closes_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Token:
        token = "credential-token"  # pragma: allowlist secret

    class Credential:
        def __init__(self, *, managed_identity_client_id: str | None) -> None:
            self.client_id = managed_identity_client_id
            self.closed = False
            created.append(self)

        def get_token(self, scope: str) -> Token:
            assert scope == AZURE_OPENAI_SCOPE
            return Token()

        def close(self) -> None:
            self.closed = True

    created: list[Credential] = []
    monkeypatch.setattr("agents.shared.azure.DefaultAzureCredential", Credential)
    provider = DefaultAzureTokenProvider("client-id")

    assert provider.get_token(AZURE_OPENAI_SCOPE) == "credential-token"
    provider.close()
    assert created[0].closed


@pytest.mark.unit
def test_default_token_provider_sanitizes_credential_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCredential:
        def __init__(self, *, managed_identity_client_id: str | None) -> None:
            pass

        def get_token(self, scope: str) -> None:
            raise RuntimeError("sensitive credential detail")

        def close(self) -> None:
            pass

    monkeypatch.setattr("agents.shared.azure.DefaultAzureCredential", FailingCredential)
    provider = DefaultAzureTokenProvider()

    with pytest.raises(AzureProviderError) as raised:
        provider.get_token(AZURE_OPENAI_SCOPE)

    assert "sensitive credential detail" not in str(raised.value)


@pytest.mark.unit
def test_url_transport_posts_and_validates_json(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[object] = []

    def open_response(request: object, *, timeout: float) -> ByteResponse:
        requests.append(request)
        assert timeout == 2.0
        return ByteResponse({"ok": True})

    monkeypatch.setattr("agents.shared.azure.urlopen", open_response)
    response = UrllibJsonTransport().post(
        "https://provider.example/path",
        headers={"Authorization": "Bearer token"},
        payload={"message": "hello"},
        timeout_seconds=2.0,
    )

    assert response == {"ok": True}
    assert len(requests) == 1


@pytest.mark.unit
def test_url_transport_sanitizes_failures_and_rejects_non_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_request(request: object, *, timeout: float) -> ByteResponse:
        raise URLError("sensitive transport detail")

    monkeypatch.setattr("agents.shared.azure.urlopen", fail_request)
    with pytest.raises(AzureProviderError) as raised:
        UrllibJsonTransport().post(
            "https://provider.example/path",
            headers={},
            payload={},
            timeout_seconds=2.0,
        )
    assert "sensitive transport detail" not in str(raised.value)

    monkeypatch.setattr(
        "agents.shared.azure.urlopen",
        lambda request, *, timeout: ByteResponse(["not", "an", "object"]),
    )
    with pytest.raises(AzureProviderError, match="invalid response"):
        UrllibJsonTransport().post(
            "https://provider.example/path",
            headers={},
            payload={},
            timeout_seconds=2.0,
        )


@pytest.mark.unit
@pytest.mark.parametrize("status", [429, 500, 503])
def test_url_transport_classifies_retryable_http_failures(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    def fail_request(request: object, *, timeout: float) -> ByteResponse:
        raise HTTPError("https://provider.example", status, "sensitive", Message(), None)

    monkeypatch.setattr("agents.shared.azure.urlopen", fail_request)

    with pytest.raises(AzureTransientError, match="provider request failed"):
        UrllibJsonTransport().post(
            "https://provider.example/path",
            headers={},
            payload={},
            timeout_seconds=2.0,
        )


@pytest.mark.unit
def test_url_transport_does_not_retry_client_http_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_request(request: object, *, timeout: float) -> ByteResponse:
        raise HTTPError("https://provider.example", 400, "sensitive", Message(), None)

    monkeypatch.setattr("agents.shared.azure.urlopen", fail_request)

    with pytest.raises(AzureProviderError) as raised:
        UrllibJsonTransport().post(
            "https://provider.example/path",
            headers={},
            payload={},
            timeout_seconds=2.0,
        )

    assert not isinstance(raised.value, AzureTransientError)
