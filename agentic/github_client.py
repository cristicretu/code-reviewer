import requests


class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self.token = token
        self.base_url = base_url.rstrip("/")

    def _headers(self, accept: str = "application/vnd.github+json") -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "code-reviewer-agent",
        }

    def get_pr(self, repo: str, pr_number: int) -> dict:
        r = requests.get(
            f"{self.base_url}/repos/{repo}/pulls/{pr_number}",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_pr_diff(self, repo: str, pr_number: int) -> str:
        r = requests.get(
            f"{self.base_url}/repos/{repo}/pulls/{pr_number}",
            headers=self._headers(accept="application/vnd.github.v3.diff"),
            timeout=60,
        )
        r.raise_for_status()
        return r.text

    def get_existing_review_comments(self, repo: str, pr_number: int) -> list:
        r = requests.get(
            f"{self.base_url}/repos/{repo}/pulls/{pr_number}/comments",
            headers=self._headers(),
            params={"per_page": 100},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def submit_review(
        self,
        repo: str,
        pr_number: int,
        commit_id: str,
        event: str,
        body: str,
        comments: list,
    ) -> dict:
        payload = {"commit_id": commit_id, "event": event, "body": body}
        if comments:
            payload["comments"] = comments
        r = requests.post(
            f"{self.base_url}/repos/{repo}/pulls/{pr_number}/reviews",
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
