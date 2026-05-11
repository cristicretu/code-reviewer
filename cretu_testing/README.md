# cretu_testing — discriminating eval

A second OOD set, calibrated to surface the gap between base and SFT/RLHF that the
existing eval understates.

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

## What's different here

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

## Composition

| Difficulty | N  |
| ---------- | -- |
| easy       | 8  |
| medium     | 20 |
| hard       | 15 |
| clean      | 7  |
| **total**  | 50 |

Multi-file diffs: 13. Multi-bug examples: 4.

## Running

```bash
# All four model variants
python -m cretu_testing.run_cretu_eval

# Single model
python -m cretu_testing.run_cretu_eval --models sft

# Smoke test
python -m cretu_testing.run_cretu_eval --max-examples 10 --models base
```

Predictions land in `cretu_testing/predictions/predictions_<label>.jsonl` and the
aggregate in `cretu_testing/cretu_results.json`. Same schema as `ood_testing`, so the
two can be compared directly.

## Rebuilding the dataset

`build_dataset.py` is the source of truth — the JSONL is generated. Edit examples
there and re-run:

```bash
python cretu_testing/build_dataset.py
```
