"""Cross-reference CodeReviewer with cleaned labels to keep only 'valid' examples.

Reads:
    - data/raw/code_reviewer_train.jsonl  (raw CodeReviewer training data)
    - data/labels/RQ1_Noisy_Classification/  (cleaned labels from Zenodo)

Writes:
    - data/processed/filtered.jsonl  (only examples labeled "valid")

Usage:
    python -m sft.data.filter [--raw-dir data/raw] [--labels-dir data/labels] [--out-dir data/processed]
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from tqdm import tqdm


DEFAULT_RAW = Path("data/raw")
DEFAULT_LABELS = Path("data/labels")
DEFAULT_OUT = Path("data/processed")


def load_labels(labels_dir: Path) -> set[int]:
    """Load the set of valid example indices from Zenodo CSVs.

    The exact CSV format may vary -- this function tries common patterns:
    1. A column like 'label' or 'classification' with 'valid'/'noisy' values
    2. A column like 'is_valid' or 'is_noisy' with boolean values
    3. An 'index' or 'id' column identifying the example

    After downloading, inspect the CSVs and adjust this function if needed.
    """
    label_dir = labels_dir / "RQ1_Noisy_Classification"
    if not label_dir.exists():
        # Try finding CSVs directly in labels_dir
        label_dir = labels_dir

    csvs = sorted(label_dir.glob("**/*.csv"))
    if not csvs:
        raise FileNotFoundError(
            f"No CSV files found in {label_dir}. "
            "Run `python -m sft.data.download_labels` first."
        )

    valid_indices: set[int] = set()

    for csv_path in csvs:
        print(f"  Reading {csv_path.name}...")
        df = pd.read_csv(csv_path)
        cols_lower = {c.lower(): c for c in df.columns}

        # Try to find the label column
        label_col = None
        for candidate in ["label", "classification", "class", "category"]:
            if candidate in cols_lower:
                label_col = cols_lower[candidate]
                break

        # Try to find the index column
        idx_col = None
        for candidate in ["index", "id", "idx", "example_id", "sample_id"]:
            if candidate in cols_lower:
                idx_col = cols_lower[candidate]
                break

        if label_col is None:
            print(f"    WARNING: Could not find label column in {csv_path.name}")
            print(f"    Columns: {list(df.columns)}")
            print("    Please inspect this file and update filter.py if needed.")
            continue

        # Determine which rows are valid
        unique_labels = df[label_col].unique()
        print(f"    Label column '{label_col}' has values: {unique_labels}")

        # Common patterns for "valid"
        valid_mask = df[label_col].astype(str).str.lower().isin(
            ["valid", "useful", "1", "true", "clean", "good"]
        )

        if idx_col:
            valid_ids = set(df.loc[valid_mask, idx_col].astype(int).tolist())
        else:
            # Use row position as index
            valid_ids = set(df.loc[valid_mask].index.tolist())

        valid_indices.update(valid_ids)
        print(f"    Found {len(valid_ids):,} valid examples in {csv_path.name}")

    return valid_indices


def filter_dataset(
    raw_dir: Path = DEFAULT_RAW,
    labels_dir: Path = DEFAULT_LABELS,
    out_dir: Path = DEFAULT_OUT,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load valid indices
    print("Loading cleaned labels...")
    valid_indices = load_labels(labels_dir)
    print(f"Total valid indices from labels: {len(valid_indices):,}")

    # Filter training data
    raw_path = raw_dir / "code_reviewer_train.jsonl"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"{raw_path} not found. Run `python -m sft.data.download` first."
        )

    out_path = out_dir / "filtered.jsonl"
    kept = 0
    total = 0

    print(f"Filtering {raw_path}...")
    with open(raw_path) as fin, open(out_path, "w") as fout:
        for i, line in enumerate(tqdm(fin, desc="Filtering")):
            total += 1
            if i in valid_indices:
                fout.write(line)
                kept += 1

    print(f"Kept {kept:,} / {total:,} examples ({kept/total*100:.1f}%)")
    print(f"Output: {out_path}")

    # Also copy validation and test splits unfiltered
    # (the Zenodo labels only cover the training set)
    for split in ["validation", "test"]:
        src = raw_dir / f"code_reviewer_{split}.jsonl"
        if src.exists():
            dst = out_dir / f"code_reviewer_{split}.jsonl"
            import shutil
            shutil.copy2(src, dst)
            print(f"Copied {split} split: {dst}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter CodeReviewer to valid examples")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    filter_dataset(args.raw_dir, args.labels_dir, args.out_dir)
