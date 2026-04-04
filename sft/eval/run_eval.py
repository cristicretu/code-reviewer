"""Orchestrate the full evaluation pipeline.

Runs a model on the test set and computes all metrics:
    1. Generate predictions on test split
    2. Compute automated metrics (ChrF, ROUGE-L, CodeBERTScore)
    3. Optionally run LLM-as-judge (if ANTHROPIC_API_KEY is set)

Usage:
    python -m sft.eval.run_eval --model outputs/sft/final
    python -m sft.eval.run_eval --model Qwen/Qwen3.5-9B  # evaluate base model

Add --judge to also run LLM-as-judge (requires ANTHROPIC_API_KEY).
"""

import unsloth  # noqa: F401 — must be imported before transformers

import argparse
import json
import os
from pathlib import Path

from sft.eval.metrics import compute_metrics


def generate_predictions(
    model_path: str,
    test_path: str,
    max_new_tokens: int = 256,
    max_examples: int | None = None,
) -> list[dict]:
    """Generate review comments for test examples."""
    from unsloth import FastLanguageModel

    print(f"Loading model: {model_path}")
    model, processing_class = FastLanguageModel.from_pretrained(
        model_name=model_path,
        max_seq_length=2048,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)

    # Extract tokenizer from VL processor if needed
    if hasattr(processing_class, "tokenizer"):
        tokenizer = processing_class.tokenizer
    else:
        tokenizer = processing_class

    # Load test data
    examples = []
    with open(test_path) as f:
        for line in f:
            examples.append(json.loads(line))

    if max_examples:
        examples = examples[:max_examples]

    print(f"Generating predictions for {len(examples)} examples...")
    results = []
    for i, ex in enumerate(examples):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  {i+1}/{len(examples)}...")

        messages = ex["messages"][:2]  # system + user only
        reference = ex["messages"][2]["content"]  # assistant = ground truth

        # Extract the diff from the user message for judge context
        user_msg = messages[1]["content"]

        inputs = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)

        outputs = model.generate(
            input_ids=inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            do_sample=True,
        )
        prediction = tokenizer.decode(
            outputs[0][inputs.shape[1]:], skip_special_tokens=True
        )

        results.append({
            "diff": user_msg,
            "prediction": prediction,
            "reference": reference,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Full evaluation pipeline")
    parser.add_argument("--model", required=True, help="Model path or HF model ID")
    parser.add_argument("--test-data", default="data/processed/test.jsonl")
    parser.add_argument("--max-examples", type=int, default=None,
                        help="Limit test examples (useful for quick checks)")
    parser.add_argument("--judge", action="store_true",
                        help="Also run LLM-as-judge (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--judge-n", type=int, default=50)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/eval"))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_name = Path(args.model).name or args.model.replace("/", "_")

    # Step 1: Generate predictions
    predictions_path = args.output_dir / f"predictions_{model_name}.jsonl"

    if predictions_path.exists():
        print(f"Loading cached predictions from {predictions_path}")
        results = []
        with open(predictions_path) as f:
            for line in f:
                results.append(json.loads(line))
    else:
        results = generate_predictions(
            args.model, args.test_data, max_examples=args.max_examples
        )
        with open(predictions_path, "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
        print(f"Predictions saved to {predictions_path}")

    # Step 2: Automated metrics
    print("\nComputing automated metrics...")
    preds = [r["prediction"] for r in results]
    refs = [r["reference"] for r in results]

    metrics = compute_metrics(preds, refs)

    print(f"\n{'='*40}")
    print(f"Results for: {args.model}")
    print(f"{'='*40}")
    print(f"  ChrF:           {metrics['chrf']:.2f}")
    print(f"  ROUGE-L:        {metrics['rouge_l']:.4f}")
    cbs = metrics.get("code_bert_score")
    if cbs is not None:
        print(f"  CodeBERTScore:  {cbs:.4f}")
    else:
        print(f"  CodeBERTScore:  (not available)")

    # Save metrics
    metrics_path = args.output_dir / f"metrics_{model_name}.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nMetrics saved to {metrics_path}")

    # Step 3: LLM-as-judge (optional)
    if args.judge:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("\nWARNING: ANTHROPIC_API_KEY not set, skipping LLM-as-judge")
        else:
            from sft.eval.judge import run_judge

            print(f"\nRunning LLM-as-judge on {args.judge_n} examples...")
            judge_results = run_judge(results, n=args.judge_n)

            judge_path = args.output_dir / f"judge_{model_name}.json"
            with open(judge_path, "w") as f:
                json.dump(judge_results, f, indent=2)

            print(f"\nJudge Results:")
            for dim in ["accuracy", "helpfulness", "specificity"]:
                print(f"  {dim}: {judge_results[f'mean_{dim}']:.2f} / 5.0")
            print(f"Saved to {judge_path}")


if __name__ == "__main__":
    main()
