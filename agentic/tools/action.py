from smolagents import Tool

from agentic.review_state import REVIEW_STATE


class PostCommentTool(Tool):
    name = "post_comment"
    description = (
        "Buffer an inline review comment on a specific file:line. "
        "Comments are submitted together as one review when the agent picks a final verdict."
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
        ok = REVIEW_STATE.add_comment(file, line, body)
        if not ok:
            return f"Comment budget exhausted ({len(REVIEW_STATE.comments)} comments buffered); pick a final verdict."
        return f"Comment buffered ({len(REVIEW_STATE.comments)}/{REVIEW_STATE.comment_budget})."


class RequestChangesTool(Tool):
    name = "request_changes"
    description = "Final verdict: request changes. Submits all buffered comments as one review."
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        REVIEW_STATE.set_verdict("REQUEST_CHANGES")
        return "Verdict set: REQUEST_CHANGES."


class ApproveTool(Tool):
    name = "approve"
    description = "Final verdict: approve. Submits any buffered comments as one approving review."
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        REVIEW_STATE.set_verdict("APPROVE")
        return "Verdict set: APPROVE."


class CommentOnlyTool(Tool):
    name = "comment_only"
    description = "Final verdict: comment-only review (no approval gate)."
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        REVIEW_STATE.set_verdict("COMMENT")
        return "Verdict set: COMMENT."


class ProposePatchTool(Tool):
    name = "propose_patch"
    description = (
        "Attach a GitHub-style suggested change (single-line or block) at a specific file:line. "
        "Buffered with the rest of the review."
    )
    inputs = {
        "file": {"type": "string", "description": "file path relative to the repo root"},
        "line": {"type": "integer", "description": "line number on the new (RIGHT) side of the diff"},
        "diff": {"type": "string", "description": "replacement text for the suggestion block"},
    }
    output_type = "string"

    def forward(self, file: str, line: int, diff: str) -> str:
        body = "Suggested change:\n```suggestion\n" + diff + "\n```"
        ok = REVIEW_STATE.add_comment(file, line, body)
        if not ok:
            return "Comment budget exhausted; pick a final verdict."
        return "Patch attached."
