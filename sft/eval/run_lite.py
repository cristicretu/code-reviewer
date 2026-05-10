"""Lightweight eval runner — computes CodeBERTScore, ChrF, ROUGE-L on predictions.

Works on M1 Pro in seconds. No LLM judge needed.

Usage:
    python -m sft.eval.run_lite
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sft.eval.metrics import compute_metrics


def load_predictions(path: str, max_examples: int | None = None) -> tuple[list[str], list[str]]:
    preds = []
    refs = []
    with open(path) as f:
        for line in f:
            ex = json.loads(line.strip())
            preds.append(ex["prediction"])
            refs.append(ex["reference"])
    if max_examples:
        preds = preds[:max_examples]
        refs = refs[:max_examples]
    return preds, refs


def main() -> int:
    eval_dir = Path("outputs/eval")
    variants = [
        ("base", eval_dir / "predictions_base.jsonl"),
        ("sft", eval_dir / "predictions_sft.jsonl"),
        ("rlhf", eval_dir / "predictions_rlhf.jsonl"),
    ]

    print(f"{'='*60}")
    print(f"{'Model':<8} {'CodeBERTScore':>15} {'ChrF':>8} {'ROUGE-L':>8}")
    print(f"{'='*60}")

    results = {}
    for label, path in variants:
        if not path.exists():
            print(f"{label:<8} {'(no predictions)':>15}")
            continue
        preds, refs = load_predictions(str(path))
        print(f"{label:<8}  ({len(preds)} examples)...", end="", flush=True)
        scores = compute_metrics(preds, refs)
        cbs = scores.get("code_bert_score", 0) or 0
        chrf = scores.get("chrf", 0)
        rl = scores.get("rouge_l", 0)
        print(f"\r{label:<8}  {cbs:>15.4f} {chrf:>8.2f} {rl:>8.4f}")
        results[label] = {"code_bert_score": cbs, "chrf": chrf, "rouge_l": rl}

    results_path = eval_dir / "lite_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
