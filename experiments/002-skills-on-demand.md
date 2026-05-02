# 002 — On-demand framework skills

- **Date:** 2026-05-02
- **Status:** shipped (`v1` tag at `b318a68`)
- **Outcome:** 5/7 cumulative catch rate on PR #2 (was 2/7 baseline). The +3
  delta is directly attributable to skill-loaded playbook content.

## Hypothesis

Experiment 001 showed that adding a generic checklist of failure-mode
*categories* to the system prompt jumped catch rate from 2/6 → 5/6 on PR #1
(form / env-var bugs). PR #2 (a React focus-timer with Supabase realtime, 7
React-lifecycle / closure / async bugs) was harder: the same checklist only
caught 2/7. The hypothesis: framework-*specific* knowledge (e.g. "every
`.subscribe()` needs a `removeChannel`", "`.toString()` doesn't parse as
`timestamptz`") would close the gap, but injecting all of it eagerly would
blow up the agent's KV cache. So: detect the stack at task setup, present a
*catalog* of relevant playbooks in the prompt, and let the agent pull the
ones it wants on demand via a `load_skill` tool.

## Setup

| | Held constant |
| --- | --- |
| Model | `cretu-luca/code-reviewer-grpo` merged onto `Qwen/Qwen3.5-9B`, 4-bit MLX, served on Mac via `mlx_lm.server` + cloudflared tunnel |
| Target PR | `cristicretu/code-reviewer-test-repo` PR #2 (`feat/focus-timer`, head `c12bc8d`) — adds `FocusTimer.tsx` with 7 deliberately introduced bugs |
| Action | `cristicretu/code-reviewer@v1` (composite GH Action) |
| max-agent-steps | 8 |
| comment-budget | 10 |
| RAG | full repo ingest into Chroma each run, no chunking |
| System prompt body | unchanged from experiment 001 (failure-mode checklist) |

| | Variable |
| --- | --- |
| Skill loading mechanism | (a) none → (b) eager-injected bodies → (c) catalog + `load_skill` tool (cost-warning framing) → (d) catalog + `load_skill` tool (value-pitch framing) |

Per the design intent: skills are *not* mandatory. The agent decides whether
each playbook is worth pulling into context. Detection (parsing
`package.json`/`pyproject.toml`/`Cargo.toml`/`go.mod` + diff file
extensions) is a *hint* of what's likely relevant for this stack.

## Method

The 7 introduced bugs in PR #2:

1. `FocusTimer.tsx:17` — stale-closure tick inside `setInterval`, deps
   `[running]`. Real fix is the functional updater `setSeconds(s => s - 1)`.
2. `FocusTimer.tsx:31` — keydown listener leaks: no `removeEventListener`
   in cleanup.
3. `FocusTimer.tsx:44` — Supabase channel never removed: no
   `removeChannel` in cleanup.
4. `FocusTimer.tsx:48` — race condition on `load()`: concurrent
   `postgres_changes`-triggered fetches can interleave; needs an
   `AbortController` or version id.
5. `FocusTimer.tsx:60` — `new Date().toString()` for a `timestamptz`
   column. Fix is `toISOString()`.
6. `FocusTimer.tsx:23` — auto-save effect with no fire-once guard;
   `saveSession` captures stale state via closure.
7. `FocusTimer.tsx:67` — `start()` while running doesn't restart the
   interval; old interval ticks against new state.

Three iterations on the same head SHA (`c12bc8d`):

| Run | Action commit | Run ID | Skill UX |
| --- | --- | --- | --- |
| Baseline | `efdba5f` | [25255741854](https://github.com/cristicretu/code-reviewer-test-repo/actions/runs/25255741854) | none (exp 001 prompt only) |
| Skills v1 | `2dc2078` | [25256060712](https://github.com/cristicretu/code-reviewer-test-repo/actions/runs/25256060712) | catalog with cost-warning framing ("each load consumes context budget") |
| Skills v2 | `df35a51` | [25256232246](https://github.com/cristicretu/code-reviewer-test-repo/actions/runs/25256232246) | catalog reframed as value pitch ("AVAILABLE PLAYBOOKS", lists specific bugs each skill covers, shows literal `load_skill("...")` syntax) |

## Results

| Metric | Baseline | Skills v1 (cost framing) | Skills v2 (value framing) |
| --- | --- | --- | --- |
| `load_skill` calls in trace | n/a | **0** | **5** (3 distinct: react, supabase, async-js) |
| New unique inline findings | 5 | 4 unique + 4 duplicates | 2 |
| Bug 4 caught (race condition) | no | no | **yes**, agent cited supabase playbook |
| Bug 5 caught (`.toString` → `.toISOString`) | no | no | **yes**, agent cited supabase playbook |
| Cumulative bugs caught (this SHA) | 2/7 | 2/7 | **5/7** |
| Workflow duration | 2m 53s | 3m 57s | 5m 8s |
| Mac kernel panics | 0 | 0 | 0 |

Cumulative breakdown after Skills v2:

- Bug 1 (stale closure tick) — **misdiagnosed** at baseline (suggested
  adding `seconds` to deps, the wrong fix). Not corrected.
- Bug 2 (keydown leak) — **hit** at baseline.
- Bug 3 (channel `removeChannel`) — **hit** in Skills v1.
- Bug 4 (race condition) — **hit** in Skills v2, citing playbook.
- Bug 5 (`.toString` → `.toISOString`) — **hit** in Skills v2, citing playbook.
- Bug 6 (auto-save fire-once) — **partial** in baseline (closure capture noted).
- Bug 7 (`start()` doesn't restart interval) — **missed**.

## Takeaway

- **Ship the on-demand skills system.** Live behind `v1`. Five starter
  skills (`react`, `vite`, `supabase`, `async-js`, `nextjs`) cover the JS
  stack; `pyproject.toml` / `Cargo.toml` / `go.mod` triggers exist for
  future Python / Rust / Go skills.
- **Prompt framing is the variable, not the mechanism.** Same code, same
  catalog data — the model went from 0 `load_skill` calls to 5 just by
  reframing the catalog from cost-warning to value-pitch ("Senior reviewers
  maintain framework-specific playbooks of bugs that linters miss"). When
  the obvious-good-move *looks* obvious-and-good, the model takes it.
- **Skill-derived findings are disproportionately valuable.** Bug 4 (race
  condition) and bug 5 (`timestamptz` formatting) are exactly the class of
  bug a generic checklist *can't* hint at — they need framework-specific
  domain knowledge. Both got caught, both with playbook citations in the
  agent's reasoning trace.
- **Two follow-up tweaks shipped same day** (commit `b318a68`):
  `LoadSkillTool` now dedupes by skill name (Skills v2 wasted ~1500 tokens
  re-loading react + supabase in step 2), and the catalog tells the model
  to load *at most 2-3* skills (Skills v2 loaded 3 of 4 in one step,
  contributing to the parse-error bottleneck below).

## Open questions / future experiments

- **smolagents code-block parse errors are the new bottleneck.** Skills v2
  burned **3 of 8 steps** on `Your code snippet is invalid, because the regex
  pattern <code>(.*?)</code> was not found` errors — the model emitted prose
  `Thought: ...` blocks instead of the required code-block format.
  Without those losses, the same run would likely have posted 4-5 findings
  instead of 2. **→ Experiment 003 candidate: switch from `CodeAgent` to
  `ToolCallingAgent`** (uses native function-calling JSON, no code-block
  parsing, no regex, no parse errors). Bigger refactor (~30 min) but a
  clean ablation of agent type holding everything else constant.
- **Bug 1 still misdiagnosed across all three runs.** The model sees a
  symptom (interval not updating) and proposes a *plausible-but-wrong* fix
  (add `seconds` to deps array). Even with the react skill loaded, it never
  proposed the correct fix (functional updater `setSeconds(s => s - 1)`).
  This is a model-knowledge ceiling at 9B 4-bit, not a prompt issue. Worth
  re-running on a larger / less-quantised model to confirm.
- **Bug 7 (`start()` while running) is genuinely subtle.** No skill covers
  it explicitly. Could add a `react-state-sync.md` skill, or accept that
  some bugs need a real type-checker / static-analysis tool.
- **Skill ROI per skill loaded.** Skills v2 loaded react + supabase +
  async-js but only the supabase content shows up in the comment text.
  Worth measuring per-skill yield once we have more PRs to test on.
