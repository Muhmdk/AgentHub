"""Versioned known-answer benchmark for the deterministic local retriever."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from agents.shared.corpus import create_retail_retriever
from packages.contracts.retrieval import (
    RetrievalBenchmarkCase,
    RetrievalBenchmarkReport,
    RetrievalBenchmarkResult,
    SearchRequest,
)


class BenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    cases: list[RetrievalBenchmarkCase]


def load_benchmark(path: Path | None = None) -> BenchmarkSuite:
    benchmark_path = path or Path(__file__).parents[2] / "data" / "evals" / "retrieval-v1.json"
    try:
        return BenchmarkSuite.model_validate_json(benchmark_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise ValueError("Retrieval benchmark fixture is invalid") from exc


def run_benchmark(suite: BenchmarkSuite | None = None) -> RetrievalBenchmarkReport:
    selected_suite = suite or load_benchmark()
    retriever, corpus, _ = create_retail_retriever()
    case_results = []
    for case in selected_suite.cases:
        results, _ = retriever.search(
            SearchRequest(
                query=case.query,
                corpus_id=corpus.corpus_id,
                corpus_version=corpus.version,
                top_k=3,
                filters=case.filters,
            )
        )
        document_ids = [result.chunk.document_id for result in results]
        case_results.append(
            RetrievalBenchmarkResult(
                case_id=case.case_id,
                expected_document_id=case.expected_document_id,
                result_document_ids=document_ids,
                hit=case.expected_document_id in document_ids,
            )
        )
    hits = sum(result.hit for result in case_results)
    return RetrievalBenchmarkReport(
        suite_version=selected_suite.version,
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        case_count=len(case_results),
        hit_count=hits,
        hit_rate=hits / len(case_results) if case_results else 0.0,
        results=case_results,
    )


def main() -> int:
    print(run_benchmark().model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
