"""Command-line demonstration for the grounded Shopping Agent."""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from agents.shared.corpus import create_retail_retriever
from agents.shared.providers import create_chat_model
from agents.shopping.agent import ShoppingAgent
from agents.shopping.tools import ProductSearchTool
from apps.api.config import load_settings
from packages.contracts.runtime import AgentExecutionError, AgentRequest

DEFAULT_QUESTION = "Recommend a snow shovel under $50"


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic Shopping Agent demo")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--seed", type=int, default=0)
    parsed = parser.parse_args(arguments)
    settings = load_settings()
    retriever, corpus, _ = create_retail_retriever()
    agent = ShoppingAgent(
        product_tool=ProductSearchTool(retriever, corpus),
        model=create_chat_model(settings.model_provider),
        timeout_seconds=settings.agent_timeout_seconds,
    )
    try:
        response = asyncio.run(agent.invoke(AgentRequest(query=parsed.question, seed=parsed.seed)))
    except AgentExecutionError as exc:
        print(f"{exc.code.value}: {exc.message}", file=sys.stderr)
        return 2
    print(response.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
