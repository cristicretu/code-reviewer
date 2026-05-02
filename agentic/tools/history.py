import os
import subprocess

import requests
from smolagents import Tool


class CheckHistoryTool(Tool):
    name = "check_history"
    description = "git blame + log for the touched lines"
    inputs = {
        "path": {"type": "string", "description": "filepath"},
        "line_range": {"type": "string", "description": "line range like '10,20'", "nullable": True},
    }
    output_type = "string"

    def forward(self, path: str, line_range: str = None) -> str:
        try:
            cmd = ["git", "blame"]
            if line_range:
                cmd.extend(["-L", line_range])
            cmd.append(path)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout or result.stderr
        except Exception as e:
            return str(e)


class GetPrMetadataTool(Tool):
    name = "get_pr_metadata"
    description = "PR title, body, author, base/head refs, CI status (via GitHub API when available)"
    inputs = {}
    output_type = "string"

    def forward(self) -> str:
        repo = os.environ.get("REPO_ID") or os.environ.get("GITHUB_REPOSITORY")
        pr_number = os.environ.get("PR_NUMBER")
        token = os.environ.get("GITHUB_TOKEN")
        if repo and pr_number and token:
            try:
                r = requests.get(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    timeout=30,
                )
                r.raise_for_status()
                pr = r.json()
                lines = [
                    f"title: {pr.get('title')}",
                    f"author: @{pr.get('user', {}).get('login')}",
                    f"state: {pr.get('state')}  draft: {pr.get('draft')}",
                    f"base: {pr.get('base', {}).get('ref')} <- head: {pr.get('head', {}).get('ref')}",
                    f"head_sha: {pr.get('head', {}).get('sha')}",
                    f"changed_files: {pr.get('changed_files')}  +{pr.get('additions')} / -{pr.get('deletions')}",
                    "",
                    "body:",
                    pr.get("body") or "(no description)",
                ]
                return "\n".join(lines)
            except Exception as e:
                return f"GitHub API lookup failed ({e}); falling back to git log."
        try:
            result = subprocess.run(["git", "log", "-1"], capture_output=True, text=True, timeout=10)
            return result.stdout or "No metadata found"
        except Exception as e:
            return str(e)


class GetTeamConventionsTool(Tool):
    name = "get_team_conventions"
    description = "retrieve conventions"
    inputs = {
        "topic": {"type": "string", "description": "topic name", "nullable": True},
    }
    output_type = "string"

    def forward(self, topic: str = None) -> str:
        output = []
        for file_name in [".cursorrules", ".github/CONTRIBUTING.md", "CONTRIBUTING.md", "CLAUDE.md"]:
            if os.path.exists(file_name):
                with open(file_name, "r", encoding="utf-8") as f:
                    output.append(f"# {file_name}\n{f.read()}")
        return "\n\n".join(output) if output else "No conventions found"
