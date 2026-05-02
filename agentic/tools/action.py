from smolagents import Tool

from agentic.review_state import REVIEW_STATE


_FINALIZED_HINT = "Verdict already set ({}); call final_answer('done') to end the review."


class PostCommentTool(Tool):
    name = "post_comment"
    description = (
        "Buffer an inline review comment on a specific file:line. "
        "Comments are submitted together as one review when the agent picks a final verdict. "
        "Comments cannot be added after a verdict is set."
    )
    inputs = {
        "file": {"type": "string", "description": "file path relative to the repo root"},
        "line": {"type": "integer", "description": "line number on the new (RIGHT) side of the diff"},
        "severity": {"type": "string", "description": "critical | high | medium | low"},
        "category": {"type": "string", "description": "bug | security | logic | performance | style"},
        "suggestion": {"type": "string", "description": "explanation and suggested fix in markdown"},
    }
    output_type = "string"

    def forward(self, file: str, line: int, severity: str, category: str, suggestion: str) -> str:
        body = f"**[{severity}/{category}]** {suggestion}"
        status = REVIEW_STATE.add_comment(file, line, body)
        if status == "finalized":
            return _FINALIZED_HINT.format(REVIEW_STATE.verdict)
        if status == "duplicate":
            return f"Already buffered a comment on {file}:{line}; one comment per line. Move on or pick a verdict."
        if status == "budget_exhausted":
            return f"Comment budget exhausted ({len(REVIEW_STATE.comments)} buffered); pick a final verdict."
        return f"Comment buffered ({len(REVIEW_STATE.comments)}/{REVIEW_STATE.comment_budget})."


class _VerdictTool(Tool):
    """Shared logic for the three verdict tools. First-call-wins; later calls are ignored."""

    inputs = {}
    output_type = "string"
    _verdict: str = ""

    def forward(self) -> str:
        if REVIEW_STATE.is_finalized():
            return _FINALIZED_HINT.format(REVIEW_STATE.verdict)
        REVIEW_STATE.set_verdict(self._verdict)
        return f"Verdict set: {self._verdict}. Call final_answer('done') to end the review."


class RequestChangesTool(_VerdictTool):
    name = "request_changes"
    description = "Final verdict: request changes. Submits all buffered comments as one review. First-call-wins."
    _verdict = "REQUEST_CHANGES"


class ApproveTool(_VerdictTool):
    name = "approve"
    description = "Final verdict: approve. Submits any buffered comments as one approving review. First-call-wins."
    _verdict = "APPROVE"


class CommentOnlyTool(_VerdictTool):
    name = "comment_only"
    description = "Final verdict: comment-only review (no approval gate). First-call-wins."
    _verdict = "COMMENT"


class ProposePatchTool(Tool):
    name = "propose_patch"
    description = (
        "Attach a GitHub-style suggested change at a specific file:line. "
        "Buffered with the rest of the review. Cannot be added after a verdict is set."
    )
    inputs = {
        "file": {"type": "string", "description": "file path relative to the repo root"},
        "line": {"type": "integer", "description": "line number on the new (RIGHT) side of the diff"},
        "diff": {"type": "string", "description": "replacement text for the suggestion block"},
    }
    output_type = "string"

    def forward(self, file: str, line: int, diff: str) -> str:
        body = "Suggested change:\n```suggestion\n" + diff + "\n```"
        status = REVIEW_STATE.add_comment(file, line, body)
        if status == "finalized":
            return _FINALIZED_HINT.format(REVIEW_STATE.verdict)
        if status == "duplicate":
            return f"Already buffered a comment on {file}:{line}; one patch per line."
        if status == "budget_exhausted":
            return "Comment budget exhausted; pick a final verdict."
        return "Patch attached."
