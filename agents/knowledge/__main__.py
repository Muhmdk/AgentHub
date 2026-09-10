"""Command-line demonstration for the grounded Knowledge Agent."""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from agents.knowledge.agent import KnowledgeAgent
from agents.shared.providers import create_provider_bundle
from apps.api.config import load_settings
from packages.contracts.runtime import AgentExecutionError, AgentRequest

DEFAULT_QUESTION = "Can I return an unopened product after 20 days?"


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic Knowledge Agent demo")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--seed", type=int, default=0)
    parsed = parser.parse_args(arguments)
    settings = load_settings()
    providers = create_provider_bundle(settings)
    agent = KnowledgeAgent(
        retriever=providers.retriever,
        corpus=providers.corpus,
        model=providers.model,
        top_k=settings.rag_top_k,
        minimum_score=settings.rag_minimum_score,
        timeout_seconds=settings.retrieval_timeout_seconds,
    )
    try:
        response = asyncio.run(agent.invoke(AgentRequest(query=parsed.question, seed=parsed.seed)))
    except AgentExecutionError as exc:
        print(f"{exc.code.value}: {exc.message}", file=sys.stderr)
        return 2
    finally:
        providers.close()
    print(response.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
