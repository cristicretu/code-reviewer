import json
import os
from typing import Optional

from loguru import logger


class ReviewState:
    """Buffers inline comments + verdict during the agent run, then submits one batched review.

    Falls back to a JSONL dump on stdout when no GitHub client is configured (local dev).
    """

    VALID_VERDICTS = {"REQUEST_CHANGES", "APPROVE", "COMMENT"}

    def __init__(self):
        self.client = None
        self.repo: Optional[str] = None
        self.pr_number: Optional[int] = None
        self.commit_id: Optional[str] = None
        self.comments: list = []
        self.verdict: Optional[str] = None
        self.comment_budget: int = 10

    def configure(self, *, client, repo, pr_number, commit_id, comment_budget=10):
        self.client = client
        self.repo = repo
        self.pr_number = pr_number
        self.commit_id = commit_id
        self.comment_budget = comment_budget
        self.comments = []
        self.verdict = None

    def add_comment(self, file: str, line: int, body: str) -> bool:
        if len(self.comments) >= self.comment_budget:
            return False
        self.comments.append(
            {"path": file, "line": int(line), "side": "RIGHT", "body": body}
        )
        return True

    def set_verdict(self, verdict: str) -> bool:
        if verdict not in self.VALID_VERDICTS:
            return False
        self.verdict = verdict
        return True

    def _build_body(self) -> str:
        n = len(self.comments)
        if n == 0:
            return "No actionable issues found."
        return f"Automated review by code-reviewer agent: {n} finding(s)."

    def submit(self) -> Optional[dict]:
        verdict = self.verdict or "COMMENT"
        body = self._build_body()
        if self.client is None:
            output = {
                "verdict": verdict,
                "body": body,
                "comments": self.comments,
            }
            logger.info("No GitHub client configured; dumping review locally.")
            print(json.dumps(output, indent=2))
            try:
                with open("review_output.json", "w", encoding="utf-8") as f:
                    json.dump(output, f, indent=2)
            except Exception:
                pass
            return output

        logger.info(
            f"Submitting review to {self.repo}#{self.pr_number}: {verdict} with {len(self.comments)} comment(s)"
        )
        return self.client.submit_review(
            repo=self.repo,
            pr_number=self.pr_number,
            commit_id=self.commit_id,
            event=verdict,
            body=body,
            comments=self.comments,
        )


REVIEW_STATE = ReviewState()
