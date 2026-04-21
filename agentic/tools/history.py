from smolagents import Tool
import subprocess
import os

class CheckHistoryTool(Tool):
    name = "check_history"
    description = "git blame + log for the touched lines"
    inputs = {
        "path": {"type": "string", "description": "filepath"},
        "line_range": {"type": "string", "description": "line range like '10,20'", "nullable": True}
    }
    output_type = "string"

    def forward(self, path: str, line_range: str = None) -> str:
        try:
            cmd = ["git", "blame"]
            if line_range:
                cmd.extend(["-L", line_range])
            cmd.append(path)
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout or result.stderr
        except Exception as e:
            return str(e)

class GetPrMetadataTool(Tool):
    name = "get_pr_metadata"
    description = "title, description, linked issue, author, CI status"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        try:
            result = subprocess.run(["git", "log", "-1"], capture_output=True, text=True)
            return result.stdout or "No metadata found"
        except Exception as e:
            return str(e)

class GetTeamConventionsTool(Tool):
    name = "get_team_conventions"
    description = "retrieve conventions"
    inputs = {
        "topic": {"type": "string", "description": "topic name", "nullable": True}
    }
    output_type = "string"

    def forward(self, topic: str = None) -> str:
        output = []
        for file_name in [".cursorrules", ".github/CONTRIBUTING.md", "CONTRIBUTING.md"]:
            if os.path.exists(file_name):
                with open(file_name, "r", encoding="utf-8") as f:
                    output.append(f.read())
        return "\n".join(output) if output else "No conventions found"
