"""Split preprocessed SFT data into train/val/test (80/10/10).

Reads:
    - data/processed/sft_train.jsonl

Writes:
    - data/processed/train.jsonl
    - data/processed/val.jsonl
    - data/processed/test.jsonl

Usage:
    python -m sft.data.split [--in-dir data/processed] [--seed 42]
"""

import argparse
import json
import random
from pathlib import Path

DEFAULT_IN = Path("data/processed")


def split(in_dir: Path = DEFAULT_IN, seed: int = 42) -> None:
    in_path = in_dir / "sft_train.jsonl"
    if not in_path.exists():
        raise FileNotFoundError(
            f"{in_path} not found. Run `python -m sft.data.preprocess` first."
        )

    # Load all examples
    with open(in_path) as f:
        examples = [json.loads(line) for line in f]

    print(f"Total examples: {len(examples):,}")

    # Shuffle deterministically
    random.seed(seed)
    random.shuffle(examples)

    # 80/10/10 split
    n = len(examples)
    n_train = int(0.8 * n)
    n_val = int(0.1 * n)

    splits = {
        "train": examples[:n_train],
        "val": examples[n_train : n_train + n_val],
        "test": examples[n_train + n_val :],
    }

    for name, data in splits.items():
        out_path = in_dir / f"{name}.jsonl"
        with open(out_path, "w") as f:
            for ex in data:
                f.write(json.dumps(ex) + "\n")
        print(f"  {name}: {len(data):,} examples -> {out_path}")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train/val/test split")
    parser.add_argument("--in-dir", type=Path, default=DEFAULT_IN)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    split(args.in_dir, args.seed)
