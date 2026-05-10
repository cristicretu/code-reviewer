"""Hallucination and defect-overlap metrics for code review eval.

No LLM needed — fast regex/token-based, runs on M1 Pro in seconds.

Metrics:
    hallucination_rate: fraction of predictions referencing entities
        (variable names, function names) NOT present in the diff.
    defect_precision: how many predicted issues overlap with the reference?
    defect_recall: how many reference issues are covered by the prediction?
    defect_f1: harmonic mean of precision and recall.
"""

from __future__ import annotations

import re
from collections import Counter


_IDENTIFIER_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b")

_STOP_WORDS = {
    "the", "and", "for", "that", "this", "with", "from", "should", "would",
    "could", "code", "line", "lines", "file", "change", "changes", "function",
    "diff", "issue", "issues", "review", "comment", "add", "use", "used",
    "using", "can", "not", "but", "also", "has", "have", "been", "will",
    "one", "two", "new", "you", "are", "was", "does", "here", "need",
    "needs", "make", "same", "just", "only", "then", "more", "like",
    "when", "what", "how", "why", "where", "some", "any", "all",
    "about", "into", "over", "your", "its", "it", "be", "or",
    "get", "set", "see", "we", "do", "if", "no", "on", "in", "to",
    "at", "by", "of", "is", "as", "an", "so", "up", "out",
    "very", "too", "much", "many", "may", "now", "way",
}


def extract_identifiers(text: str) -> set[str]:
    ids = set()
    for match in _IDENTIFIER_RE.finditer(text):
        w = match.group().lower()
        if w not in _STOP_WORDS and len(w) > 2:
            ids.add(w)
    return ids


def compute_hallucination_rate(predictions: list[str], diffs: list[str]) -> float:
    """Fraction of predictions that reference entities not in the diff."""
    hallucinated = 0
    total = 0
    for pred, diff in zip(predictions, diffs):
        pred_ids = extract_identifiers(pred)
        diff_ids = extract_identifiers(diff)
        if not pred_ids:
            continue
        total += 1
        alien = pred_ids - diff_ids
        if len(alien) > len(pred_ids) * 0.3:  # >30% of identifiers not in diff
            hallucinated += 1
    return hallucinated / total if total else 0.0


def compute_defect_f1(predictions: list[str], references: list[str]) -> dict:
    """Approximate defect precision/recall/F1 via keyword overlap with reference."""
    precisions = []
    recalls = []

    for pred, ref in zip(predictions, references):
        pred_ids = extract_identifiers(pred)
        ref_ids = extract_identifiers(ref)

        if not ref_ids:
            continue

        overlap = pred_ids & ref_ids

        precision = len(overlap) / len(pred_ids) if pred_ids else 0.0
        recall = len(overlap) / len(ref_ids) if ref_ids else 0.0
        precisions.append(precision)
        recalls.append(recall)

    avg_precision = sum(precisions) / len(precisions) if precisions else 0.0
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    f1 = (
        2 * avg_precision * avg_recall / (avg_precision + avg_recall)
        if (avg_precision + avg_recall) > 0
        else 0.0
    )

    return {
        "defect_precision": round(avg_precision, 4),
        "defect_recall": round(avg_recall, 4),
        "defect_f1": round(f1, 4),
    }
