"""Command-line demonstration for the deterministic Inventory Agent."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date

from agents.inventory.agent import InventoryAgent
from agents.inventory.data import RetailData
from agents.shared.providers import create_chat_model
from apps.api.config import load_settings
from packages.contracts.runtime import AgentExecutionError, AgentRequest

DEFAULT_QUESTION = "Which Toronto stores may run low on snow shovels this weekend?"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deterministic Inventory Agent demo")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 9, 8))
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Run one inventory question and write a machine-readable response."""
    parsed = build_parser().parse_args(arguments)
    settings = load_settings()
    agent = InventoryAgent(
        data=RetailData.load(),
        model=create_chat_model(settings.model_provider),
        max_steps=settings.agent_max_steps,
        tool_timeout_seconds=settings.tool_timeout_seconds,
        execution_timeout_seconds=settings.agent_timeout_seconds,
    )
    try:
        response = asyncio.run(
            agent.invoke(AgentRequest(query=parsed.question, seed=parsed.seed, as_of=parsed.as_of))
        )
    except AgentExecutionError as exc:
        print(f"{exc.code.value}: {exc.message}", file=sys.stderr)
        return 2

    print(response.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
