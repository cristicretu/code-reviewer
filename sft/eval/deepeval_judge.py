"""Score model predictions with deepeval using Qwen3.5-14B as judge.

Evaluates each prediction on 4 metrics:
  - G-Eval Correctness: does the comment identify a real issue?
  - G-Eval Specificity: does it reference exact code/locations?
  - G-Eval Actionability: is the suggestion concrete?
  - Answer Relevancy: is the output relevant to the diff?

Usage:
    deepeval set-ollama --model=qwen3.5:14b
    python -m sft.eval.deepeval_judge --predictions outputs/eval/predictions_base.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LOCAL_MODEL_NAME", "qwen3:8b")
os.environ.setdefault("LOCAL_MODEL_API_KEY", "ollama")
os.environ.setdefault("LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")

from deepeval.metrics import GEval, AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase, SingleTurnParams


CORRECTNESS_CRITERIA = (
    "Evaluate whether the code review comment correctly identifies a real "
    "issue in the code diff. A correct comment points to an actual bug, "
    "security vulnerability, logic error, or performance problem that exists "
    "in the diff. A comment that hallucinates a non-existent issue, makes "
    "factually wrong statements about the code, or describes a problem that "
    "isn't present should score low."
)

SPECIFICITY_CRITERIA = (
    "Evaluate whether the code review comment is specific about what to "
    "change. A specific comment references exact variable names, function "
    "names, line numbers, or code patterns from the diff. A vague comment "
    "that could apply to any code diff (e.g. 'this could be improved' or "
    "'consider better naming') should score low."
)

ACTIONABILITY_CRITERIA = (
    "Evaluate whether the code review comment provides a concrete, "
    "actionable suggestion for fixing the issue. An actionable comment "
    "explains exactly what to do (e.g. 'add a null check before accessing "
    "user.profile', 'wrap this in a try-except block'). A comment that "
    "only states something is wrong without explaining how to fix it "
    "should score low."
)


def load_predictions(path: Path) -> list[dict]:
    predictions = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                predictions.append(json.loads(line))
    return predictions


def build_test_case(ex: dict) -> LLMTestCase:
    return LLMTestCase(
        input=ex.get("diff", ""),
        actual_output=ex.get("prediction", ""),
        expected_output=ex.get("reference", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Deepeval LLM-as-judge")
    parser.add_argument(
        "--predictions", required=True, type=Path,
        help="Path to prediction JSONL (diff, prediction, reference per line)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output JSON path (default: same dir as predictions + _deepeval.json)",
    )
    parser.add_argument(
        "--max-examples", type=int, default=None,
        help="Limit number of examples (for quick tests)",
    )
    args = parser.parse_args()

    predictions = load_predictions(args.predictions)
    if args.max_examples:
        predictions = predictions[:args.max_examples]

    if not predictions:
        print("ERROR: No predictions loaded.")
        return 1

    print(f"Loaded {len(predictions)} predictions from {args.predictions}")

    metrics = {
        "correctness": GEval(
            name="Correctness",
            criteria=CORRECTNESS_CRITERIA,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            strict_mode=False,
            verbose_mode=True,
            async_mode=False,
        ),
        "specificity": GEval(
            name="Specificity",
            criteria=SPECIFICITY_CRITERIA,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
            strict_mode=False,
            verbose_mode=True,
            async_mode=False,
        ),
        "actionability": GEval(
            name="Actionability",
            criteria=ACTIONABILITY_CRITERIA,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
            strict_mode=False,
            verbose_mode=True,
            async_mode=False,
        ),
        "answer_relevancy": AnswerRelevancyMetric(
            verbose_mode=True,
            async_mode=False,
        ),
    }

    results: dict[str, list[float]] = {
        k: [] for k in metrics
    }
    individual_scores: list[dict] = []

    for i, ex in enumerate(predictions):
        tc = build_test_case(ex)
        print(f"\n--- Example {i+1}/{len(predictions)} ---")

        scores: dict[str, float] = {}
        for name, metric in metrics.items():
            try:
                metric.measure(tc)
                score = metric.score
                print(f"  {name}: {score:.3f}  ({metric.reason})")
            except Exception as e:
                print(f"  {name}: ERROR - {e}")
                score = -1.0
            scores[name] = score
            results[name].append(score)

        individual_scores.append({
            "index": i,
            "scores": scores,
        })

    print(f"\n{'='*50}")
    print("AGGREGATE RESULTS")
    print(f"{'='*50}")
    aggregates = {}
    for name, scores in results.items():
        valid = [s for s in scores if s >= 0]
        mean = sum(valid) / len(valid) if valid else 0.0
        aggregates[f"mean_{name}"] = round(mean, 4)
        aggregates[f"n_{name}"] = len(valid)
        print(f"  {name}: {mean:.4f} (n={len(valid)})")

    output = {
        "model_name": args.predictions.stem.replace("predictions_", ""),
        "n_total": len(predictions),
        "metrics": aggregates,
        "individual_scores": individual_scores,
    }

    output_path = args.output or (
        args.predictions.parent / f"{args.predictions.stem}_deepeval.json"
    )
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
