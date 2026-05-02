# Experiments

A lightweight log of the changes we A/B-tested against real PRs. Each
experiment is a single file `NNN-short-slug.md`, numbered in order of when
we ran it. Goal is reproducibility for the team and a paper trail for what
worked vs. didn't, so we don't relitigate decisions later.

## Format

Each experiment file should answer five questions, in this order:

1. **Hypothesis** — one sentence: what we expected to change and why.
2. **Setup** — the *one* variable we changed, what we held constant
   (model, max-agent-steps, RAG state, model server, target PR/SHA).
3. **Method** — exact commits / commands / runs so anyone can rerun.
4. **Results** — a small table: baseline vs. variant on the metric we
   actually care about (catch rate, latency, false-positive count).
5. **Takeaway** — what to ship, what to throw out, what's still open.

Keep experiments tight. If a writeup hits two pages, you're probably
trying to land more than one variable; split it.

## Index

| # | Title | Date | Outcome |
| --- | --- | --- | --- |
| [001](./001-system-prompt-checklist.md) | System prompt: bug-category checklist | 2026-05-02 | Shipped — catch rate 2/6 → 5/6, 0 false positives |
