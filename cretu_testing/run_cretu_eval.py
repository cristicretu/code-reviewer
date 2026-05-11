"""Eval runner for cretu_testing/cretu.txt.

This is a thin wrapper over ood_testing.run_ood_eval that points at the harder
dataset. It reuses the same generation backends, prompts, and metrics so the
numbers are directly comparable to the OOD eval.

Usage:
    python -m cretu_testing.run_cretu_eval
    python -m cretu_testing.run_cretu_eval --models base,sft --max-examples 20
    python -m cretu_testing.run_cretu_eval --skip-existing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ood_testing.run_ood_eval import (
    MODEL_CONFIGS,
    compute_all_metrics,
    generate_predictions,
    load_ood_data,
)

DATA_PATH = Path(__file__).parent / "cretu.txt"
PRED_DIR = Path(__file__).parent / "predictions"
RESULTS_PATH = Path(__file__).parent / "cretu_results.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="cretu_testing eval")
    parser.add_argument("--models", default="base,sft,rlhf,quantized")
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    requested = set(args.models.split(","))
    configs = [c for c in MODEL_CONFIGS if c["label"] in requested]
    if not configs:
        print(f"ERROR: no matching model configs for: {args.models}")
        return 1

    examples = load_ood_data(DATA_PATH, args.max_examples)
    n_clean = sum(1 for e in examples if not e["bugs"])
    n_multi_file = sum(1 for e in examples if e["diff"].count("diff --git") > 1)
    n_multi_bug = sum(1 for e in examples if len(e["bugs"]) > 1)
    print(
        f"Loaded {len(examples)} cretu examples "
        f"({n_clean} clean, {n_multi_file} multi-file, {n_multi_bug} multi-bug)"
    )

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, dict] = {}

    for config in configs:
        label = config["label"]
        pred_path = PRED_DIR / f"predictions_{label}.jsonl"

        print(f"\n{'='*60}\nModel: {label}\n{'='*60}")

        if args.skip_existing and pred_path.exists():
            print(f"  Loading cached predictions from {pred_path}")
            with open(pred_path) as f:
                results = [json.loads(line) for line in f]
        else:
            results = generate_predictions(config, examples)
            with open(pred_path, "w") as f:
                for r in results:
                    f.write(json.dumps(r) + "\n")
            print(f"  Saved {len(results)} predictions to {pred_path}")

        print("  Computing metrics...")
        metrics = compute_all_metrics(results)
        all_results[label] = metrics

        avg_len = sum(len(r["prediction"]) for r in results) / len(results)
        print(f"  avg prediction length: {avg_len:.0f} chars")
        for k, v in metrics.items():
            if v is not None:
                print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    print(f"\n{'='*100}")
    header = (
        f"{'Model':<12} {'CBS':>8} {'ChrF':>7} {'ROUGE':>7} {'DefF1':>7} "
        f"{'BDR':>7} {'FPR':>6} {'Hall%':>7} {'Coher':>7} {'Toxic%':>7}"
    )
    print(header)
    print(f"{'-'*100}")
    for label, m in all_results.items():
        cbs = m.get("code_bert_score") or 0.0
        print(
            f"{label:<12}"
            f" {cbs:>8.4f}"
            f" {m.get('chrf', 0):>7.2f}"
            f" {m.get('rouge_l', 0):>7.4f}"
            f" {m.get('defect_f1', 0):>7.4f}"
            f" {m.get('bug_detection_rate', 0):>7.4f}"
            f" {m.get('false_positive_rate', 0):>6.2%}"
            f" {m.get('hallucination_rate', 0):>7.2%}"
            f" {m.get('coherence', 0):>7.4f}"
            f" {m.get('toxicity_rate', 0):>7.2%}"
        )

    with open(RESULTS_PATH, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nFull results saved to {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
