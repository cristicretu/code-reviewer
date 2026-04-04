"""Download the Microsoft CodeReviewer dataset from HuggingFace.

Usage:
    python -m sft.data.download [--out-dir data/raw]
"""

import argparse
from pathlib import Path

from datasets import load_dataset


DEFAULT_OUT = Path("data/raw")


def download(out_dir: Path = DEFAULT_OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # CodeReviewer "msg" config: (patch, msg) pairs for comment generation
    print("Downloading microsoft/code_reviewer (msg config)...")
    ds = load_dataset("microsoft/code_reviewer", "msg", trust_remote_code=True)

    for split_name, split_ds in ds.items():
        out_path = out_dir / f"code_reviewer_{split_name}.jsonl"
        split_ds.to_json(out_path)
        print(f"  {split_name}: {len(split_ds):,} examples -> {out_path}")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download CodeReviewer dataset")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    download(args.out_dir)
