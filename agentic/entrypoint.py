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
real defect.

REQUIRED WORKFLOW (do not skip steps):

Step 1 -- INVESTIGATE (at least 2 tool calls before any post_comment):
  Pick the most suspicious lines in the diff and confirm them in actual project code.
  At least one of:
    * semantic_search("<symbol or pattern>") -- find related code via the RAG index.
      ALWAYS call this first to understand how a changed function is used elsewhere.
    * get_file("<path>", start, end) -- read full surrounding context (helpers,
      types, callers).
    * search_keyword("<literal>") -- ripgrep across the repo.
    * search_symbol("<name>") -- AST walk for Python definitions.
    * check_history("<file>") -- git blame on the touched lines (history of the
      function tells you why it was written this way).
    * get_team_conventions() -- read .cursorrules / CONTRIBUTING.md / CLAUDE.md
      so suggestions match team style.
  After investigating, you can also call run_tests(), run_linter(), or run_typecheck()
  to confirm a suspected bug actually breaks something.

Step 2 -- POST findings (one post_comment per distinct bug):
  Only AFTER you've called at least one investigation tool. Call
  post_comment(file, line, severity, category, suggestion) for each finding,
  with a line number on the new (RIGHT) side of the diff. Suggestions should
  explain *why* it's a bug, citing what you saw in the investigation, and what
  to do about it. You may also call propose_patch for a GitHub-style suggested change.

Step 3 -- VERDICT (exactly one):
  Pick exactly one of request_changes / approve / comment_only. First-call-wins.
  Then call final_answer("done").

Failure modes to scan the diff for (not exhaustive):
- ERROR PATHS that don't restore state (loading flag, disabled button, lock,
  transaction left in wrong state on failure).
- LOGGING that leaks user PII (emails, names, tokens, IDs, full request bodies).
- HARDCODED secrets, fallbacks, or defaults that mask misconfiguration.
- INPUT VALIDATION gaps (user input -> DB / API / shell / query string with no
  format/length/range/type check).
- ERROR UX (catch with no user-visible feedback, looks identical to "still loading").
- AUTH / AUTHZ gaps (missing auth check, IDOR, exposing sensitive columns).
- CRYPTO mistakes (MD5/SHA1 for passwords, Math.random() for tokens, hardcoded
  IV/key, non-constant-time compare).
- INJECTION (SQL, command, prototype pollution, eval of user input, SSRF, XSS via
  dangerouslySetInnerHTML or innerHTML).
- FRAMEWORK gotchas: Vite VITE_ prefix, Next.js client/server boundary, React
  useEffect deps + cleanup + stale closures, async missing-await + races + sequential-
  in-loop.

Rules:
- INVESTIGATE FIRST. A run that posts comments without first calling at least one
  investigation tool is a failed review -- you are guessing, not reviewing.
- Do not duplicate findings already listed under "ALREADY FLAGGED".
- Comment budget is enforced server-side; pick the highest-impact issues first.
- If after investigation nothing is wrong, call approve with no comments, then
  final_answer("done").
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
