"""OOD evaluation on 100-syntetic.txt for all four model variants.

Models evaluated (sequentially — one at a time to fit in 24 GB unified memory):
  base       — Qwen/Qwen3.5-9B, BF16, no fine-tuning
  sft        — cretu-luca/code-reviewer-lora (PEFT adapter on same base)
  rlhf       — cretu-luca/code-reviewer-grpo (PEFT adapter on same base)
  quantized  — cretu-luca/code-reviewer-4-bit (MLX 4-bit or HF 4-bit)

Inference backends (auto-detected):
  mlx_lm     — used when mlx_lm is importable AND model is in MLX format
  transformers + PEFT — fallback for all other cases

Metrics:
  ChrF, ROUGE-L, CodeBERTScore    (sft/eval/metrics.py)
  Defect F1, Coherence, Hallucination rate, Toxicity rate  (sft/eval/defect_metrics.py)
  Bug Detection Rate, False Positive Rate  (ood_testing/ood_metrics.py)

Usage:
    python -m ood_testing.run_ood_eval
    python -m ood_testing.run_ood_eval --models base,sft --max-examples 20
    python -m ood_testing.run_ood_eval --skip-existing  # skip generation if preds exist
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

_BASE_MODEL_ID = "Qwen/Qwen3.5-9B"

MODEL_CONFIGS: list[dict] = [
    {
        "label": "base",
        "model_id": _BASE_MODEL_ID,
        "adapter_id": None,
    },
    {
        "label": "sft",
        "model_id": None,          # derived from adapter_config.json at runtime
        "adapter_id": "cretu-luca/code-reviewer-lora",
    },
    {
        "label": "rlhf",
        "model_id": None,
        "adapter_id": "cretu-luca/code-reviewer-grpo",
    },
    {
        "label": "quantized",
        "model_id": "cretu-luca/code-reviewer-4-bit",
        "adapter_id": None,
    },
]

# Chat format from SFT training (sft/data/preprocess.py)
SYSTEM_PROMPT = (
    "You are an expert code reviewer. Given a code diff, provide a concise, "
    "actionable review comment. Focus on:\n"
    "- Bugs and logic errors\n"
    "- Security vulnerabilities\n"
    "- Performance issues\n"
    "- Code style and best practices\n\n"
    "Be specific: reference the exact code that needs changing and explain why. "
    "If the code looks correct, say so briefly."
)

OOD_DATA_PATH = Path(__file__).parent / "100-syntetic.txt"
PRED_DIR = Path(__file__).parent / "predictions"
RESULTS_PATH = Path(__file__).parent / "ood_results.json"

MAX_NEW_TOKENS = 512


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_ood_data(path: Path, max_examples: int | None = None) -> list[dict]:
    examples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    if max_examples:
        examples = examples[:max_examples]
    return examples


def build_reference_text(bugs: list[dict]) -> str:
    """Convert structured bugs to a reference string for similarity metrics."""
    if not bugs:
        return "The code looks correct. No issues found."
    return " ".join(b.get("description", "") for b in bugs)


# ---------------------------------------------------------------------------
# Think-tag stripping
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Remove Qwen3 <think>...</think> blocks; return the response portion only."""
    return _THINK_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# MLX backend (optional)
# ---------------------------------------------------------------------------

def _try_mlx_generate(model_id: str, prompts: list[str], verbose: bool = True) -> list[str] | None:
    """Try to generate using mlx_lm. Returns None if mlx_lm is not available or fails."""
    try:
        from mlx_lm import load, generate as mlx_gen  # noqa: F401
    except ImportError:
        return None

    try:
        print(f"  [mlx_lm] loading {model_id}...")
        model, tokenizer = load(model_id)
        results = []
        for i, prompt in enumerate(prompts):
            print(f"\r  generating {i+1}/{len(prompts)}...", end="", flush=True)
            out = mlx_gen(model, tokenizer, prompt=prompt, max_tokens=MAX_NEW_TOKENS, verbose=False)
            results.append(strip_think(out))
        print()
        del model
        gc.collect()
        return results
    except Exception as e:
        print(f"  [mlx_lm] failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Transformers backend
# ---------------------------------------------------------------------------

def _resolve_base_model_id(adapter_id: str) -> str:
    """Read base_model_name_or_path from the adapter's adapter_config.json on HF."""
    from huggingface_hub import hf_hub_download
    import json as _json

    cfg_path = hf_hub_download(repo_id=adapter_id, filename="adapter_config.json")
    with open(cfg_path) as f:
        cfg = _json.load(f)
    base = cfg.get("base_model_name_or_path", _BASE_MODEL_ID)
    print(f"  adapter base: {base}")
    return base


def _get_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_transformers(model_id: str, adapter_id: str | None, device: str, load_in_4bit: bool = False):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"  [transformers] loading {adapter_id or model_id} on {device}...")

    load_kwargs: dict = {}
    if load_in_4bit and device == "cuda":
        # bitsandbytes 4-bit only works on CUDA
        from transformers import BitsAndBytesConfig
        load_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
    else:
        load_kwargs["torch_dtype"] = torch.bfloat16

    if adapter_id:
        base_id = _resolve_base_model_id(adapter_id)
        base = AutoModelForCausalLM.from_pretrained(
            base_id, device_map=device, **load_kwargs
        )
        from peft import PeftModel
        model = PeftModel.from_pretrained(base, adapter_id)
        tokenizer = AutoTokenizer.from_pretrained(adapter_id)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, device_map=device, **load_kwargs
        )
        tokenizer = AutoTokenizer.from_pretrained(model_id)

    model.eval()
    return model, tokenizer


def _generate_transformers(
    model, tokenizer, messages_batch: list[list[dict]]
) -> list[str]:
    import torch

    results = []
    for i, messages in enumerate(messages_batch):
        print(f"\r  generating {i+1}/{len(messages_batch)}...", end="", flush=True)

        inputs = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                input_ids=inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                temperature=0.1,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
            )

        new_tokens = outputs[0][inputs.shape[1]:]
        prediction = tokenizer.decode(new_tokens, skip_special_tokens=True)
        results.append(strip_think(prediction))

    print()
    return results


# ---------------------------------------------------------------------------
# Prediction generation
# ---------------------------------------------------------------------------

def build_messages(diff: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Review this code change:\n\n```diff\n{diff}\n```"},
    ]


def generate_predictions(
    config: dict, examples: list[dict]
) -> list[dict]:
    """Generate predictions for all examples using the given model config."""
    label = config["label"]
    model_id = config["model_id"]
    adapter_id = config["adapter_id"]

    messages_batch = [build_messages(ex["diff"]) for ex in examples]

    # For quantized model, try mlx_lm first (MLX 4-bit models load best this way)
    if label == "quantized" and model_id:
        # Build flat prompts for mlx_lm (it takes a single string, not messages)
        # Use tokenizer-rendered prompt from tokenizer if we can, otherwise build manually
        from transformers import AutoTokenizer
        try:
            tok = AutoTokenizer.from_pretrained(model_id)
            prompts = [
                tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
                for msgs in messages_batch
            ]
            del tok
        except Exception:
            prompts = [
                f"{SYSTEM_PROMPT}\n\nReview this code change:\n\n```diff\n{ex['diff']}\n```\n"
                for ex in examples
            ]

        mlx_results = _try_mlx_generate(model_id, prompts)
        if mlx_results is not None:
            return [
                {
                    "diff": ex["diff"],
                    "prediction": pred,
                    "reference": build_reference_text(ex["bugs"]),
                    "bugs": ex["bugs"],
                    "is_clean": len(ex["bugs"]) == 0,
                }
                for ex, pred in zip(examples, mlx_results)
            ]

    # Transformers backend
    device = _get_device()
    load_in_4bit = (label == "quantized" and device == "cuda")
    model, tokenizer = _load_transformers(model_id, adapter_id, device, load_in_4bit=load_in_4bit)

    predictions = _generate_transformers(model, tokenizer, messages_batch)

    # Free memory before next model
    del model, tokenizer
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass

    return [
        {
            "diff": ex["diff"],
            "prediction": pred,
            "reference": build_reference_text(ex["bugs"]),
            "bugs": ex["bugs"],
            "is_clean": len(ex["bugs"]) == 0,
        }
        for ex, pred in zip(examples, predictions)
    ]


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_all_metrics(results: list[dict]) -> dict:
    preds = [r["prediction"] for r in results]
    refs = [r["reference"] for r in results]
    diffs = [r["diff"] for r in results]
    bug_lists = [r["bugs"] for r in results]

    from sft.eval.metrics import compute_metrics
    from sft.eval.defect_metrics import (
        compute_defect_f1,
        compute_hallucination_rate,
        compute_coherence,
        compute_toxicity_rate,
    )
    from ood_testing.ood_metrics import compute_bug_detection_rate, compute_false_positive_rate

    scores = compute_metrics(preds, refs)
    defect = compute_defect_f1(preds, refs)
    bdr = compute_bug_detection_rate(preds, bug_lists)
    fpr = compute_false_positive_rate(preds, bug_lists)

    return {
        **scores,
        **defect,
        "hallucination_rate": compute_hallucination_rate(preds, diffs),
        **compute_coherence(preds),
        "toxicity_rate": compute_toxicity_rate(preds),
        **bdr,
        "false_positive_rate": fpr,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="OOD evaluation on synthetic bug dataset")
    parser.add_argument(
        "--models",
        default="base,sft,rlhf,quantized",
        help="Comma-separated list of model labels to evaluate",
    )
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip generation if predictions file already exists",
    )
    args = parser.parse_args()

    requested = set(args.models.split(","))
    configs = [c for c in MODEL_CONFIGS if c["label"] in requested]

    if not configs:
        print(f"ERROR: no matching model configs for: {args.models}")
        return 1

    examples = load_ood_data(OOD_DATA_PATH, args.max_examples)
    print(f"Loaded {len(examples)} OOD examples ({sum(1 for e in examples if not e['bugs'])} clean)")

    PRED_DIR.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, dict] = {}

    for config in configs:
        label = config["label"]
        pred_path = PRED_DIR / f"predictions_{label}.jsonl"

        print(f"\n{'='*60}")
        print(f"Model: {label}")
        print(f"{'='*60}")

        if args.skip_existing and pred_path.exists():
            print(f"  Loading cached predictions from {pred_path}")
            results = []
            with open(pred_path) as f:
                for line in f:
                    results.append(json.loads(line))
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

    # Summary table
    print(f"\n{'='*100}")
    header = f"{'Model':<12} {'CBS':>8} {'ChrF':>7} {'ROUGE':>7} {'DefF1':>7} {'BDR':>7} {'FPR':>6} {'Hall%':>7} {'Coher':>7} {'Toxic%':>7}"
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
