"""Score predictions against the cretu_testing dataset.

Two metric families, kept deliberately separate (per the design discussion with Luca):

Set 1 — Bug detection (the discriminating signal).
  Per planted bug: LLM judge decides found / not-found.
  Per clean example: LLM judge decides false_positive / not.
  Aggregated to precision / recall / accuracy / F1, plus a confusion matrix.

Set 2 — Review-quality metrics (cheap, regex/heuristic).
  Coherence, toxicity rate, hallucination rate.
  Reuses sft.eval.defect_metrics so numbers are comparable to existing reports.

Usage:
    # Score one model
    python -m cretu_testing.score --models sft

    # Compare several
    python -m cretu_testing.score --models base,sft,rlhf --backend gemini

    # Skip the LLM judge (Set 2 only — useful for an offline sanity check)
    python -m cretu_testing.score --models sft --skip-judge

Predictions are read from cretu_testing/predictions/predictions_<label>.jsonl
(produced by run_cretu_eval.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cretu_testing.bug_detection import (
    aggregate,
    aggregate_by_difficulty,
    judge_predictions,
)

DATA_PATH = Path(__file__).parent / "cretu.txt"
PRED_DIR = Path(__file__).parent / "predictions"
RESULTS_PATH = Path(__file__).parent / "cretu_scores.json"


def load_examples() -> list[dict]:
    examples = []
    with open(DATA_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def load_predictions(label: str) -> list[dict]:
    path = PRED_DIR / f"predictions_{label}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"predictions file missing: {path}\n"
            f"Run `python -m cretu_testing.run_cretu_eval --models {label}` first."
        )
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def compute_quality_metrics(predictions: list[str], diffs: list[str]) -> dict:
    """Set 2 — coherence, toxicity, hallucination (regex/heuristic)."""
    from sft.eval.defect_metrics import (
        compute_coherence,
        compute_hallucination_rate,
        compute_toxicity_rate,
    )

    return {
        **compute_coherence(predictions),
        "hallucination_rate": round(compute_hallucination_rate(predictions, diffs), 4),
        "toxicity_rate": round(compute_toxicity_rate(predictions), 4),
    }


def _print_confusion(label: str, agg: dict) -> None:
    tp, fn, fp, tn = agg["tp"], agg["fn"], agg["fp"], agg["tn"]
    print(f"  Confusion matrix ({label}):")
    print(f"                       judged-bug  judged-no-bug")
    print(f"    planted bug        {tp:>10}  {fn:>13}")
    print(f"    clean diff         {fp:>10}  {tn:>13}")
    print(f"  precision = {agg['precision']:.4f}   recall = {agg['recall']:.4f}")
    print(f"  accuracy  = {agg['accuracy']:.4f}   F1     = {agg['f1']:.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="cretu_testing scoring")
    parser.add_argument(
        "--models",
        default="base,sft,rlhf,quantized",
        help="Comma-separated model labels whose predictions are in predictions/",
    )
    parser.add_argument(
        "--backend",
        choices=["gemini", "anthropic"],
        default="gemini",
        help="LLM judge backend",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip Set 1 (LLM judge) and only run Set 2 (quality metrics)",
    )
    parser.add_argument(
        "--by-difficulty",
        action="store_true",
        help="Also report bug-detection metrics bucketed by example difficulty",
    )
    args = parser.parse_args()

    labels = [s.strip() for s in args.models.split(",") if s.strip()]
    examples = load_examples()
    n_clean = sum(1 for e in examples if not e["bugs"])
    n_bugs = sum(len(e["bugs"]) for e in examples)
    print(
        f"Loaded {len(examples)} cretu examples "
        f"({n_bugs} planted bugs, {n_clean} clean diffs)"
    )

    all_results: dict[str, dict] = {}

    for label in labels:
        print(f"\n{'='*60}\nModel: {label}\n{'='*60}")

        try:
            preds = load_predictions(label)
        except FileNotFoundError as e:
            print(f"  skip: {e}")
            continue

        if len(preds) != len(examples):
            print(
                f"  WARN: predictions ({len(preds)}) != examples ({len(examples)}) — "
                "will score on the overlap"
            )
            n = min(len(preds), len(examples))
            ex_slice = examples[:n]
            preds = preds[:n]
        else:
            ex_slice = examples

        pred_texts = [p["prediction"] for p in preds]
        diff_texts = [p["diff"] for p in preds]

        per_model: dict = {}

        # ---- Set 1: Bug detection via LLM judge ----
        if not args.skip_judge:
            print("  Set 1: bug-detection judge ({})".format(args.backend))
            judgements = judge_predictions(
                ex_slice,
                pred_texts,
                model_label=label,
                backend=args.backend,
            )
            overall = aggregate(judgements)
            per_model["bug_detection"] = overall
            _print_confusion(label, overall)

            if args.by_difficulty:
                buckets = aggregate_by_difficulty(ex_slice, judgements)
                per_model["bug_detection_by_difficulty"] = buckets
                print("  By difficulty:")
                for diff, agg in sorted(buckets.items()):
                    print(
                        f"    {diff:<8} "
                        f"P={agg['precision']:.3f}  R={agg['recall']:.3f}  "
                        f"A={agg['accuracy']:.3f}  F1={agg['f1']:.3f}  "
                        f"(TP={agg['tp']} FN={agg['fn']} FP={agg['fp']} TN={agg['tn']})"
                    )

        # ---- Set 2: Quality (coherence, toxicity, hallucination) ----
        print("  Set 2: quality metrics")
        quality = compute_quality_metrics(pred_texts, diff_texts)
        per_model["quality"] = quality
        for k, v in quality.items():
            print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")

        all_results[label] = per_model

    # Comparison table
    if all_results:
        print(f"\n{'='*100}")
        if not args.skip_judge:
            print(
                f"{'Model':<12} {'Prec':>7} {'Recall':>7} {'Acc':>7} {'F1':>7}  "
                f"{'TP':>4} {'FN':>4} {'FP':>4} {'TN':>4}  "
                f"{'Coher':>7} {'Hall%':>7} {'Toxic%':>7}"
            )
            print(f"{'-'*100}")
            for label, m in all_results.items():
                bd = m.get("bug_detection", {})
                q = m.get("quality", {})
                print(
                    f"{label:<12}"
                    f" {bd.get('precision', 0):>7.4f}"
                    f" {bd.get('recall', 0):>7.4f}"
                    f" {bd.get('accuracy', 0):>7.4f}"
                    f" {bd.get('f1', 0):>7.4f}"
                    f"  {bd.get('tp', 0):>4} {bd.get('fn', 0):>4}"
                    f" {bd.get('fp', 0):>4} {bd.get('tn', 0):>4}"
                    f"  {q.get('coherence', 0):>7.4f}"
                    f" {q.get('hallucination_rate', 0):>7.2%}"
                    f" {q.get('toxicity_rate', 0):>7.2%}"
                )
        else:
            print(f"{'Model':<12} {'Coher':>7} {'Hall%':>7} {'Toxic%':>7}")
            print(f"{'-'*100}")
            for label, m in all_results.items():
                q = m.get("quality", {})
                print(
                    f"{label:<12}"
                    f" {q.get('coherence', 0):>7.4f}"
                    f" {q.get('hallucination_rate', 0):>7.2%}"
                    f" {q.get('toxicity_rate', 0):>7.2%}"
                )

    RESULTS_PATH.write_text(json.dumps(all_results, indent=2))
    print(f"\nFull scores saved to {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
