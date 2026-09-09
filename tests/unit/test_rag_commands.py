"""Tests for local RAG commands and the versioned retrieval benchmark."""

import json
from pathlib import Path

import pytest

from agents.knowledge.__main__ import main as knowledge_main
from agents.shared.benchmark import BenchmarkSuite, load_benchmark, run_benchmark
from agents.shared.benchmark import main as benchmark_main
from agents.shared.ingest import main as ingest_main
from agents.shopping.__main__ import main as shopping_main


@pytest.mark.unit
def test_versioned_benchmark_hits_every_known_answer() -> None:
    suite = load_benchmark()
    report = run_benchmark(suite)

    assert suite.version == "retrieval-v1"
    assert report.case_count == 6
    assert report.hit_count == 6
    assert report.hit_rate == 1.0
    assert all(result.hit for result in report.results)


@pytest.mark.unit
def test_empty_benchmark_has_zero_hit_rate() -> None:
    report = run_benchmark(BenchmarkSuite(version="empty-v1", cases=[]))

    assert report.case_count == 0
    assert report.hit_count == 0
    assert report.hit_rate == 0.0


@pytest.mark.unit
def test_benchmark_loader_rejects_invalid_fixture(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="fixture is invalid"):
        load_benchmark(invalid)


@pytest.mark.unit
def test_ingestion_command_reports_idempotent_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ingest_main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["initial"]["document_count"] == 7
    assert output["initial"]["added_chunks"] == 7
    assert output["repeated"]["added_chunks"] == 0
    assert output["repeated"]["unchanged_chunks"] == 7


@pytest.mark.unit
def test_benchmark_command_prints_machine_readable_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert benchmark_main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["suite_version"] == "retrieval-v1"
    assert output["hit_rate"] == 1.0


@pytest.mark.unit
def test_knowledge_demo_command_returns_cited_answer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert knowledge_main(["Can I return an unopened product after 20 days?", "--seed", "7"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["answer"].startswith("Unopened products may be returned within 30 days")
    assert output["citations"]


@pytest.mark.unit
def test_shopping_demo_command_returns_retrieved_product(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert shopping_main(["Recommend a snow shovel under $50", "--seed", "8"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert "NorthPeak Aluminum Snow Shovel" in output["answer"]
    assert output["tool_calls"][0]["tool_name"] == "product.search"
