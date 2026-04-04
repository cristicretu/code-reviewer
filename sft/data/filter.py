"""Cross-reference CodeReviewer with cleaned labels to keep only valid examples.

This script:
1. Reads the raw CodeReviewer Comment_Generation data (paired line files from Zenodo)
2. Reads the RQ1_Noisy_Classification labels
3. Keeps only examples labeled as "valid"
4. Outputs filtered data as JSONL

Usage:
    python -m sft.data.filter [--raw-dir data/raw] [--labels-dir data/labels] [--out-dir data/processed]
"""

import argparse
import csv
import json
from pathlib import Path

import pandas as pd
from tqdm import tqdm


DEFAULT_RAW = Path("data/raw")
DEFAULT_LABELS = Path("data/labels")
DEFAULT_OUT = Path("data/processed")


def find_paired_files(raw_dir: Path) -> dict[str, tuple[Path, Path]]:
    """Find paired (source/diff, target/msg) files in the extracted data.

    CodeReviewer uses paired line files where line N in source corresponds
    to line N in target. Common naming patterns:
    - train.source / train.target
    - train.diff / train.msg
    - Or nested in directories
    """
    splits = {}

    # Search recursively for paired files
    for f in sorted(raw_dir.rglob("*")):
        if not f.is_file():
            continue
        name = f.name.lower()
        stem = f.stem.lower()

        # Try to identify source (diff) files
        if any(x in name for x in [".source", ".diff", "input"]):
            split_name = stem.split(".")[0]  # e.g., "train" from "train.source"
            if split_name not in splits:
                splits[split_name] = [None, None]
            splits[split_name][0] = f

        # Try to identify target (msg/comment) files
        if any(x in name for x in [".target", ".msg", "output"]):
            split_name = stem.split(".")[0]
            if split_name not in splits:
                splits[split_name] = [None, None]
            splits[split_name][1] = f

    result = {}
    for split_name, (src, tgt) in splits.items():
        if src and tgt:
            result[split_name] = (src, tgt)
        else:
            print(f"  WARNING: incomplete pair for '{split_name}': src={src}, tgt={tgt}")

    return result


def load_paired_lines(source_path: Path, target_path: Path) -> list[dict]:
    """Load paired line files into a list of {patch, msg} dicts."""
    with open(source_path, encoding="utf-8", errors="replace") as f:
        sources = f.readlines()
    with open(target_path, encoding="utf-8", errors="replace") as f:
        targets = f.readlines()

    if len(sources) != len(targets):
        print(f"  WARNING: line count mismatch: {len(sources)} sources vs {len(targets)} targets")

    examples = []
    for src, tgt in zip(sources, targets):
        examples.append({
            "patch": src.strip(),
            "msg": tgt.strip(),
        })
    return examples


def load_valid_indices(labels_dir: Path) -> set[int] | None:
    """Load valid example indices from RQ1_Noisy_Classification.

    Returns a set of indices (0-based line numbers) that are labeled valid,
    or None if no labels are found (in which case we skip filtering).
    """
    # Search for label files
    label_files = (
        list(labels_dir.rglob("*.csv"))
        + list(labels_dir.rglob("*.xlsx"))
        + list(labels_dir.rglob("*.jsonl"))
    )

    if not label_files:
        print(f"  No label files found in {labels_dir}")
        print("  Listing contents:")
        for f in sorted(labels_dir.rglob("*")):
            if f.is_file():
                print(f"    {f.relative_to(labels_dir)} ({f.stat().st_size:,} bytes)")
        return None

    print(f"  Found {len(label_files)} label files:")
    for f in label_files:
        print(f"    {f.relative_to(labels_dir)}")

    valid_indices: set[int] = set()

    for label_file in label_files:
        suffix = label_file.suffix.lower()

        if suffix == ".csv":
            df = pd.read_csv(label_file)
        elif suffix == ".xlsx":
            df = pd.read_excel(label_file)
        elif suffix == ".jsonl":
            rows = []
            with open(label_file) as f:
                for line in f:
                    rows.append(json.loads(line))
            df = pd.DataFrame(rows)
        else:
            continue

        print(f"\n  Inspecting {label_file.name}:")
        print(f"    Shape: {df.shape}")
        print(f"    Columns: {list(df.columns)}")
        print(f"    First row: {dict(df.iloc[0]) if len(df) > 0 else 'empty'}")

        # Find label column
        cols_lower = {c.lower(): c for c in df.columns}
        label_col = None
        for candidate in ["label", "classification", "class", "category", "type", "noisy"]:
            if candidate in cols_lower:
                label_col = cols_lower[candidate]
                break

        if label_col is None:
            # Check if any column has valid/noisy values
            for col in df.columns:
                vals = df[col].astype(str).str.lower().unique()
                if any(v in vals for v in ["valid", "noisy", "clean", "useful"]):
                    label_col = col
                    break

        if label_col is None:
            print(f"    Could not find label column, skipping")
            continue

        print(f"    Using label column: '{label_col}'")
        print(f"    Value counts: {dict(df[label_col].value_counts())}")

        # Find index column
        idx_col = None
        for candidate in ["index", "id", "idx", "example_id", "sample_id", "line", "row"]:
            if candidate in cols_lower:
                idx_col = cols_lower[candidate]
                break

        # Determine valid rows
        valid_mask = df[label_col].astype(str).str.lower().isin(
            ["valid", "useful", "clean", "good", "1", "true"]
        )

        if idx_col:
            new_valid = set(df.loc[valid_mask, idx_col].astype(int).tolist())
        else:
            new_valid = set(df.loc[valid_mask].index.tolist())

        valid_indices.update(new_valid)
        print(f"    Valid: {len(new_valid):,} / {len(df):,}")

    return valid_indices


def filter_dataset(
    raw_dir: Path = DEFAULT_RAW,
    labels_dir: Path = DEFAULT_LABELS,
    out_dir: Path = DEFAULT_OUT,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Find and load raw data
    print("Looking for CodeReviewer data files...")
    print(f"  Searching in: {raw_dir}")

    # List everything so we can debug
    all_files = sorted(raw_dir.rglob("*"))
    print(f"  Total files found: {len([f for f in all_files if f.is_file()])}")
    for f in all_files:
        if f.is_file():
            print(f"    {f.relative_to(raw_dir)} ({f.stat().st_size:,} bytes)")

    pairs = find_paired_files(raw_dir)
    if not pairs:
        print("\nERROR: Could not find paired source/target files.")
        print("Expected files like: train.source/train.target or train.diff/train.msg")
        print("Check the extracted contents above and update filter.py if needed.")
        raise SystemExit(1)

    print(f"\nFound splits: {list(pairs.keys())}")

    # Step 2: Load labels
    print("\nLoading cleaned labels...")
    valid_indices = load_valid_indices(labels_dir)

    # Step 3: Filter and save
    for split_name, (src_path, tgt_path) in pairs.items():
        print(f"\nProcessing '{split_name}' split...")
        examples = load_paired_lines(src_path, tgt_path)
        print(f"  Loaded {len(examples):,} examples")

        # Only filter training data (labels are for training set only)
        if split_name == "train" and valid_indices is not None:
            filtered = [ex for i, ex in enumerate(examples) if i in valid_indices]
            print(f"  After filtering: {len(filtered):,} / {len(examples):,} "
                  f"({len(filtered)/len(examples)*100:.1f}%)")
        else:
            filtered = examples
            if split_name == "train" and valid_indices is None:
                print("  WARNING: No labels found, keeping all training examples")

        out_path = out_dir / f"{split_name}.jsonl"
        with open(out_path, "w") as f:
            for ex in filtered:
                f.write(json.dumps(ex) + "\n")
        print(f"  Saved to {out_path}")

    print("\nDone!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter CodeReviewer to valid examples")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    filter_dataset(args.raw_dir, args.labels_dir, args.out_dir)
