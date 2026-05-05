"""
Quantize cretu-luca/code-reviewer-grpo to 4-bit MLX for local eval on Apple Silicon.

Usage:
    python quantize_mlx.py
    python quantize_mlx.py --bits 8           # if you have 48GB and want to compare
    python quantize_mlx.py --upload <hf-repo>  # optional: push the MLX model back to HF

Outputs an MLX model directory at ./code-reviewer-grpo-mlx-q{bits}/ ready to be
served with `mlx_lm.server` or run with `mlx_lm.generate`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download

GRPO_REPO = "cretu-luca/code-reviewer-grpo"
SFT_LORA_REPO = "cristicretu/code-reviewer-lora"


def is_adapter_only(model_dir: Path) -> bool:
    return (model_dir / "adapter_config.json").exists() and not any(
        model_dir.glob("model*.safetensors")
    ) and not (model_dir / "pytorch_model.bin").exists()


def read_base_model(adapter_dir: Path) -> str:
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
    base = cfg.get("base_model_name_or_path")
    if not base:
        raise RuntimeError(f"adapter_config.json in {adapter_dir} has no base_model_name_or_path")
    return base


def merge_adapter(base_id: str, adapter_dir: Path, out_dir: Path) -> Path:
    """Load base model + LoRA adapter on CPU, merge, save full weights."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"[merge] base={base_id}")
    print(f"[merge] adapter={adapter_dir}")
    base = AutoModelForCausalLM.from_pretrained(
        base_id,
        torch_dtype=torch.float16,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )
    model = PeftModel.from_pretrained(base, adapter_dir)
    print("[merge] merging adapter into base weights...")
    model = model.merge_and_unload()

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    AutoTokenizer.from_pretrained(base_id).save_pretrained(out_dir)
    print(f"[merge] merged model written to {out_dir}")
    return out_dir


def materialize_grpo(work: Path) -> Path:
    """Return a directory containing a *full* (non-adapter) HF checkpoint."""
    grpo_dir = work / "grpo-raw"
    print(f"[fetch] {GRPO_REPO} -> {grpo_dir}")
    snapshot_download(repo_id=GRPO_REPO, local_dir=grpo_dir, local_dir_use_symlinks=False)

    if not is_adapter_only(grpo_dir):
        print("[fetch] grpo repo is a full model, no merge needed")
        return grpo_dir

    print("[fetch] grpo repo is adapter-only, merging on top of base...")
    base_id = read_base_model(grpo_dir)

    # GRPO adapter may have been trained on top of the SFT-merged model. If its
    # base_model_name_or_path points at the original Qwen base, that's fine — we
    # just merge GRPO directly. If it points at a local SFT-merged path, we
    # fall back to merging the SFT LoRA first.
    if Path(base_id).exists() or "/" not in base_id:
        # Local-only path that we can't resolve; fall back to chained merge.
        print(f"[fetch] base path '{base_id}' is not an HF id; chaining SFT->GRPO merge")
        sft_dir = work / "sft-adapter"
        snapshot_download(repo_id=SFT_LORA_REPO, local_dir=sft_dir, local_dir_use_symlinks=False)
        sft_base = read_base_model(sft_dir)
        sft_merged = merge_adapter(sft_base, sft_dir, work / "sft-merged")
        return merge_adapter(str(sft_merged), grpo_dir, work / "grpo-merged")

    return merge_adapter(base_id, grpo_dir, work / "grpo-merged")


def quantize_to_mlx(src: Path, out: Path, bits: int) -> None:
    """Convert a HF checkpoint to MLX with q{bits} quantization."""
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
    print(f"[mlx] done. Files:")
    for p in sorted(out.iterdir()):
        size = p.stat().st_size / (1024**2)
        print(f"  {p.name:40s} {size:8.1f} MB")


def smoke_test(mlx_dir: Path) -> None:
    from mlx_lm import generate, load

    print("[smoke] loading quantized model...")
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
    out = generate(model, tokenizer, prompt=prompt, max_tokens=80, verbose=False)
    print("[smoke] >>>", out)


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

    full_ckpt = materialize_grpo(args.work)
    quantize_to_mlx(full_ckpt, out_dir, args.bits)

    if not args.no_smoke:
        smoke_test(out_dir)

    if args.upload:
        from huggingface_hub import HfApi
        print(f"[upload] pushing {out_dir} -> {args.upload}")
        HfApi().create_repo(args.upload, exist_ok=True)
        HfApi().upload_folder(folder_path=str(out_dir), repo_id=args.upload)


if __name__ == "__main__":
    main()
