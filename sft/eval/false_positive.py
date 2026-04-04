"""False positive rate evaluation on clean diffs.

Tests whether the model hallucinates issues on diffs that have no problems.
A good model should output something like "LGTM" or a minimal/no-issue response.

Usage:
    python -m sft.eval.false_positive --model outputs/sft/final --n 100
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


# Keywords that indicate the model found no issues (good on clean diffs)
LGTM_PATTERNS = [
    r"\blgtm\b",
    r"\blooks good\b",
    r"\bno issues?\b",
    r"\bapprove\b",
    r"\bclean\b",
    r"\bcorrect\b",
    r"\bwell.?written\b",
    r"\bnothing to\b",
]

# Keywords that indicate the model found a (false positive) issue
ISSUE_PATTERNS = [
    r"\bbug\b",
    r"\bfix\b",
    r"\berror\b",
    r"\bvulnerab",
    r"\bshould\b",
    r"\bconsider\b",
    r"\binstead\b",
    r"\bmissing\b",
    r"\bwrong\b",
    r"\bincorrect\b",
]


def classify_response(text: str) -> str:
    """Classify a model response as 'lgtm' (no issues) or 'flagged' (found issues)."""
    text_lower = text.lower()

    lgtm_score = sum(1 for p in LGTM_PATTERNS if re.search(p, text_lower))
    issue_score = sum(1 for p in ISSUE_PATTERNS if re.search(p, text_lower))

    # Short responses are more likely to be LGTM
    if len(text.split()) < 10 and issue_score == 0:
        return "lgtm"

    if lgtm_score > issue_score:
        return "lgtm"
    elif issue_score > 0:
        return "flagged"
    else:
        return "ambiguous"


def generate_on_clean_diffs(
    model_path: str,
    clean_diffs: list[str],
    max_new_tokens: int = 256,
) -> list[str]:
    """Generate model responses for clean diffs."""
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_path,
        max_seq_length=4096,
        dtype=None,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)

    system_prompt = (
        "You are an expert code reviewer. Given a code diff, provide a concise, "
        "actionable review comment. If the code looks correct, say so briefly."
    )

    responses = []
    for i, diff in enumerate(clean_diffs):
        print(f"  Generating {i+1}/{len(clean_diffs)}...", end="\r")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Review this code change:\n\n```diff\n{diff}\n```"},
        ]
        inputs = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)

        outputs = model.generate(
            input_ids=inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            do_sample=True,
        )
        response = tokenizer.decode(outputs[0][inputs.shape[1]:], skip_special_tokens=True)
        responses.append(response)

    print()
    return responses


def evaluate_false_positives(responses: list[str]) -> dict:
    """Compute false positive rate from model responses on clean diffs."""
    classifications = [classify_response(r) for r in responses]

    n = len(classifications)
    n_lgtm = classifications.count("lgtm")
    n_flagged = classifications.count("flagged")
    n_ambiguous = classifications.count("ambiguous")

    return {
        "total": n,
        "lgtm": n_lgtm,
        "flagged_fp": n_flagged,
        "ambiguous": n_ambiguous,
        "false_positive_rate": n_flagged / n if n > 0 else 0.0,
        "classifications": classifications,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="False positive rate evaluation")
    parser.add_argument("--model", required=True, help="Path to model/adapter")
    parser.add_argument("--clean-diffs", type=Path, default=None,
                        help="JSONL with clean diffs (one per line, 'diff' field)")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("outputs/fp_results.json"))
    args = parser.parse_args()

    # Load clean diffs
    if args.clean_diffs and args.clean_diffs.exists():
        diffs = []
        with open(args.clean_diffs) as f:
            for line in f:
                diffs.append(json.loads(line)["diff"])
        diffs = diffs[:args.n]
    else:
        print("No clean diffs file provided.")
        print("TODO: Create a set of clean diffs for FP evaluation.")
        print("For now, you can manually curate ~100 diffs that are known-good.")
        raise SystemExit(1)

    print(f"Generating responses for {len(diffs)} clean diffs...")
    responses = generate_on_clean_diffs(args.model, diffs)

    results = evaluate_false_positives(responses)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nFalse Positive Results:")
    print(f"  LGTM (correct): {results['lgtm']}/{results['total']}")
    print(f"  Flagged (FP):   {results['flagged_fp']}/{results['total']}")
    print(f"  Ambiguous:      {results['ambiguous']}/{results['total']}")
    print(f"  FP Rate:        {results['false_positive_rate']:.1%}")
    print(f"Saved to {args.output}")
