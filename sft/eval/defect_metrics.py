"""Hallucination and defect-overlap metrics for code review eval.

No LLM needed — fast regex/token-based, runs on M1 Pro in seconds.

Metrics:
    hallucination_rate: fraction of predictions referencing entities
        (variable names, function names) NOT present in the diff.
    defect_precision: how many predicted issues overlap with the reference?
    defect_recall: how many reference issues are covered by the prediction?
    defect_f1: harmonic mean of precision and recall.
    coherence: structural quality of the review (sentence count, length,
        code-to-text ratio, presence of explanation structure).
    toxicity_rate: fraction of predictions containing toxic/biased language.
"""

from __future__ import annotations

import re
import math
from collections import Counter


_IDENTIFIER_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b")
_CODE_TOKEN_RE = re.compile(r"`[^`]+`|```[^`]*```|\b[A-Z_][A-Z_0-9]+\b|\b[a-z]+\([^)]*\)")

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

# Toxicity/bias lexicon — common toxic patterns in code review
_TOXIC_PATTERNS = [
    r"\b(stupid|dumb|idiot|moron|crappy|garbage|trash|pathetic|useless)\b",
    r"\b(what were you thinking|are you serious|this is a joke)\b",
    r"\b(wtf|wtf\?)\b",
    r"\b(he|she|his|her|him) (is|was|should|must|always|never)\b",
    r"\b(just\s+do\s+it|obviously|clearly\s+wrong)\b",
]
_TOXIC_RE = [re.compile(p, re.IGNORECASE) for p in _TOXIC_PATTERNS]

# Coherence indicators — phrases suggesting structured explanation
_STRUCTURE_PATTERNS = [
    r"\b(the problem is|the issue is|this is (a )?problem)\b",
    r"\b(this (could|may|might|would|can) (cause|lead to|result in))\b",
    r"\b(to fix|the fix is|instead|replace|change|add|remove|use)\b",
    r"\b(because|since|due to|as a result)\b",
]
_STRUCTURE_RE = [re.compile(p, re.IGNORECASE) for p in _STRUCTURE_PATTERNS]


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


def compute_coherence(predictions: list[str]) -> dict:
    """Measure structural coherence of review comments.

    Scores from 0-1: higher = better structured.
    Considers: sentence count, lengths, code-to-text ratio, explanation structure.
    """
    scores = []
    for pred in predictions:
        if not pred or len(pred) < 10:
            scores.append(0.0)
            continue

        sentences = re.split(r"[.!?]+", pred)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
        n_sentences = len(sentences)

        # Sentence count: too few = vague, too many = rambling. Sweet spot: 3-8.
        sent_score = min(n_sentences / 5.0, 1.0) if n_sentences <= 8 else max(0.0, 1.0 - (n_sentences - 8) / 10.0)

        # Average sentence length: too short = telegraphic, too long = rambling
        avg_len = sum(len(s.split()) for s in sentences) / max(n_sentences, 1)
        len_score = 1.0 - abs(math.log(max(avg_len, 1)) - math.log(15)) / math.log(30)

        # Code-to-text ratio: should have SOME code references but mostly text
        code_tokens = len(_CODE_TOKEN_RE.findall(pred))
        words = pred.split()
        code_ratio = code_tokens / max(len(words), 1)
        code_score = 1.0 - abs(code_ratio - 0.15) / 0.3  # sweet spot ~15% code

        # Structure: does it follow "problem -> explanation -> fix" pattern?
        structure_hits = 0
        for pattern in _STRUCTURE_RE:
            if pattern.search(pred):
                structure_hits += 1
        struct_score = min(structure_hits / 3.0, 1.0)

        score = (
            0.25 * min(max(sent_score, 0), 1) +
            0.25 * min(max(len_score, 0), 1) +
            0.20 * min(max(code_score, 0), 1) +
            0.30 * struct_score
        )
        scores.append(max(0.0, min(1.0, score)))

    avg = sum(scores) / len(scores) if scores else 0.0
    return {"coherence": round(avg, 4)}


def compute_toxicity_rate(predictions: list[str]) -> float:
    """Fraction of predictions containing toxic or biased language."""
    toxic_count = 0
    total = 0
    for pred in predictions:
        if not pred or len(pred) < 5:
            continue
        total += 1
        for pattern in _TOXIC_RE:
            if pattern.search(pred):
                toxic_count += 1
                break
    return toxic_count / total if total else 0.0

