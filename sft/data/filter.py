"""Filter CodeReviewer training data to remove noisy/low-quality comments.

Heuristic filtering removes obviously non-actionable comments:
- Too short (<10 chars)
- Generic responses ("done", "ok", "nit", "fixed", "+1", etc.)
- Auto-generated bot comments
- Pure formatting/whitespace comments

Usage:
    python -m sft.data.filter [--raw-dir data/raw] [--out-dir data/processed]
"""

import argparse
import json
import re
from pathlib import Path

from tqdm import tqdm


DEFAULT_RAW = Path("data/raw")
DEFAULT_OUT = Path("data/processed")

# Comments that match these exactly (case-insensitive) are noisy
NOISY_EXACT = {
    "done", "done.", "ok", "ok.", "okay", "fixed", "fixed.", "ack",
    "nit", "nit.", "nitpick", "+1", "-1", "lgtm", "lgtm.",
    "thanks", "thanks.", "thanks!", "thank you", "ty",
    "yes", "no", "yeah", "yep", "nope", "sure", "agreed",
    "same here", "same", "ditto", "this", "^", "see above",
    "please fix", "please update", "please change",
    "n/a", "na", "tbd", "todo", "wip",
    "acknowledged", "resolved", "addressed",
}

# Comments matching these patterns are noisy
NOISY_PATTERNS = [
    r"^\.+$",                          # just dots
    r"^\?+$",                          # just question marks
    r"^!+$",                           # just exclamation marks
    r"^\s*$",                          # empty/whitespace
    r"^https?://\S+$",                 # bare URL with nothing else
    r"^see #?\d+$",                    # just "see #123"
    r"^duplicate of #?\d+$",           # just "duplicate of #123"
]

NOISY_RE = [re.compile(p, re.IGNORECASE) for p in NOISY_PATTERNS]


def is_noisy(msg: str) -> bool:
    """Return True if the comment is likely noisy/non-actionable."""
    stripped = msg.strip()

    # Too short
    if len(stripped) < 10:
        return True

    # Exact match against known noisy comments
    if stripped.lower().rstrip(".!?") in NOISY_EXACT:
        return True

    # Pattern match
    for pattern in NOISY_RE:
        if pattern.match(stripped):
            return True

    return False


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


def filter_dataset(
    raw_dir: Path = DEFAULT_RAW,
    out_dir: Path = DEFAULT_OUT,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    splits = find_jsonl_files(raw_dir)
    if not splits:
        print(f"ERROR: No JSONL files found in {raw_dir}")
        raise SystemExit(1)

    print(f"Found splits: {list(splits.keys())}")

    # Peek at schema
    with open(next(iter(splits.values()))) as f:
        sample = json.loads(f.readline())
    print(f"Schema: {list(sample.keys())}")

    for split_name, split_path in splits.items():
        print(f"\nProcessing '{split_name}'...")

        with open(split_path) as f:
            total = sum(1 for _ in f)

        kept = 0
        filtered_out = 0
        out_path = out_dir / f"{split_name}.jsonl"

        with open(split_path) as fin, open(out_path, "w") as fout:
            for line in tqdm(fin, total=total, desc=f"  {split_name}"):
                ex = json.loads(line)
                msg = ex.get("msg", "")

                # Only filter training data
                if split_name == "train" and is_noisy(msg):
                    filtered_out += 1
                    continue

                fout.write(line)
                kept += 1

        print(f"  Kept: {kept:,} / {total:,} ({kept/total*100:.1f}%)")
        if filtered_out:
            print(f"  Removed: {filtered_out:,} noisy comments")
        print(f"  -> {out_path}")

    print("\nDone!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter noisy comments from CodeReviewer")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    filter_dataset(args.raw_dir, args.out_dir)
