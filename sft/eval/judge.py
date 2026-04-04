"""LLM-as-judge evaluation for code review quality.

Uses Claude (via Anthropic API) to score each review on:
    - Accuracy (1-5): Does the comment identify a real issue?
    - Helpfulness (1-5): Is the suggestion actionable?
    - Specificity (1-5): Does it reference exact lines and context?

Requires ANTHROPIC_API_KEY environment variable.

Usage:
    python -m sft.eval.judge --predictions outputs/predictions.jsonl --n 50
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

JUDGE_PROMPT = """\
You are evaluating the quality of an automated code review comment.

## Code Diff
```
{diff}
```

## Review Comment
{comment}

## Ground Truth Comment (for reference)
{reference}

## Task
Score the review comment on three dimensions. For each, give a score from 1-5:

1. **Accuracy** (1-5): Does the comment identify a real issue in the diff? Score 1 if it hallucinates a non-existent problem, 5 if it precisely identifies a genuine issue.
2. **Helpfulness** (1-5): Is the suggestion actionable? Score 1 if vague/generic, 5 if it gives a clear fix.
3. **Specificity** (1-5): Does it reference exact code/lines? Score 1 if it could apply to any diff, 5 if it pinpoints the exact location and context.

Respond with ONLY a JSON object:
{{"accuracy": <int>, "helpfulness": <int>, "specificity": <int>, "reasoning": "<brief explanation>"}}"""


def judge_single(
    diff: str, comment: str, reference: str, client
) -> dict:
    """Score a single review comment using Claude."""
    prompt = JUDGE_PROMPT.format(diff=diff, comment=comment, reference=reference)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Parse JSON from response
    # Handle case where model wraps in ```json ... ```
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    return json.loads(text)


def run_judge(
    examples: list[dict],
    n: int = 50,
    seed: int = 42,
) -> dict:
    """Run LLM-as-judge on a subset of examples.

    Each example should have keys: diff, prediction, reference

    Returns:
        Dict with mean scores per dimension and individual results.
    """
    import anthropic

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    # Sample subset
    random.seed(seed)
    if len(examples) > n:
        examples = random.sample(examples, n)

    results = []
    for i, ex in enumerate(examples):
        print(f"  Judging {i+1}/{len(examples)}...", end="\r")
        try:
            scores = judge_single(
                diff=ex["diff"],
                comment=ex["prediction"],
                reference=ex["reference"],
                client=client,
            )
            scores["index"] = i
            results.append(scores)
        except Exception as e:
            print(f"\n  WARNING: Failed on example {i}: {e}")
            continue

    print()

    # Compute means
    dims = ["accuracy", "helpfulness", "specificity"]
    means = {}
    for dim in dims:
        values = [r[dim] for r in results if dim in r]
        means[f"mean_{dim}"] = sum(values) / len(values) if values else 0.0

    means["n_judged"] = len(results)
    means["individual_results"] = results

    return means


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-as-judge evaluation")
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("outputs/judge_results.json"))
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        raise SystemExit(1)

    # Load predictions
    examples = []
    with open(args.predictions) as f:
        for line in f:
            examples.append(json.loads(line))

    print(f"Loaded {len(examples)} predictions, judging {args.n}...")
    results = run_judge(examples, n=args.n, seed=args.seed)

    # Save
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults:")
    for dim in ["accuracy", "helpfulness", "specificity"]:
        print(f"  {dim}: {results[f'mean_{dim}']:.2f} / 5.0")
    print(f"  ({results['n_judged']} examples judged)")
    print(f"Saved to {args.output}")
