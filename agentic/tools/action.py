from smolagents import Tool
import json

class PostCommentTool(Tool):
    name = "post_comment"
    description = "post comment matching structured-output schema"
    inputs = {
        "file": {"type": "string", "description": "file"},
        "line": {"type": "integer", "description": "line num"},
        "severity": {"type": "string", "description": "severity"},
        "category": {"type": "string", "description": "category"},
        "suggestion": {"type": "string", "description": "suggestion"}
    }
    output_type = "string"

    def forward(self, file: str, line: int, severity: str, category: str, suggestion: str) -> str:
        try:
            with open("review_output.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "action": "post_comment",
                    "file": file,
                    "line": line,
                    "severity": severity,
                    "category": category,
                    "suggestion": suggestion
                }) + "\n")
            return "Comment posted"
        except Exception as e:
            return str(e)

class RequestChangesTool(Tool):
    name = "request_changes"
    description = "final verdict request changes"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        try:
            with open("review_output.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"action": "request_changes"}) + "\n")
            return "Changes requested"
        except Exception as e:
            return str(e)

class ApproveTool(Tool):
    name = "approve"
    description = "final verdict approve"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        try:
            with open("review_output.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"action": "approve"}) + "\n")
            return "Approved"
        except Exception as e:
            return str(e)

class CommentOnlyTool(Tool):
    name = "comment_only"
    description = "final verdict comment only"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        try:
            with open("review_output.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"action": "comment_only"}) + "\n")
            return "Comment only recorded"
        except Exception as e:
            return str(e)

class ProposePatchTool(Tool):
    name = "propose_patch"
    description = "propose patch diff"
    inputs = {
        "file": {"type": "string", "description": "file path"},
        "diff": {"type": "string", "description": "patch diff"}
    }
    output_type = "string"

    def forward(self, file: str, diff: str) -> str:
        try:
            with open("review_output.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "action": "propose_patch",
                    "file": file,
                    "diff": diff
                }) + "\n")
            return "Patch proposed"
        except Exception as e:
            return str(e)
