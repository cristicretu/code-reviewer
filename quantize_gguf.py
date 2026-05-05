"""
Quantize cretu-luca/code-reviewer-grpo using llama.cpp's GGUF toolchain.

Each step is a battle-tested upstream tool from ggml-org/llama.cpp:

  1. convert_hf_to_gguf.py     HF safetensors  -> GGUF f16          (streaming)
  2. convert_lora_to_gguf.py   PEFT adapter    -> GGUF LoRA          (streaming)
  3. llama-export-lora         merge LoRA into GGUF base             (streaming)
  4. llama-quantize            f16 GGUF        -> Q4_K_M (default)   (streaming)

The output is consumed natively by llama-server with Metal acceleration and an
OpenAI-compatible HTTP API:
  llama-server -m code-reviewer-grpo-Q4_K_M.gguf --port 8080
which is a drop-in for MODEL_API_BASE in the agent.

Setup (one time):
  brew install llama.cpp
  git clone https://github.com/ggerganov/llama.cpp ./.quantize-work/llama.cpp-src
  uv pip install -r ./.quantize-work/llama.cpp-src/requirements.txt

Run:
  python quantize/quantize_gguf.py
  python quantize/quantize_gguf.py --quant Q8_0       # 48GB SKU
  python quantize/quantize_gguf.py --quant Q5_K_M     # middle ground (~6.5GB)
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

# Tokenizer files we want from the GRPO adapter (training-time tokenizer + chat template)
TRAINED_TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "special_tokens_map.json",
    "vocab.json",
    "merges.txt",
)

# Files from the base model that define the architecture / weights
BASE_FILES_GLOB = ("*.safetensors", "*.safetensors.index.json", "config.json", "generation_config.json")


def which_or_die(bin_name: str, hint: str) -> str:
    p = shutil.which(bin_name)
    if not p:
        sys.exit(f"error: `{bin_name}` not on PATH. {hint}")
    return p


def run(*args) -> None:
    str_args = [str(a) for a in args]
    print(f"[run] {' '.join(str_args)}")
    subprocess.run(str_args, check=True)


def stage_hf_dir(base_hf: Path, adapter_dir: Path, dst: Path) -> Path:
    """
    Build a directory containing the base model's weights+config but the
    *trained* tokenizer + chat template from the GRPO adapter, so the GGUF
    metadata gets the chat template the model was actually trained with.

    Files are symlinked, not copied, so this stage is free disk-wise.
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    for pattern in BASE_FILES_GLOB:
        for f in base_hf.glob(pattern):
            (dst / f.name).symlink_to(f.resolve())

    for fname in TRAINED_TOKENIZER_FILES:
        src = adapter_dir / fname
        if src.exists():
            link = dst / fname
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(src.resolve())
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--quant",
        default="Q4_K_M",
        choices=["Q4_K_M", "Q4_K_S", "Q5_K_M", "Q5_K_S", "Q6_K", "Q8_0"],
        help="GGUF quantization. Q4_K_M ~5.5GB, Q5_K_M ~6.5GB, Q8_0 ~9.5GB.",
    )
    ap.add_argument("--llama-src", type=Path, default=Path("./.quantize-work/llama.cpp-src"))
    ap.add_argument("--work", type=Path, default=Path("./.quantize-work"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep-intermediate", action="store_true")
    args = ap.parse_args()

    quantize_bin = which_or_die("llama-quantize", "brew install llama.cpp")
    export_lora_bin = which_or_die("llama-export-lora", "brew install llama.cpp")

    convert_hf_py = args.llama_src / "convert_hf_to_gguf.py"
    convert_lora_py = args.llama_src / "convert_lora_to_gguf.py"
    for p in (convert_hf_py, convert_lora_py):
        if not p.exists():
            sys.exit(
                f"missing {p}\n"
                f"  git clone https://github.com/ggerganov/llama.cpp {args.llama_src}\n"
                f"  uv pip install -r {args.llama_src}/requirements.txt"
            )

    args.work.mkdir(parents=True, exist_ok=True)
    out_path = args.out or Path(f"./code-reviewer-grpo-{args.quant}.gguf")

    # 1. Fetch the PEFT adapter
    adapter_dir = args.work / "grpo-adapter"
    print(f"[fetch] {GRPO_REPO} -> {adapter_dir}")
    snapshot_download(repo_id=GRPO_REPO, local_dir=adapter_dir)
    base_id = json.loads((adapter_dir / "adapter_config.json").read_text())["base_model_name_or_path"]
    print(f"[base] {base_id}")

    # 2. Locate the base model in the HF cache (no copy: snapshot_download without
    #    local_dir returns the cache snapshot path directly).
    base_hf = Path(
        snapshot_download(
            repo_id=base_id,
            allow_patterns=["*.safetensors", "*.safetensors.index.json", "*.json", "tokenizer*",
                            "*.txt", "*.jinja"],
        )
    )
    print(f"[base-hf] {base_hf}")

    # 3. Stage a directory: base weights + trained tokenizer (symlinks, ~0 disk)
    staged = stage_hf_dir(base_hf, adapter_dir, args.work / "base-staged")

    # 4. HF -> GGUF f16
    base_gguf = args.work / "base-f16.gguf"
    if not base_gguf.exists():
        run(sys.executable, convert_hf_py, staged, "--outtype", "f16", "--outfile", base_gguf)

    # 5. PEFT adapter -> GGUF LoRA
    lora_gguf = args.work / "grpo-lora.gguf"
    if not lora_gguf.exists():
        run(sys.executable, convert_lora_py, adapter_dir, "--base", staged, "--outfile", lora_gguf)

    # 6. Bake LoRA into base
    fused_gguf = args.work / "grpo-fused-f16.gguf"
    if not fused_gguf.exists():
        run(export_lora_bin, "-m", base_gguf, "--lora", lora_gguf, "-o", fused_gguf)

    # Free the f16 base now that we have the fused GGUF (saves ~18GB during step 7)
    if not args.keep_intermediate:
        base_gguf.unlink(missing_ok=True)

    # 7. Quantize
    run(quantize_bin, fused_gguf, out_path, args.quant)

    if not args.keep_intermediate:
        fused_gguf.unlink(missing_ok=True)
        lora_gguf.unlink(missing_ok=True)

    size_gb = out_path.stat().st_size / (1024**3)
    print(f"\n[done] {out_path}  ({size_gb:.2f} GB)")
    print(f"[serve] llama-server -m {out_path} --port 8080 --host 127.0.0.1 --jinja")
    print(f"        export MODEL_API_BASE=http://localhost:8080/v1")
    print(f"        export MODEL_ID={out_path.stem}")


if __name__ == "__main__":
    main()
