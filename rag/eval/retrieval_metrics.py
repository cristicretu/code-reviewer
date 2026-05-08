"""Evaluate RAG retrieval quality using deepeval contextual metrics.

Loads test examples, derives search queries from diffs, retrieves chunks
from the RAG service, and scores retrieval quality.

Usage:
    # Start RAG service first:
    DYNACONF_APP_PROFILE=dev python -m rag.main &

    # Then run eval:
    python -m rag.eval.retrieval_metrics --n 20
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("LOCAL_MODEL_NAME", "qwen3:14b")
os.environ.setdefault("LOCAL_MODEL_API_KEY", "ollama")
os.environ.setdefault("LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")

import requests
from deepeval.metrics import (
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
)
from deepeval.test_case import LLMTestCase


def load_test_data(n: int, seed: int = 42) -> list[dict]:
    test_path = Path("data/processed/test.jsonl")
    if not test_path.exists():
        print(f"Test data not found at {test_path}")
        print("Run the data pipeline first: python -m sft.data.preprocess && python -m sft.data.split")
        return []

    examples = []
    with open(test_path) as f:
        for line in f:
            examples.append(json.loads(line))

    random.seed(seed)
    random.shuffle(examples)
    return examples[:n]


def derive_query(diff: str) -> str:
    lines = diff.splitlines()
    keywords = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("+") and not stripped.startswith("+++"):
            for word in stripped[1:].split():
                clean = word.strip("(),;{}[]\"'")
                if len(clean) > 3 and not clean.startswith("_"):
                    keywords.append(clean)
        if stripped.startswith("-") and not stripped.startswith("---"):
            for word in stripped[1:].split():
                clean = word.strip("(),;{}[]\"'")
                if len(clean) > 3 and not clean.startswith("_"):
                    keywords.append(clean)

    seen = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)

    keyword_str = " ".join(unique[:15])
    return f"Code related to: {keyword_str}" if keyword_str else "General code review context"


def retrieve_from_rag(query: str, k: int = 5) -> list[str]:
    rag_url = os.environ.get("RAG_URL", "http://localhost:8000").rstrip("/")
    repo_id = os.environ.get("REPO_ID", "default_repo")
    try:
        resp = requests.post(
            f"{rag_url}/api/v1/retrieve/{repo_id}",
            json={"query": query, "max_results": k},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        chunks = []
        for item in data if isinstance(data, list) else data.get("results", []):
            content = item.get("content") or item.get("text", "")
            chunks.append(content)
        return chunks
    except Exception as e:
        print(f"  WARNING: RAG retrieval failed: {e}")
        return []


def extract_reference_diff(diff: str) -> str:
    lines = []
    for line in diff.splitlines():
        stripped = line.strip()
        if stripped.startswith("+") or stripped.startswith("-"):
            lines.append(stripped)
    return "\n".join(lines[:50])


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG retrieval quality evaluation")
    parser.add_argument("--n", type=int, default=20, help="Number of test examples")
    parser.add_argument("--k", type=int, default=5, help="Number of chunks to retrieve per query")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rag-url", default=None, help="RAG service URL")
    parser.add_argument("--output", type=Path, default=Path("outputs/eval/rag_metrics.json"))
    args = parser.parse_args()

    if args.rag_url:
        os.environ["RAG_URL"] = args.rag_url
        del args  # noqa

    rag_url = os.environ.get("RAG_URL", "http://localhost:8000").rstrip("/")

    # Check RAG is alive
    try:
        r = requests.get(f"{rag_url}/health", timeout=5)
        r.raise_for_status()
        print(f"RAG service OK at {rag_url}")
    except Exception as e:
        print(f"ERROR: RAG service not reachable at {rag_url}: {e}")
        print("Start it with: DYNACONF_APP_PROFILE=dev python -m rag.main &")
        return 1

    examples = load_test_data(args.n, args.seed)
    if not examples:
        return 1
    print(f"Loaded {len(examples)} test examples")

    precision = ContextualPrecisionMetric(verbose_mode=True)
    recall = ContextualRecallMetric(verbose_mode=True)
    relevancy = ContextualRelevancyMetric(verbose_mode=True)

    all_scores: list[dict] = []
    succeeded = 0

    for i, ex in enumerate(examples):
        messages = ex.get("messages", [])
        user_msg = ""
        assistant_msg = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
            elif msg.get("role") == "assistant":
                assistant_msg = msg.get("content", "")

        diff = user_msg
        reference = assistant_msg
        query = derive_query(diff)
        ref_diff = extract_reference_diff(diff)

        print(f"\n--- Example {i+1}/{len(examples)} ---")

        chunks = retrieve_from_rag(query, k=args.k)
        if not chunks:
            print(f"  SKIP: no chunks retrieved")
            continue

        tc = LLMTestCase(
            input=query,
            actual_output=reference,
            expected_output=reference,
            retrieval_context=chunks,
        )

        scores = {}
        for name, metric in [("precision", precision), ("recall", recall), ("relevancy", relevancy)]:
            try:
                metric.measure(tc)
                s = metric.score
                print(f"  {name}: {s:.3f}  ({metric.reason})")
            except Exception as e:
                print(f"  {name}: ERROR - {e}")
                s = -1.0
            scores[name] = s

        all_scores.append({
            "index": i,
            "query": query[:100],
            "n_chunks": len(chunks),
            "scores": scores,
        })
        succeeded += 1

    print(f"\n{'='*50}")
    print("RAG RETRIEVAL RESULTS (n={})".format(succeeded))
    print(f"{'='*50}")
    aggregates = {}
    for dim in ["precision", "recall", "relevancy"]:
        vals = [s["scores"][dim] for s in all_scores if s["scores"].get(dim, -1) >= 0]
        mean = sum(vals) / len(vals) if vals else 0.0
        aggregates[f"mean_{dim}"] = round(mean, 4)
        aggregates[f"n_{dim}"] = len(vals)
        print(f"  {dim}: {mean:.4f} (n={len(vals)})")

    output = {
        "n_examples": succeeded,
        "metrics": aggregates,
        "individual_results": all_scores,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
