"""End-to-end orchestration: fetch PR + diff, run the agent, submit one batched review.

Designed for CI: reads everything from env vars set by the GitHub Actions workflow.
Required env: GITHUB_TOKEN, GITHUB_REPOSITORY (or REPO_ID), PR_NUMBER, HEAD_SHA.
Optional env: API_BASE, MODEL_ID, RAG_URL, MAX_AGENT_STEPS, COMMENT_BUDGET.
"""

import os
import sys

from loguru import logger

from agentic.agent import build_agent
from agentic.config import COMMENT_BUDGET, MAX_AGENT_STEPS
from agentic.github_client import GitHubClient
from agentic.review_state import REVIEW_STATE
from agentic.skills.loader import detect_skills, format_skills_catalog


SYSTEM_INSTRUCTIONS = """\
You are an automated code reviewer. Your job is to find real bugs, security issues, and
logic errors introduced by this pull request. Skip stylistic nits unless they create a
real defect. Investigate before commenting -- use semantic_search, search_keyword,
search_symbol, get_file, and check_history to ground claims in the actual code.

Before your verdict, scan the diff for these failure modes (not exhaustive -- apply to
whatever the diff actually contains):

- ERROR PATHS that don't restore state: catch blocks that leave a loading flag,
  disabled button, lock, or transaction in the wrong state on failure.
- LOGGING that leaks user PII: console.log / console.error / logger calls that
  include emails, names, tokens, IDs, or full request bodies.
- HARDCODED FALLBACKS that mask misconfiguration: defaults like "example.com",
  "dummy", "localhost", "test-key", or empty strings sitting behind missing env
  vars -- production will silently misbehave instead of failing loudly.
- INPUT VALIDATION gaps: user input from forms / URL params / request bodies
  passed to a sink (DB, API, shell, query string) without format / length /
  range / type checks. type="email" on an <input> is not validation.
- ERROR UX: catch blocks with no user-visible feedback, so failures look
  identical to "still loading".
- FRAMEWORK CONVENTIONS: a few common gotchas worth checking when relevant:
    * Vite: only env vars prefixed VITE_ are exposed to client code; anything
      else evaluates to undefined in the browser.
    * Next.js: server vs client component boundary, "use client", server-only
      env on the client.
    * React: useEffect/useMemo dep arrays, controlled vs uncontrolled inputs,
      stale closures over state.
    * Async: missing await, unhandled promise rejections, race conditions.

For each issue, call post_comment(file, line, severity, category, suggestion) with a
line number on the new (RIGHT) side of the diff. Suggestions should explain *why* it's
a bug and what to do about it. You may also call propose_patch to attach a
GitHub-style suggested change.

Pick exactly one verdict by calling request_changes, approve, or comment_only. This is
first-call-wins and cannot be changed. Comments cannot be added after the verdict.
Immediately after the verdict, call final_answer("done") to end the review.

Rules:
- Do not duplicate findings already listed under "ALREADY FLAGGED".
- Comment budget is enforced server-side; pick the highest-impact issues first.
- If nothing is wrong, call approve with no comments, then final_answer("done").
"""


def _format_existing(existing: list, limit: int = 30) -> str:
    if not existing:
        return ""
    lines = []
    for c in existing[:limit]:
        path = c.get("path") or "?"
        line = c.get("line") or c.get("original_line") or "?"
        body = (c.get("body") or "").strip().replace("\n", " ")
        if len(body) > 160:
            body = body[:160] + "..."
        lines.append(f"- {path}:{line} :: {body}")
    return "\n\nALREADY FLAGGED (do not duplicate):\n" + "\n".join(lines)


def build_task_prompt(pr: dict, diff: str, existing: list, skills_catalog: str = "") -> str:
    base = pr.get("base", {})
    head = pr.get("head", {})
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"{skills_catalog}"
        f"Repository: {base.get('repo', {}).get('full_name')}\n"
        f"PR #{pr.get('number')}: {pr.get('title')}\n"
        f"Author: @{pr.get('user', {}).get('login')}\n"
        f"Base: {base.get('ref')} <- Head: {head.get('ref')}\n"
        f"Changed files: {pr.get('changed_files')}  +{pr.get('additions')} / -{pr.get('deletions')}\n\n"
        f"Description:\n{pr.get('body') or '(no description)'}\n\n"
        f"Diff:\n```diff\n{diff}\n```"
        f"{_format_existing(existing)}"
    )


def _truncate_diff(diff: str, max_chars: int = 60000) -> str:
    if len(diff) <= max_chars:
        return diff
    head = diff[: max_chars // 2]
    tail = diff[-max_chars // 2 :]
    return head + f"\n\n... [diff truncated, original {len(diff)} chars] ...\n\n" + tail


def main() -> int:
    repo = os.environ.get("REPO_ID") or os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    head_sha = os.environ.get("HEAD_SHA")
    gh_token = os.environ.get("GITHUB_TOKEN")

    if not (repo and pr_number and head_sha and gh_token):
        logger.error(
            "Missing required env vars: REPO_ID/GITHUB_REPOSITORY, PR_NUMBER, HEAD_SHA, GITHUB_TOKEN"
        )
        return 2

    api_base = os.environ.get("API_BASE", "")
    if not api_base or api_base == "http://localhost:1234/v1":
        logger.warning(
            "API_BASE is empty or points at the LM Studio default. "
            "Set the MODEL_API_BASE secret to your hosted endpoint or LiteLLM will fall through to the OpenAI default."
        )

    pr_number_int = int(pr_number)
    client = GitHubClient(gh_token)

    logger.info(f"Fetching PR {repo}#{pr_number_int}")
    pr = client.get_pr(repo, pr_number_int)
    diff = client.get_pr_diff(repo, pr_number_int)
    existing = client.get_existing_review_comments(repo, pr_number_int)

    REVIEW_STATE.configure(
        client=client,
        repo=repo,
        pr_number=pr_number_int,
        commit_id=head_sha,
        comment_budget=COMMENT_BUDGET,
    )

    truncated_diff = _truncate_diff(diff)
    skills_in_catalog = detect_skills(diff=truncated_diff)
    if skills_in_catalog:
        logger.info(
            "Skill catalog (agent will load_skill on demand): "
            + ", ".join(s.name for s in skills_in_catalog)
        )
    else:
        logger.info("No skills matched the consumer repo manifest.")
    skills_catalog = format_skills_catalog(skills_in_catalog)

    task = build_task_prompt(pr, truncated_diff, existing, skills_catalog)
    logger.info(
        f"Running agent (max_steps={MAX_AGENT_STEPS}, comment_budget={COMMENT_BUDGET})"
    )

    agent_failed = False
    agent = build_agent()
    try:
        agent.run(task, max_steps=MAX_AGENT_STEPS)
    except Exception as e:
        logger.exception(f"Agent run failed: {e}")
        agent_failed = True
        if not REVIEW_STATE.verdict:
            REVIEW_STATE.set_verdict("COMMENT")

    REVIEW_STATE.submit()
    return 1 if agent_failed else 0


if __name__ == "__main__":
    sys.exit(main())
