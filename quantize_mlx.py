"""
Quantize cretu-luca/code-reviewer-grpo to 4-bit MLX for local eval on Apple Silicon.

The HF repo is a PEFT LoRA adapter on top of a Qwen base. We:
  1. Download the adapter
  2. Read base_model_name_or_path from adapter_config.json
  3. Load base + adapter on CPU, merge_and_unload, save merged HF checkpoint
  4. Convert to MLX with q4 (or q8) quantization

Usage:
    python quantize_mlx.py
    python quantize_mlx.py --bits 8           # only on a 48GB Mac
    python quantize_mlx.py --upload <hf-repo>  # optional: push the MLX model back
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download

GRPO_REPO = "cretu-luca/code-reviewer-grpo"


def merge_adapter(base_id: str, adapter_dir: Path, out_dir: Path) -> Path:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"[merge] base={base_id}  adapter={adapter_dir}")
    base = AutoModelForCausalLM.from_pretrained(
        base_id,
        torch_dtype=torch.float16,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )
    model = PeftModel.from_pretrained(base, adapter_dir).merge_and_unload()

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    AutoTokenizer.from_pretrained(base_id).save_pretrained(out_dir)
    print(f"[merge] wrote merged model to {out_dir}")
    return out_dir


def quantize_to_mlx(src: Path, out: Path, bits: int) -> None:
    from mlx_lm import convert

    if out.exists():
        shutil.rmtree(out)
    print(f"[mlx] converting {src} -> {out} (q{bits}, group_size=64)")
    convert(
        hf_path=str(src),
        mlx_path=str(out),
        quantize=True,
        q_bits=bits,
        q_group_size=64,
    )
    for p in sorted(out.iterdir()):
        print(f"  {p.name:40s} {p.stat().st_size / (1024**2):8.1f} MB")


def smoke_test(mlx_dir: Path) -> None:
    from mlx_lm import generate, load

    model, tokenizer = load(str(mlx_dir))
    prompt = (
        "You are a senior code reviewer. Review this diff in one sentence:\n"
        "+ def add(a, b): return a - b\n"
    )
    if hasattr(tokenizer, "apply_chat_template"):
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
    print("[smoke] >>>", generate(model, tokenizer, prompt=prompt, max_tokens=80, verbose=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bits", type=int, choices=[4, 8], default=4)
    ap.add_argument("--work", type=Path, default=Path("./.quantize-work"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-smoke", action="store_true")
    ap.add_argument("--upload", type=str, default=None, help="HF repo id to push the MLX model to")
    args = ap.parse_args()

    out_dir = args.out or Path(f"./code-reviewer-grpo-mlx-q{args.bits}")
    args.work.mkdir(parents=True, exist_ok=True)

    adapter_dir = args.work / "grpo-adapter"
    print(f"[fetch] {GRPO_REPO} -> {adapter_dir}")
    snapshot_download(repo_id=GRPO_REPO, local_dir=adapter_dir, local_dir_use_symlinks=False)

    base_id = json.loads((adapter_dir / "adapter_config.json").read_text())["base_model_name_or_path"]
    merged = merge_adapter(base_id, adapter_dir, args.work / "grpo-merged")

    quantize_to_mlx(merged, out_dir, args.bits)

    if not args.no_smoke:
        smoke_test(out_dir)

    if args.upload:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(args.upload, exist_ok=True)
        api.upload_folder(folder_path=str(out_dir), repo_id=args.upload)


if __name__ == "__main__":
    main()
