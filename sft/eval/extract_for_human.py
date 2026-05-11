"""Extract examples for human evaluation.

Picks n examples from each model variant and saves them as a readable
markdown file for manual review.

Usage:
    python -m sft.eval.extract_for_human --n 20
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("outputs/eval/human_eval.md"))
    args = parser.parse_args()

    variants = [
        ("Base model (qwen3:8b)", "outputs/eval/predictions_base.jsonl"),
        ("SFT model", "outputs/eval/predictions_sft.jsonl"),
        ("RLHF model", "outputs/eval/predictions_rlhf.jsonl"),
    ]

    lines = [
        "# Human Evaluation",
        "",
        f"Review {args.n} examples per model. For each, mark:",
        "",
        "- **Correct**: Does the comment identify a real issue? (Y/N)",
        "- **Useful**: Is the suggestion helpful/actionable? (Y/N)",
        "- **Specific**: Does it reference exact code/locations? (Y/N)",
        "- **Hallucinated**: Does it mention things not in the diff? (Y/N)",
        "- **Too vague**: Is it generic and could apply to any diff? (Y/N)",
        "",
        "---",
        "",
    ]

    for model_name, pred_path in variants:
        path = Path(pred_path)
        if not path.exists():
            continue

        examples = []
        with open(path) as f:
            for line in f:
                examples.append(json.loads(line.strip()))

        random.seed(args.seed)
        sample = random.sample(examples, min(args.n, len(examples)))

        lines.append(f"## {model_name}")
        lines.append("")

        for i, ex in enumerate(sample):
            diff = ex["diff"][:500]
            pred = ex["prediction"][:500]
            ref = ex["reference"][:300]

            lines.append(f"### Example {i+1}")
            lines.append("")
            lines.append("**Diff:**")
            lines.append("```diff")
            lines.append(diff)
            lines.append("```")
            lines.append("")
            lines.append("**Prediction:**")
            lines.append(f"> {pred}")
            lines.append("")
            lines.append("**Reference (ground truth):**")
            lines.append(f"> {ref}")
            lines.append("")
            lines.append("**Human verdict:**")
            lines.append("- [ ] Correct  - [ ] Useful  - [ ] Specific  - [ ] Hallucinated  - [ ] Too vague")
            lines.append("")
            lines.append("---")
            lines.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        f.write("\n".join(lines))

    print(f"Extracted human eval template: {args.output}")
    print(f"Open and mark each example, then give the file to your tech lead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
