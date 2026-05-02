import json
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

    def is_finalized(self) -> bool:
        return self.verdict is not None

    def add_comment(self, file: str, line: int, body: str) -> str:
        """Returns one of: 'added' | 'duplicate' | 'budget_exhausted' | 'finalized'.

        Dedupe is by (file, line): a real reviewer wouldn't post two separate
        threads on the same line, and the model has a tendency to re-emit the
        same finding across consecutive steps.
        """
        if self.is_finalized():
            return "finalized"
        line_int = int(line)
        for existing in self.comments:
            if existing["path"] == file and existing["line"] == line_int:
                return "duplicate"
        if len(self.comments) >= self.comment_budget:
            return "budget_exhausted"
        self.comments.append(
            {"path": file, "line": line_int, "side": "RIGHT", "body": body}
        )
        return "added"

    def set_verdict(self, verdict: str) -> bool:
        """First-call-wins. Returns True if this call set the verdict, False if it was already set or invalid."""
        if verdict not in self.VALID_VERDICTS:
            return False
        if self.verdict is not None:
            return False
        self.verdict = verdict
        return True

    def _build_body(self) -> str:
        n = len(self.comments)
        if n == 0:
            return "No actionable issues found."
        return f"Automated review by code-reviewer agent: {n} finding(s)."

    def _format_comments_in_body(self) -> str:
        if not self.comments:
            return ""
        lines = ["## Inline findings"]
        for c in self.comments:
            lines.append(f"- **`{c['path']}:{c['line']}`** {c['body']}")
        return "\n".join(lines)

    def _dump_local(self, payload: dict) -> None:
        try:
            with open("review_output.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logger.info("Wrote review_output.json (will be uploaded as a workflow artifact).")
        except Exception as e:
            logger.warning(f"Could not write review_output.json: {e}")
        print(json.dumps(payload, indent=2))

    def submit(self) -> Optional[dict]:
        verdict = self.verdict or "COMMENT"
        body = self._build_body()
        payload = {"verdict": verdict, "body": body, "comments": self.comments}

        if self.client is None:
            logger.info("No GitHub client configured; dumping review locally.")
            self._dump_local(payload)
            return payload

        try:
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
        except Exception as e:
            logger.warning(f"Primary submission failed ({e}); folding comments into review body and retrying.")

        try:
            fallback_body = body + "\n\n---\n\n" + self._format_comments_in_body()
            return self.client.submit_review(
                repo=self.repo,
                pr_number=self.pr_number,
                commit_id=self.commit_id,
                event=verdict,
                body=fallback_body,
                comments=[],
            )
        except Exception as e:
            logger.error(f"Fallback submission also failed ({e}); dumping locally.")
            self._dump_local(payload)
            return None


REVIEW_STATE = ReviewState()
