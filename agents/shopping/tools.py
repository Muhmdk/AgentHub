"""Typed read-only product retrieval tool."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents.shared.content_safety import contains_embedded_instruction
from agents.shared.retrieval import Retriever
from packages.contracts.retrieval import CorpusVersion, RetrievalTrace, SearchRequest
from packages.contracts.runtime import (
    Citation,
    JsonValue,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
    ToolObservation,
)


class ProductSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=4000)
    max_price: float | None = Field(default=None, gt=0)
    top_k: int = Field(default=5, ge=1, le=10)


class ProductMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["product"]
    sku: str
    name: str
    category: str
    price: float = Field(gt=0)
    source: str
    trusted: Literal[True]


class ProductCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    chunk_id: str
    sku: str
    name: str
    category: str
    price: float
    summary: str
    score: float


class ProductSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    products: list[ProductCandidate]
    retrieval: RetrievalTrace


class ProductTool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation: ...


class ProductSearchTool:
    """Search trusted products without any write or purchase capability."""

    definition: ToolDefinition = ToolDefinition(
        name="product.search",
        description="Search the versioned product corpus using optional price constraints.",
    )

    def __init__(self, retriever: Retriever, corpus: CorpusVersion) -> None:
        self._retriever = retriever
        self._corpus = corpus

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        try:
            parsed = ProductSearchInput.model_validate(arguments)
        except ValidationError:
            raise ToolExecutionError(
                self.definition.name,
                ToolErrorCode.INVALID_ARGUMENTS,
                "Invalid arguments for product.search",
            ) from None

        try:
            results, trace = self._retriever.search(
                SearchRequest(
                    query=parsed.query,
                    corpus_id=self._corpus.corpus_id,
                    corpus_version=self._corpus.version,
                    top_k=min(parsed.top_k * 2, 20),
                    filters={"kind": "product", "trusted": True},
                )
            )
        except Exception as exc:
            raise ToolExecutionError(
                self.definition.name,
                ToolErrorCode.DATA_ERROR,
                "Product search is unavailable",
            ) from exc

        products = []
        for result in results:
            if contains_embedded_instruction(result.chunk.content):
                continue
            try:
                metadata = ProductMetadata.model_validate(result.chunk.metadata)
            except ValidationError:
                continue
            if parsed.max_price is not None and metadata.price > parsed.max_price:
                continue
            products.append(
                ProductCandidate(
                    document_id=result.chunk.document_id,
                    chunk_id=result.chunk.chunk_id,
                    sku=metadata.sku,
                    name=metadata.name,
                    category=metadata.category,
                    price=metadata.price,
                    summary=result.chunk.content,
                    score=result.score,
                )
            )
            if len(products) == parsed.top_k:
                break

        output = ProductSearchOutput(products=products, retrieval=trace)
        return ToolObservation(
            data=output.model_dump(mode="json"),
            citations=[
                Citation(source_id=product.chunk_id, title=product.name) for product in products
            ],
        )
