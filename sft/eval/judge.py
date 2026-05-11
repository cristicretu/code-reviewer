"""LLM-as-judge evaluation for code review quality.

Uses either Claude (Anthropic) or Gemini (Google) to score each review on:
    - Accuracy (1-5): Does the comment identify a real issue?
    - Helpfulness (1-5): Is the suggestion actionable?
    - Specificity (1-5): Does it reference exact lines and context?

Requires ANTHROPIC_API_KEY or GEMINI_API_KEY environment variable.

Usage:
    python -m sft.eval.judge --backend gemini --predictions outputs/predictions.jsonl --n 50
    python -m sft.eval.judge --backend anthropic --predictions outputs/predictions.jsonl --n 50
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

from dotenv import load_dotenv

_load_paths = [Path(__file__).resolve().parent.parent.parent / ".env.local", ".env.local"]
for p in _load_paths:
    if p.exists():
        load_dotenv(p, override=False)
        break

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


def _parse_json(text: str) -> dict:
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def judge_single_anthropic(
    diff: str, comment: str, reference: str, client
) -> dict:
    """Score a single review comment using Claude."""
    prompt = JUDGE_PROMPT.format(diff=diff, comment=comment, reference=reference)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(response.content[0].text.strip())


def judge_single_gemini(
    diff: str, comment: str, reference: str, client, model_name: str
) -> dict:
    """Score a single review comment using Gemini with retry and backoff."""
    import time as _time

    prompt = JUDGE_PROMPT.format(diff=diff, comment=comment, reference=reference)
    last_error = None

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return _parse_json(response.text.strip())
        except Exception as e:
            last_error = e
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                wait = min((2 ** attempt) * 5, 30)
                _time.sleep(wait)
            else:
                raise

    raise last_error


def run_judge(
    examples: list[dict],
    n: int = 50,
    seed: int = 42,
    backend: str = "anthropic",
) -> dict:
    """Run LLM-as-judge on a subset of examples.

    Each example should have keys: diff, prediction, reference

    Returns:
        Dict with mean scores per dimension and individual results.
    """
    if backend == "gemini":
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        model = "gemini-2.5-flash"
        judge_fn = lambda diff, comment, ref: judge_single_gemini(diff, comment, ref, client, model)
    else:
        import anthropic

        client = anthropic.Anthropic()
        judge_fn = lambda diff, comment, ref: judge_single_anthropic(diff, comment, ref, client)

    random.seed(seed)
    if len(examples) > n:
        examples = random.sample(examples, n)

    results = []
    for i, ex in enumerate(examples):
        if backend == "gemini" and i > 0:
            time.sleep(13)  # respect 5 RPM free-tier limit
        print(f"  Judging {i+1}/{len(examples)}...", end="\r")
        try:
            scores = judge_fn(
                diff=ex["diff"],
                comment=ex["prediction"],
                ref=ex["reference"],
            )
            scores["index"] = i
            results.append(scores)
        except Exception as e:
            print(f"\n  WARNING: Failed on example {i}: {e}")
            continue

    print()

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
    parser.add_argument("--backend", choices=["anthropic", "gemini"], default="anthropic")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("outputs/judge_results.json"))
    args = parser.parse_args()

    if args.backend == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            print("ERROR: Set GEMINI_API_KEY environment variable")
            raise SystemExit(1)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ERROR: Set ANTHROPIC_API_KEY environment variable")
            raise SystemExit(1)

    examples = []
    with open(args.predictions) as f:
        for line in f:
            examples.append(json.loads(line))

    print(f"Loaded {len(examples)} predictions, judging {args.n} with {args.backend}...")
    results = run_judge(examples, n=args.n, seed=args.seed, backend=args.backend)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults:")
    for dim in ["accuracy", "helpfulness", "specificity"]:
        print(f"  {dim}: {results[f'mean_{dim}']:.2f} / 5.0")
    print(f"  ({results['n_judged']} examples judged)")
    print(f"Saved to {args.output}")
