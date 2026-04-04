"""Convert filtered CodeReviewer data to chat-format SFT training data.

Reads:
    - data/processed/train.jsonl (filtered training data with {patch, msg} objects)

Writes:
    - data/processed/sft_train.jsonl (chat-format conversations)

Usage:
    python -m sft.data.preprocess [--in-dir data/processed] [--out-dir data/processed]
"""

import argparse
import json
from pathlib import Path

from tqdm import tqdm


DEFAULT_IN = Path("data/processed")
DEFAULT_OUT = Path("data/processed")

SYSTEM_PROMPT = """\
You are an expert code reviewer. Given a code diff, provide a concise, \
actionable review comment. Focus on:
- Bugs and logic errors
- Security vulnerabilities
- Performance issues
- Code style and best practices

Be specific: reference the exact code that needs changing and explain why. \
If the code looks correct, say so briefly."""


def normalize_diff(patch: str) -> str:
    """Clean up the CodeReviewer diff format.

    CodeReviewer uses a simplified format with <add>/<del> tags.
    Normalize to a more readable unified-diff-like format.
    """
    lines = []
    for line in patch.split("\n"):
        stripped = line.strip()
        if stripped.startswith("<add>"):
            lines.append("+ " + stripped[5:].strip())
        elif stripped.startswith("<del>"):
            lines.append("- " + stripped[5:].strip())
        else:
            lines.append("  " + stripped)
    return "\n".join(lines)


def format_example(example: dict) -> dict | None:
    """Convert a (patch, msg) pair to chat format.

    Returns None if the example should be skipped.
    """
    patch = example.get("patch", "").strip()
    msg = example.get("msg", "").strip()

    if not patch or not msg:
        return None

    # Skip extremely short or generic comments
    if len(msg) < 5:
        return None

    diff = normalize_diff(patch)

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this code change:\n\n```diff\n{diff}\n```"},
            {"role": "assistant", "content": msg},
        ]
    }


def preprocess(in_dir: Path = DEFAULT_IN, out_dir: Path = DEFAULT_OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Process all splits
    for split_name in ["train", "valid", "validation", "test", "dev"]:
        in_path = in_dir / f"{split_name}.jsonl"
        if not in_path.exists():
            continue

        out_path = out_dir / f"sft_{split_name}.jsonl"
        kept = 0
        skipped = 0

        with open(in_path) as fin, open(out_path, "w") as fout:
            for line in tqdm(fin, desc=f"Preprocessing {split_name}"):
                example = json.loads(line)
                formatted = format_example(example)
                if formatted:
                    fout.write(json.dumps(formatted) + "\n")
                    kept += 1
                else:
                    skipped += 1

        print(f"  {split_name}: {kept:,} kept, {skipped:,} skipped -> {out_path}")

    # Show a sample from training data
    train_path = out_dir / "sft_train.jsonl"
    if train_path.exists():
        with open(train_path) as f:
            sample = json.loads(f.readline())
        print("\n--- Sample ---")
        for msg in sample["messages"]:
            role = msg["role"].upper()
            content = msg["content"][:200]
            print(f"[{role}] {content}{'...' if len(msg['content']) > 200 else ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess to SFT chat format")
    parser.add_argument("--in-dir", type=Path, default=DEFAULT_IN)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    preprocess(args.in_dir, args.out_dir)
