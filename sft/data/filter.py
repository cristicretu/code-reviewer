"""Cross-reference CodeReviewer with cleaned labels to keep only valid examples.

This script:
1. Reads the raw CodeReviewer Comment_Generation JSONL files
2. Reads the RQ1_Noisy_Classification labels
3. Keeps only examples labeled as "valid"
4. Outputs filtered data as JSONL

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


def find_jsonl_files(raw_dir: Path) -> dict[str, Path]:
    """Find JSONL data files and map to split names."""
    splits = {}
    for f in sorted(raw_dir.rglob("*.jsonl")):
        name = f.stem.lower()
        if "train" in name:
            splits["train"] = f
        elif "valid" in name:
            splits["valid"] = f
        elif "test" in name:
            splits["test"] = f
    return splits


def load_valid_indices(labels_dir: Path) -> set[int] | None:
    """Load valid example indices from RQ1_Noisy_Classification.

    Returns a set of indices (0-based line numbers) that are labeled valid,
    or None if no labels are found.
    """
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
            with open(label_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            df = pd.DataFrame(rows)
        else:
            continue

        print(f"\n  Inspecting {label_file.name}:")
        print(f"    Shape: {df.shape}")
        print(f"    Columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"    First row: {dict(df.iloc[0])}")

        # Find label column
        cols_lower = {c.lower(): c for c in df.columns}
        label_col = None
        for candidate in ["quality_label", "label", "classification", "class", "category", "type", "noisy", "pred_quality_label"]:
            if candidate in cols_lower:
                label_col = cols_lower[candidate]
                break

        if label_col is None:
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
        for candidate in ["idx", "index", "id", "example_id", "sample_id", "line", "row"]:
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

    # Step 1: Find JSONL files
    print("Looking for CodeReviewer data files...")
    splits = find_jsonl_files(raw_dir)

    if not splits:
        print(f"\nERROR: No JSONL files found in {raw_dir}")
        print("Contents:")
        for f in sorted(raw_dir.rglob("*")):
            if f.is_file():
                print(f"  {f.relative_to(raw_dir)}")
        raise SystemExit(1)

    print(f"Found splits: {list(splits.keys())}")
    for name, path in splits.items():
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  {name}: {path} ({size_mb:.0f} MB)")

    # Peek at schema
    with open(next(iter(splits.values()))) as f:
        sample = json.loads(f.readline())
    print(f"\nData schema: {list(sample.keys())}")
    for k, v in sample.items():
        print(f"  {k}: {str(v)[:100]}...")

    # Step 2: Load labels
    print("\nLoading cleaned labels...")
    valid_indices = load_valid_indices(labels_dir)

    # Step 3: Filter and save each split
    for split_name, split_path in splits.items():
        print(f"\nProcessing '{split_name}'...")

        # Count lines first
        with open(split_path) as f:
            total = sum(1 for _ in f)
        print(f"  Total examples: {total:,}")

        # Filter
        should_filter = split_name == "train" and valid_indices is not None
        kept = 0

        out_path = out_dir / f"{split_name}.jsonl"
        with open(split_path) as fin, open(out_path, "w") as fout:
            for i, line in enumerate(tqdm(fin, total=total, desc=f"  Filtering {split_name}")):
                if should_filter and i not in valid_indices:
                    continue
                fout.write(line)
                kept += 1

        if should_filter:
            print(f"  Kept {kept:,} / {total:,} ({kept/total*100:.1f}%)")
        else:
            print(f"  Copied {kept:,} examples (no filtering for {split_name})")
        print(f"  -> {out_path}")

    print("\nDone!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter CodeReviewer to valid examples")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    filter_dataset(args.raw_dir, args.labels_dir, args.out_dir)
