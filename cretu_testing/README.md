# cretu_testing — discriminating eval

A second OOD set + scoring pipeline, calibrated to surface the gap between base and
SFT/RLHF that the existing eval understates.

## Why this set exists

On `ood_testing/100-syntetic.txt`, SFT and RLHF look only marginally better than base.
That contradicts hand-testing. Reasons the existing eval underweights what SFT buys
you:

1. **Bugs are textbook patterns.** SQL injection f-strings, missing await, `useEffect`
   deps. A 9B base model has seen these verbatim — it pattern-matches without
   understanding.
2. **`bug_detection_rate` is keyword overlap** on category tokens (`injection`, `race`,
   `null`). Any generic security-flavored review hits the keyword without grounding.
3. **ChrF / ROUGE / CodeBERTScore reward surface overlap** with the description string.
   A base model that writes long, generic reviews accidentally scores well on the same
   vocabulary; SFT, which writes terse pointed comments, loses surface similarity.
4. **No real cost for false alarms.** Clean cases are 11/100 — too thin to move the
   aggregate.
5. **No multi-file diffs.** Cross-cutting bugs are where SFT's training distribution
   (real PRs) actually shines.

## What's different in the dataset

- **Subtler bugs.** Description text deliberately avoids the obvious keyword
  (`hmac`/`timing-attack`, not "compare digest"); the bug shows itself in code intent,
  not a stock pattern.
- **Bigger diffs with distractors.** ~30-50 lines around each bug rather than 5-line
  toys, so the model must localize.
- **Multi-file diffs in the hard tier.** Bug only surfaces by cross-referencing files
  — e.g. migration adds NOT NULL but a seed script in another file still omits the
  column.
- **More "looks suspicious, is correct" clean cases** (7/50) to put real weight on
  false-positive rate.
- **A few multi-bug examples** to test prioritization — does the model surface the
  critical bug, or get distracted by a minor one?

### Composition

| Difficulty | N  |
| ---------- | -- |
| easy       | 8  |
| medium     | 20 |
| hard       | 15 |
| clean      | 7  |
| **total**  | 50 |

Multi-file diffs: 13. Multi-bug examples: 4.

## Two metric families

Scoring is split into two sets, kept deliberately separate.

### Set 1 — Bug detection (the discriminating signal)

A per-bug LLM judge that answers, for each planted bug, **did the prediction identify
this specific bug?** For clean diffs it answers the inverse: **did the prediction raise
a substantive false alarm?**

Aggregated across the dataset, this yields a real confusion matrix:

|                     | judged-bug | judged-no-bug |
| ------------------- | ---------- | ------------- |
| **planted bug**     | TP         | FN            |
| **clean diff**      | FP         | TN            |

From which: **precision**, **recall**, **accuracy**, **F1**.

This is the metric that actually moves between models. Keyword overlap can't tell
"mentions injection vaguely" from "names the f-string on line 16 and proposes a `%s`
placeholder fix" — the judge can.

Implementation: `cretu_testing/bug_detection.py`. Backends: Gemini (free-tier paced),
Anthropic (faster). Every judge call is cached in `judge_cache.json` keyed by
`(backend, model_label, kind, example_idx, bug_idx, pred_hash)` so re-runs after a
tweak only re-judge what's new.

### Set 2 — Review-quality (cheap, deterministic)

Heuristic metrics that don't need a judge:

- **coherence** — structural quality (sentence count, length distribution, code-to-text
  ratio, explanation-structure markers).
- **hallucination_rate** — fraction of predictions referencing identifiers not in the
  diff.
- **toxicity_rate** — regex over a small toxic-language lexicon.

These reuse `sft.eval.defect_metrics` so numbers are directly comparable to existing
reports.

## Pipeline

```bash
# 1. Generate predictions (slow — model inference)
python -m cretu_testing.run_cretu_eval --models base,sft,rlhf

# 2. Score predictions (cheap; LLM-judge part is rate-limited)
export GEMINI_API_KEY=...        # or ANTHROPIC_API_KEY for --backend anthropic
python -m cretu_testing.score --models base,sft,rlhf --by-difficulty

# Set 2 only (no API key needed, instant)
python -m cretu_testing.score --models base,sft,rlhf --skip-judge
```

Outputs:
- `cretu_testing/predictions/predictions_<label>.jsonl` — raw predictions per model
- `cretu_testing/cretu_scores.json` — both metric families per model
- `cretu_testing/judge_cache.json` — LLM-judge call cache (commit this to share runs)

## Rebuilding the dataset

`build_dataset.py` is the source of truth — the JSONL is generated. Edit examples
there and re-run:

```bash
python cretu_testing/build_dataset.py
```
