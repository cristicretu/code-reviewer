# 001 — System prompt: bug-category checklist

- **Date:** 2026-05-02
- **Status:** shipped (`v1` tag force-moved to `efdba5f`)
- **Outcome:** catch rate 2/6 → 5/6, 0 false positives, +52s latency

## Hypothesis

The first generic system prompt told the agent to "find real bugs, security
issues, and logic errors" without saying *what* to look for. Adding a short,
concrete checklist of failure-mode categories before the verdict step should
push the agent from generic exploration into targeted scanning, raising catch
rate without raising step budget (Mac KV-cache headroom is already the
constraint — see commit `a069938`'s message).

## Setup

| | Held constant |
| --- | --- |
| Model | `cretu-luca/code-reviewer-grpo` merged onto `Qwen/Qwen3.5-9B`, 4-bit MLX, served on Mac via `mlx_lm.server` + cloudflared tunnel |
| Target PR | `cristicretu/code-reviewer-test-repo` PR #1 (`feat/waitlist`, head `8963720`) — adds a Supabase waitlist form with 6 deliberately introduced bugs |
| Action | `cristicretu/code-reviewer@v1` (composite GH Action) |
| max-agent-steps | 8 |
| comment-budget | 10 |
| RAG | full repo ingest into Chroma each run, no chunking |

| | Variable |
| --- | --- |
| `agentic/entrypoint.py::SYSTEM_INSTRUCTIONS` | baseline (generic "find bugs") vs. variant (adds 6-line checklist + framework gotchas: error-path state, PII in logs, hardcoded fallbacks, input validation, error UX, Vite/Next/React/async conventions) |

## Method

The 6 introduced bugs in PR #1:

1. `src/supabase.ts:4` — env var `SUPABASE_ANON_KEY` not prefixed `VITE_`, evaluates to `undefined` in the browser.
2. `src/supabase.ts:3` — hardcoded `https://example.supabase.co` fallback masks misconfiguration.
3. `src/App.tsx submit()` — `setLoading(false)` only on success; button stuck disabled forever after error.
4. `src/App.tsx submit()` — `console.log("waitlist signup", email, error)` leaks user email PII.
5. `src/App.tsx submit()` — only checks `!email`, no format validation past `type="email"`.
6. `src/App.tsx` — error path has no user-visible feedback; failures look like "still loading".

Both runs hit the same head SHA (`8963720`), the same model server, and the
same RAG index. Only the system-prompt commit differs.

| Run | Action commit | Run ID | Trigger |
| --- | --- | --- | --- |
| Baseline | `a069938` | [25254835569](https://github.com/cristicretu/code-reviewer-test-repo/actions/runs/25254835569) | PR open |
| Variant | `efdba5f` | [25255037981](https://github.com/cristicretu/code-reviewer-test-repo/actions/runs/25255037981) | PR close + reopen |

## Results

| Metric | Baseline | Variant | Δ |
| --- | --- | --- | --- |
| Catch rate | 2 / 6 | 5 / 6 | **+3** |
| Inline findings posted | 2 | 4 (this run) + 2 (carried from baseline visible to GitHub on the same SHA) | — |
| False positives | 0 | 0 | 0 |
| Verdict | `CHANGES_REQUESTED` | `CHANGES_REQUESTED` | — |
| Workflow duration | 2m 53s | 3m 45s | +52s |
| Mac kernel panics | 0 | 0 | 0 |

What the variant caught that the baseline missed:

- Bug 4 (PII in `console.log`)
- Bug 5 (no email format validation)
- Bug 6 (no error UX)
- Bug 2 cleaner: hit the URL fallback at line 4 directly, vs. the baseline's adjacent partial finding on the empty anon-key fallback at line 5.

What both runs missed:

- Bug 1 (`VITE_` prefix). The variant prompt does mention the Vite convention,
  but apparently too generally — the agent flagged the empty-key *symptom* on
  the same line without identifying the missing prefix as the *cause*.

## Takeaway

- **Ship the checklist.** Largest catch-rate jump per token-of-prompt we've
  seen. Live behind `v1`.
- **Latency cost is acceptable.** ~50s extra on a 4-minute run is noise
  compared to the +3 findings.
- **Diminishing returns from making the prompt longer.** Pushing for 6/6 by
  adding more framework-specific cues risks false positives and prompt-engineering
  smell. A more credible demo story is "5/6 with one honest miss" than "6/6 with a
  prompt clearly tuned for this exact diff."

## Open questions / future experiments

- Does the same checklist help on a Python or Go diff, or is it React/TS-leaning
  by accident?
- Does a 12-step budget (and tighter diff truncation to keep KV-cache flat)
  catch bug #1, or is that bug genuinely outside this model's reach at 4-bit?
- Does a Vite-specific RAG document (one-pager dropped into the repo's RAG
  index pre-run) help the agent connect the symptom to the cause?
