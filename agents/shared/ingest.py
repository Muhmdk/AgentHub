"""Validate and ingest the versioned local corpus from the command line."""

import json

from agents.shared.corpus import load_retail_corpus
from agents.shared.retrieval import InMemoryRetriever


def main() -> int:
    corpus, documents = load_retail_corpus()
    retriever = InMemoryRetriever()
    first = retriever.ingest(corpus, documents)
    repeated = retriever.ingest(corpus, documents)
    print(
        json.dumps(
            {
                "initial": first.model_dump(mode="json"),
                "repeated": repeated.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
