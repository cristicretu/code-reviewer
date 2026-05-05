"""Quantize cretu-luca/code-reviewer-grpo to GGUF (default Q4_K_M) via llama.cpp."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

GRPO_REPO = "cretu-luca/code-reviewer-grpo"

TRAINED_TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
    "special_tokens_map.json",
    "vocab.json",
    "merges.txt",
)

BASE_FILES_GLOB = ("*.safetensors", "*.safetensors.index.json", "config.json", "generation_config.json")


def which_or_die(bin_name: str, hint: str, *extra_dirs: Path) -> str:
    p = shutil.which(bin_name)
    if p:
        return p
    for d in extra_dirs:
        candidate = d / bin_name
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return str(candidate)
    sys.exit(f"error: `{bin_name}` not on PATH. {hint}")


def run(*args) -> None:
    str_args = [str(a) for a in args]
    print(f"[run] {' '.join(str_args)}")
    subprocess.run(str_args, check=True)


def stage_hf_dir(base_hf: Path, adapter_dir: Path, dst: Path) -> Path:
    """Symlink base weights + trained tokenizer into one HF-style dir for the converter."""
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
    ap.add_argument("--quant", default="Q4_K_M",
                    choices=["Q4_K_M", "Q4_K_S", "Q5_K_M", "Q5_K_S", "Q6_K", "Q8_0"])
    ap.add_argument("--llama-src", type=Path, default=Path("./.quantize-work/llama.cpp-src"))
    ap.add_argument("--work", type=Path, default=Path("./.quantize-work"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep-intermediate", action="store_true")
    args = ap.parse_args()

    local_build_bin = args.llama_src / "build" / "bin"
    quantize_bin = which_or_die("llama-quantize", "brew install llama.cpp", local_build_bin)
    export_lora_bin = which_or_die(
        "llama-export-lora",
        f"cmake -S {args.llama_src} -B {args.llama_src}/build -DGGML_METAL=ON "
        f"&& cmake --build {args.llama_src}/build --target llama-export-lora -j",
        local_build_bin,
    )

    convert_hf_py = args.llama_src / "convert_hf_to_gguf.py"
    convert_lora_py = args.llama_src / "convert_lora_to_gguf.py"
    for p in (convert_hf_py, convert_lora_py):
        if not p.exists():
            sys.exit(f"missing {p}\n  git clone https://github.com/ggerganov/llama.cpp {args.llama_src}")

    args.work.mkdir(parents=True, exist_ok=True)
    out_path = args.out or Path(f"./code-reviewer-grpo-{args.quant}.gguf")

    adapter_dir = args.work / "grpo-adapter"
    print(f"[fetch] {GRPO_REPO} -> {adapter_dir}")
    snapshot_download(repo_id=GRPO_REPO, local_dir=adapter_dir)
    base_id = json.loads((adapter_dir / "adapter_config.json").read_text())["base_model_name_or_path"]
    print(f"[base] {base_id}")

    base_hf = Path(snapshot_download(
        repo_id=base_id,
        allow_patterns=["*.safetensors", "*.safetensors.index.json", "*.json", "tokenizer*", "*.txt", "*.jinja"],
    ))

    staged = stage_hf_dir(base_hf, adapter_dir, args.work / "base-staged")

    base_gguf = args.work / "base-f16.gguf"
    if not base_gguf.exists():
        run(sys.executable, convert_hf_py, staged, "--outtype", "f16", "--outfile", base_gguf)

    lora_gguf = args.work / "grpo-lora.gguf"
    if not lora_gguf.exists():
        run(sys.executable, convert_lora_py, adapter_dir, "--base", staged, "--outfile", lora_gguf)

    fused_gguf = args.work / "grpo-fused-f16.gguf"
    if not fused_gguf.exists():
        run(export_lora_bin, "-m", base_gguf, "--lora", lora_gguf, "-o", fused_gguf)

    if not args.keep_intermediate:
        base_gguf.unlink(missing_ok=True)

    run(quantize_bin, fused_gguf, out_path, args.quant)

    if not args.keep_intermediate:
        fused_gguf.unlink(missing_ok=True)
        lora_gguf.unlink(missing_ok=True)

    size_gb = out_path.stat().st_size / (1024**3)
    print(f"\n[done] {out_path}  ({size_gb:.2f} GB)")
    print(f"[serve] llama-server -m {out_path} --port 8080 --host 127.0.0.1 --jinja")


if __name__ == "__main__":
    main()
