"""OOD-specific metrics: bug detection rate and false positive rate.

These leverage the structured `bugs` field in 100-syntetic.txt rather than
relying on reference-text similarity, which gives a stronger eval signal.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from sft.eval.defect_metrics import extract_identifiers


_ISSUE_KEYWORDS = re.compile(
    r"\b(bug|issue|error|problem|vulnerability|security|incorrect|wrong|missing|"
    r"unsafe|broken|fail|crash|leak|race|deadlock|overflow|injection|null|undefined)\b",
    re.IGNORECASE,
)
_LGTM_KEYWORDS = re.compile(
    r"\b(lgtm|looks good|no issues|no bugs|no problems|looks correct|"
    r"no concerns|clean|well-written)\b",
    re.IGNORECASE,
)


def _bug_keywords(bug: dict) -> set[str]:
    """Extract searchable keywords from a bug entry."""
    words: set[str] = set()
    # Category: "sql-injection" → {"sql", "injection"}
    for part in re.split(r"[-_]", bug.get("category", "")):
        if len(part) > 2:
            words.add(part.lower())
    # Description identifiers (variable names, function names)
    words.update(
        w.lower() for w in extract_identifiers(bug.get("description", ""))
        if len(w) > 3
    )
    return words


def compute_bug_detection_rate(
    predictions: list[str], bug_lists: list[list[dict]]
) -> dict:
    """Fraction of planted bugs whose keywords appear in the prediction.

    Also reports example_detection_rate: fraction of buggy examples where
    at least one bug was caught.
    """
    total_bugs = 0
    detected_bugs = 0
    examples_with_any_hit = 0

    for pred, bugs in zip(predictions, bug_lists):
        if not bugs:
            continue
        pred_lower = pred.lower()
        example_hit = False
        for bug in bugs:
            total_bugs += 1
            keywords = _bug_keywords(bug)
            if any(kw in pred_lower for kw in keywords):
                detected_bugs += 1
                example_hit = True
        if example_hit:
            examples_with_any_hit += 1

    n_buggy = sum(1 for bugs in bug_lists if bugs)
    return {
        "bug_detection_rate": round(detected_bugs / total_bugs, 4) if total_bugs else 0.0,
        "example_detection_rate": round(examples_with_any_hit / n_buggy, 4) if n_buggy else 0.0,
    }


def compute_false_positive_rate(
    predictions: list[str], bug_lists: list[list[dict]]
) -> float:
    """For clean examples (no planted bugs), fraction where the model raises an alarm.

    False positive = prediction raises issue keywords without LGTM acknowledgement.
    """
    clean_total = 0
    fp_count = 0

    for pred, bugs in zip(predictions, bug_lists):
        if bugs:
            continue
        clean_total += 1
        if _ISSUE_KEYWORDS.search(pred) and not _LGTM_KEYWORDS.search(pred):
            fp_count += 1

    return round(fp_count / clean_total, 4) if clean_total else 0.0
