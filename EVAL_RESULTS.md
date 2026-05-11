# Evaluation Results

All metrics computed on a held-out test set (11,772 examples from Microsoft CodeReviewer).
Automatic metrics use 100 examples; LLM-as-judge uses 10 examples each via Gemini 2.5 Flash.

## Automatic Metrics

| Metric | Base (qwen3:8b) | SFT (code-reviewer-lora) | RLHF (code-reviewer-grpo) |
|---|---|---|---|
| Defect F1 | 0.001 | 0.070 | **0.072** |
| CodeBERTScore | 0.000 | 0.668 | **0.669** |
| ChrF | 0.29 | 13.45 | **13.93** |
| ROUGE-L | 0.001 | 0.049 | **0.050** |
| Coherence | 0.009 | 0.491 | **0.507** |
| Hallucination rate | 100% | 76% | 81% |
| Toxicity rate | 0% | 0% | 0% |

Base model predictions average 3 characters (mostly empty). SFT and RLHF both produce detailed,
structured reviews (avg ~900 chars).

## LLM-as-Judge (Gemini 2.5 Flash)

| Metric | SFT (n=10) | RLHF (n=8) |
|---|---|---|
| Accuracy | **2.40** / 5.0 | 1.50 / 5.0 |
| Helpfulness | **1.90** / 5.0 | 1.25 / 5.0 |
| Specificity | **3.70** / 5.0 | 2.62 / 5.0 |

## Key Findings

- **Both SFT and RLHF dramatically outperform the base model** on every metric. Base model
  produces essentially empty reviews and fails to identify issues.

- **Automatic metrics show RLHF has a marginal edge** over SFT (Defect F1: 0.072 vs 0.070,
  ChrF: 13.93 vs 13.45, CodeBERTScore: 0.669 vs 0.668). The gap is consistent but small.

- **LLM-as-Judge (Gemini) favors SFT over RLHF** across all three dimensions. This suggests
  that GRPO training may have over-optimized for the training reward signal (Claude Haiku)
  without meaningfully improving subjective review quality as measured by a different judge model.

- **Hallucination rates are high** across both tuned models (76-81%), but the metric is
  heuristic (identifiers not in diff). Code reviews naturally introduce new identifiers when
  suggesting fixes, inflating this number.

- **Toxicity is zero** across all models — expected for professional code review data.

## Reproducing

```bash
# Automatic metrics
python -m sft.eval.run_lite

# LLM-as-judge (requires GEMINI_API_KEY in .env.local)
python -m sft.eval.judge --backend gemini --predictions outputs/eval/predictions_sft.jsonl --n 10
python -m sft.eval.judge --backend gemini --predictions outputs/eval/predictions_rlhf.jsonl --n 10

# Human eval template
python -m sft.eval.extract_for_human --n 20
```
