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
from sft.eval.defect_metrics import (
    compute_hallucination_rate,
    compute_defect_f1,
    compute_coherence,
    compute_toxicity_rate,
)


def load_predictions(path: str, max_examples: int | None = None) -> tuple[list[str], list[str], list[str]]:
    preds = []
    refs = []
    diffs = []
    with open(path) as f:
        for line in f:
            ex = json.loads(line.strip())
            preds.append(ex["prediction"])
            refs.append(ex["reference"])
            diffs.append(ex["diff"])
    if max_examples:
        preds = preds[:max_examples]
        refs = refs[:max_examples]
        diffs = diffs[:max_examples]
    return preds, refs, diffs


def main() -> int:
    eval_dir = Path("outputs/eval")
    variants = [
        ("base", eval_dir / "predictions_base.jsonl"),
        ("sft", eval_dir / "predictions_sft.jsonl"),
        ("rlhf", eval_dir / "predictions_rlhf.jsonl"),
    ]

    print(f"{'='*80}")
    print(f"{'Model':<8} {'CBS':>8} {'ChrF':>7} {'ROUGE':>7} {'DefF1':>7} {'Hall%':>7} {'Coher':>6} {'Toxic%':>7}")
    print(f"{'='*80}")

    results = {}
    for label, path in variants:
        if not path.exists():
            print(f"{label:<8} {'(no predictions)':>15}")
            continue
        preds, refs, diffs = load_predictions(str(path))
        print(f"{label:<8}  ({len(preds)} examples)...", end="", flush=True)

        scores = compute_metrics(preds, refs)
        defective = compute_defect_f1(preds, refs)
        halluc = compute_hallucination_rate(preds, diffs)
        coherence = compute_coherence(preds)
        toxicity = compute_toxicity_rate(preds)

        cbs = scores.get("code_bert_score", 0) or 0
        chrf = scores.get("chrf", 0)
        rl = scores.get("rouge_l", 0)
        f1 = defective["defect_f1"]
        hal = halluc
        coh = coherence["coherence"]
        tox = toxicity

        print(f"\r{label:<8}  {cbs:>8.4f} {chrf:>7.2f} {rl:>7.4f} {f1:>7.4f} {hal:>7.2%} {coh:>6.4f} {tox:>7.2%}")
        results[label] = {
            "code_bert_score": cbs, "chrf": chrf, "rouge_l": rl,
            "defect_f1": f1,
            "defect_precision": defective["defect_precision"],
            "defect_recall": defective["defect_recall"],
            "hallucination_rate": hal,
            "coherence": coh,
            "toxicity_rate": tox,
        }

    results_path = eval_dir / "lite_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
