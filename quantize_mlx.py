"""
Quantize cretu-luca/code-reviewer-grpo to 4-bit MLX for local eval on Apple Silicon.

Why this script does NOT call peft.merge_and_unload:
  Loading Qwen3.5-9B in fp16 on CPU costs ~18GB. peft.merge_and_unload then
  needs to write a fp16 state_dict to disk while the model is still resident,
  which on a 24GB M4 Pro trips macOS jetsam and the process is killed silently
  during "Writing model shards" (you see a leaked-semaphore warning at exit).

  mlx-lm's fuse path avoids this: weights are loaded as MLX arrays which are
  lazy / mmapped, and the fuse step rewrites layer-by-layer. Peak RAM ~8-10GB.

Pipeline:
  1. Download the PEFT adapter from HF
  2. mlx_lm.convert: HF base -> MLX bf16 (streaming)
  3. mlx_lm.fuse: bake the PEFT adapter into the MLX base
  4. mlx_lm.convert: quantize the fused model to q4 (or q8)

Run:
    python quantize/quantize_mlx.py
    python quantize/quantize_mlx.py --bits 8           # only on a 48GB Mac
    python quantize/quantize_mlx.py --upload <hf-repo>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

GRPO_REPO = "cretu-luca/code-reviewer-grpo"


def run(*args: str) -> None:
    print(f"[run] {' '.join(args)}")
    subprocess.run([sys.executable, "-m", *args], check=True)


def convert_hf_to_mlx(hf_path: str, mlx_path: Path) -> None:
    if mlx_path.exists():
        print(f"[mlx] reusing {mlx_path}")
        return
    run("mlx_lm", "convert", "--hf-path", hf_path, "--mlx-path", str(mlx_path))


def fuse_adapter(base_mlx: Path, adapter_dir: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    run(
        "mlx_lm", "fuse",
        "--model", str(base_mlx),
        "--adapter-path", str(adapter_dir),
        "--save-path", str(out),
    )


def quantize_mlx(src: Path, out: Path, bits: int) -> None:
    if out.exists():
        shutil.rmtree(out)
    run(
        "mlx_lm", "convert",
        "--hf-path", str(src),
        "--mlx-path", str(out),
        "-q",
        "--q-bits", str(bits),
        "--q-group-size", "64",
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
    snapshot_download(repo_id=GRPO_REPO, local_dir=adapter_dir)

    base_id = json.loads((adapter_dir / "adapter_config.json").read_text())["base_model_name_or_path"]
    print(f"[base] {base_id}")

    base_mlx = args.work / "base-mlx-bf16"
    fused_mlx = args.work / "grpo-fused-mlx"

    convert_hf_to_mlx(base_id, base_mlx)
    fuse_adapter(base_mlx, adapter_dir, fused_mlx)
    quantize_mlx(fused_mlx, out_dir, args.bits)

    if not args.no_smoke:
        smoke_test(out_dir)

    if args.upload:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(args.upload, exist_ok=True)
        api.upload_folder(folder_path=str(out_dir), repo_id=args.upload)


if __name__ == "__main__":
    main()
