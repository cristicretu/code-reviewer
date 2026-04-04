"""Automated evaluation metrics for code review generation.

Metrics:
    - CodeBERTScore: semantic similarity using CodeBERT embeddings (~0.52 Kendall-tau)
    - ChrF: character n-gram F-score (~0.47 Kendall-tau)
    - ROUGE-L: longest common subsequence overlap

BLEU is intentionally omitted (scores <10 on review comments, uninformative).

Usage:
    from sft.eval.metrics import compute_metrics
    results = compute_metrics(predictions, references)
"""

from __future__ import annotations

import sacrebleu
from rouge_score import rouge_scorer


def compute_chrf(predictions: list[str], references: list[str]) -> dict:
    """Compute ChrF score using sacrebleu."""
    chrf = sacrebleu.corpus_chrf(predictions, [references])
    return {"chrf": chrf.score}


def compute_rouge_l(predictions: list[str], references: list[str]) -> dict:
    """Compute ROUGE-L score."""
    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
    scores = []
    for pred, ref in zip(predictions, references):
        score = scorer.score(ref, pred)
        scores.append(score["rougeL"].fmeasure)
    return {"rouge_l": sum(scores) / len(scores) if scores else 0.0}


def compute_code_bert_score(
    predictions: list[str], references: list[str]
) -> dict:
    """Compute CodeBERTScore using the code_bert_score package.

    Falls back gracefully if code_bert_score is not installed.
    """
    try:
        from code_bert_score import score as cbs_score

        _, _, f1, _ = cbs_score(
            cands=predictions,
            refs=references,
            lang="en",  # review comments are natural language
        )
        return {"code_bert_score": f1.mean().item()}
    except ImportError:
        print("WARNING: code_bert_score not installed, skipping CodeBERTScore")
        print("  Install with: pip install code-bert-score")
        return {"code_bert_score": None}
    except Exception as e:
        print(f"WARNING: CodeBERTScore failed: {e}")
        return {"code_bert_score": None}


def compute_metrics(
    predictions: list[str], references: list[str]
) -> dict:
    """Compute all evaluation metrics.

    Args:
        predictions: Model-generated review comments.
        references: Ground-truth review comments.

    Returns:
        Dict with metric names as keys and scores as values.
    """
    results = {}
    results.update(compute_chrf(predictions, references))
    results.update(compute_rouge_l(predictions, references))
    results.update(compute_code_bert_score(predictions, references))
    return results
