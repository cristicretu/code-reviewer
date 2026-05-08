"""Run the agentic + RAG code reviewer on test examples and collect outputs.

Each example is a diff from the held-out test set. The agent runs with its
full tool loop (no GitHub API needed). Output is saved as a prediction JSONL
that deepeval_judge.py can score for direct comparison with standalone models.

Usage:
    # Terminal 1: RAG service
    DYNACONF_APP_PROFILE=dev python -m rag.main &

    # Terminal 2: Model endpoint (Ollama / llama-server / vLLM)
    # Serve cretu-luca/code-reviewer-grpo on e.g. http://localhost:8080/v1

    # Terminal 3: Run eval
    API_BASE=http://localhost:8080/v1 MODEL_ID=cretu-luca/code-reviewer-grpo \
        python -m agentic.eval.run_agent_eval --n 5
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import requests
from loguru import logger

# Configure smolagents log level to reduce noise
import logging
logging.getLogger("smolagents").setLevel(logging.WARNING)


SYSTEM_PROMPT = """\
You are an expert code reviewer. Given a code diff, provide a concise, \
actionable review comment. Focus on:
- Bugs and logic errors
- Security vulnerabilities
- Performance issues
- Code style and best practices

Be specific: reference the exact code that needs changing and explain why. \
If the code looks correct, say so briefly."""


def load_test_data(n: int, seed: int = 42) -> list[dict]:
    test_path = Path("data/processed/test.jsonl")
    if not test_path.exists():
        print(f"ERROR: Test data not found at {test_path}")
        print("Run: python -m sft.data.preprocess && python -m sft.data.split")
        sys.exit(1)

    examples = []
    with open(test_path) as f:
        for line in f:
            examples.append(json.loads(line))

    random.seed(seed)
    random.shuffle(examples)
    return examples[:n]


def extract_messages(ex: dict) -> tuple[str, str]:
    messages = ex.get("messages", [])
    user_msg = ""
    assistant_msg = ""
    for msg in messages:
        if msg.get("role") == "user":
            user_msg = msg.get("content", "")
        elif msg.get("role") == "assistant":
            assistant_msg = msg.get("content", "")
    return user_msg, assistant_msg


def check_endpoint() -> bool:
    api_base = os.environ.get("API_BASE", "")
    model_id = os.environ.get("MODEL_ID", "")
    if not api_base:
        print("ERROR: API_BASE env var not set")
        return False
    if not model_id:
        print("ERROR: MODEL_ID env var not set")
        return False
    try:
        base = api_base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        r = requests.get(f"{base}/v1/models", timeout=10)
        r.raise_for_status()
        models = r.json()
        print(f"Model endpoint OK at {api_base}")
        if isinstance(models, dict):
            model_list = models.get("data", [])
            available = [m.get("id", "") for m in model_list] if model_list else []
            if available:
                print(f"  Available models: {', '.join(available[:5])}")
        return True
    except Exception as e:
        print(f"WARNING: Could not reach model endpoint at {api_base}: {e}")
        print("  Agent eval will fail if the endpoint is down.")
        return False


def build_synthetic_pr(diff: str, index: int) -> dict:
    lines = diff.splitlines()
    changed = len([l for l in lines if l.startswith("diff --git")])
    additions = len([l for l in lines if l.startswith("+") and not l.startswith("+++")])
    deletions = len([l for l in lines if l.startswith("-") and not l.startswith("---")])
    return {
        "number": 999900 + index,
        "title": f"Automated eval #{index}",
        "user": {"login": "eval-bot"},
        "base": {
            "ref": "main",
            "repo": {"full_name": "eval/repo"},
        },
        "head": {"ref": f"eval-branch-{index}"},
        "changed_files": max(changed, 1),
        "additions": additions,
        "deletions": deletions,
        "body": f"Automated evaluation example #{index}.",
    }


def build_task_prompt(ex: dict, index: int) -> str:
    user_msg, assistant_msg = extract_messages(ex)
    diff = user_msg
    pr = build_synthetic_pr(diff, index)

    instructions = f"""\
{SYSTEM_PROMPT}

Repository: {pr['base']['repo']['full_name']}
PR #{pr['number']}: {pr['title']}
Author: @{pr['user']['login']}
Base: {pr['base']['ref']} <- Head: {pr['head']['ref']}
Changed files: {pr['changed_files']}  +{pr['additions']} / -{pr['deletions']}

Description:
{pr['body']}

Diff:
```diff
{diff[:60000]}
```

Review this code change. Use the available tools to investigate.
Call post_comment() for each issue you find, then call request_changes,
approve, or comment_only as your verdict. Finally call final_answer("done")."""

    return instructions


def extract_agent_review() -> str:
    from agentic.review_state import REVIEW_STATE

    comments = REVIEW_STATE.comments
    verdict = REVIEW_STATE.verdict or "COMMENT"

    if not comments:
        return f"[Verdict: {verdict}] No issues found."

    parts = [f"[Verdict: {verdict}]"]
    for c in comments:
        path = c.get("path", "?")
        line = c.get("line", "?")
        body = c.get("body", "")
        parts.append(f"**{path}:{line}** {body}")

    return "\n\n".join(parts)


def reset_review_state() -> None:
    from agentic.review_state import REVIEW_STATE
    REVIEW_STATE.configure(
        client=None,
        repo="eval",
        pr_number=0,
        commit_id="eval",
    )


def run_agent_single(ex: dict, index: int, max_steps: int = 20) -> dict | None:
    from agentic.agent import build_agent

    reset_review_state()
    task = build_task_prompt(ex, index)

    agent = build_agent()
    try:
        agent.run(task, max_steps=max_steps)
    except Exception as e:
        logger.error(f"Agent run failed on example {index}: {e}")

    from agentic.review_state import REVIEW_STATE
    prediction = extract_agent_review()
    _, reference = extract_messages(ex)
    user_msg, _ = extract_messages(ex)

    n_comments = len(REVIEW_STATE.comments)
    verdict = REVIEW_STATE.verdict
    logger.info(f"Example {index}: {n_comments} comments, verdict={verdict}")

    return {
        "diff": user_msg,
        "prediction": prediction,
        "reference": reference,
        "n_comments": n_comments,
        "verdict": verdict,
        "index": index,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentic + RAG evaluation")
    parser.add_argument("--n", type=int, default=5, help="Number of test examples")
    parser.add_argument("--max-steps", type=int, default=20, help="Max agent steps per example")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("outputs/eval/predictions_agent.jsonl"))
    parser.add_argument("--trace", type=Path, default=Path("outputs/eval/agent_trace.json"))
    parser.add_argument("--skip-endpoint-check", action="store_true", help="Skip model endpoint check")
    args = parser.parse_args()

    if not args.skip_endpoint_check:
        if not check_endpoint():
            print("Use --skip-endpoint-check to bypass this check.")
            return 1

    examples = load_test_data(args.n, args.seed)
    print(f"Loaded {len(examples)} test examples")

    results = []
    trace = []

    for i, ex in enumerate(examples):
        print(f"\n{'='*60}")
        print(f"Example {i+1}/{len(examples)}")
        print(f"{'='*60}")

        start = time.time()
        result = run_agent_single(ex, i, args.max_steps)
        elapsed = time.time() - start

        if result:
            results.append(result)
            trace.append({
                "index": i,
                "elapsed_seconds": round(elapsed, 1),
                "n_comments": result.get("n_comments", 0),
                "verdict": result.get("verdict"),
            })
            print(f"  Time: {elapsed:.1f}s")
            print(f"  Comments: {result['n_comments']}")
            print(f"  Verdict: {result['verdict']}")

    # Save predictions in same format as run_eval.py
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        for r in results:
            f.write(json.dumps({
                "diff": r["diff"],
                "prediction": r["prediction"],
                "reference": r["reference"],
            }) + "\n")
    print(f"\nPredictions saved to {args.output}")

    # Save trace
    with open(args.trace, "w") as f:
        json.dump({
            "n_examples": len(results),
            "config": {"max_steps": args.max_steps, "seed": args.seed},
            "runs": trace,
        }, f, indent=2)
    print(f"Trace saved to {args.trace}")

    agentic_results_path = args.output.parent / "agentic_results.json"
    with open(agentic_results_path, "w") as f:
        json.dump({
            "n_examples": len(results),
            "total_comments": sum(r["n_comments"] for r in results),
            "avg_comments": sum(r["n_comments"] for r in results) / len(results) if results else 0,
            "verdicts": {
                v: sum(1 for r in results if r.get("verdict") == v)
                for v in set(r.get("verdict") for r in results)
            },
            "runs": trace,
        }, f, indent=2)
    print(f"Agentic results saved to {agentic_results_path}")

    print(f"\nDone. {len(results)}/{len(examples)} examples completed.")
    print(f"Next: python -m sft.eval.deepeval_judge --predictions {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
