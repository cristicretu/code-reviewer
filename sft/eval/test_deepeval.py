"""Smoke test: verify deepeval metrics work with the Qwen3.5-14B Ollama judge.

Creates synthetic prediction examples and scores them to confirm:
  1. Deepeval is installed and configured correctly
  2. The Ollama judge (qwen3.5:14b) responds with valid JSON
  3. All 4 metrics produce scores in [0, 1] range

Usage:
    # First ensure Ollama is running with the judge:
    ollama pull qwen3.5:14b
    ollama serve

    # Then run:
    deepeval set-ollama --model=qwen3.5:14b
    python -m sft.eval.test_deepeval
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("LOCAL_MODEL_NAME", "qwen3:14b")
os.environ.setdefault("LOCAL_MODEL_API_KEY", "ollama")
os.environ.setdefault("LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")

from deepeval.metrics import GEval, AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase, SingleTurnParams


CORRECTNESS_CRITERIA = (
    "Evaluate whether the code review comment correctly identifies a real "
    "issue in the code diff. Score 1.0 if the comment points to a real issue, "
    "0.0 if it hallucinates or is factually wrong."
)

SPECIFICITY_CRITERIA = (
    "Evaluate whether the review comment is specific about what to change. "
    "Score 1.0 if it references exact code, 0.0 if vague or generic."
)

ACTIONABILITY_CRITERIA = (
    "Evaluate whether the review provides a concrete fix suggestion. "
    "Score 1.0 if actionable, 0.0 if only states a problem."
)

SYNTHETIC_DIFF = """\
def get_user(db, user_id):
-   return db.query("SELECT * FROM users WHERE id = ?", [user_id])
+   return db.query("SELECT * FROM users WHERE id = " + user_id)
"""

GOOD_REVIEW = (
    "SQL injection vulnerability at line 1: the query concatenates `user_id` "
    "directly into the SQL string instead of using parameterized binding. "
    "Use the original parameterized form: "
    "`db.query('SELECT * FROM users WHERE id = ?', [user_id])`"
)

BAD_REVIEW = (
    "This code could be improved. Consider using better coding practices. "
    "The function name is unclear and there may be edge cases."
)

REFERENCE_REVIEW = (
    "Possible SQL injection: the change removes parameterized query binding "
    "and concatenates user_id directly into SQL. This allows arbitrary SQL "
    "execution if user_id is attacker-controlled. Revert to the original "
    "parameterized form using '?' placeholders."
)

TEST_CASES = [
    {
        "label": "good review",
        "diff": SYNTHETIC_DIFF,
        "prediction": GOOD_REVIEW,
        "reference": REFERENCE_REVIEW,
    },
    {
        "label": "bad review (vague)",
        "diff": SYNTHETIC_DIFF,
        "prediction": BAD_REVIEW,
        "reference": REFERENCE_REVIEW,
    },
]


def main() -> int:
    print("Deepeval smoke test")
    print("===================\n")

    metrics = {
        "correctness": GEval(
            name="Correctness",
            criteria=CORRECTNESS_CRITERIA,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            verbose_mode=True,
        ),
        "specificity": GEval(
            name="Specificity",
            criteria=SPECIFICITY_CRITERIA,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
            verbose_mode=True,
        ),
        "actionability": GEval(
            name="Actionability",
            criteria=ACTIONABILITY_CRITERIA,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
            verbose_mode=True,
        ),
        "answer_relevancy": AnswerRelevancyMetric(verbose_mode=True),
    }

    all_passed = True

    for tc_def in TEST_CASES:
        label = tc_def["label"]
        print(f"\n--- {label} ---")
        tc = LLMTestCase(
            input=tc_def["diff"],
            actual_output=tc_def["prediction"],
            expected_output=tc_def["reference"],
        )

        for name, metric in metrics.items():
            try:
                metric.measure(tc)
                score = metric.score
                reason = getattr(metric, "reason", "no reason")
                in_range = 0.0 <= score <= 1.0
                status = "OK" if in_range else "INVALID"
                if not in_range:
                    all_passed = False
                print(f"  {name}: {score:.3f} [{status}]  {reason}")
            except Exception as e:
                print(f"  {name}: FAILED - {e}")
                all_passed = False

    print(f"\n{'='*30}")
    if all_passed:
        print("ALL CHECKS PASSED - deepeval + Qwen judge wired correctly")
    else:
        print("SOME CHECKS FAILED - see errors above")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
