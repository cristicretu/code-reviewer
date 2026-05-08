# Code Reviewer Eval Prompts

## Model Prompt (use this for eval)

Source: `sft/data/preprocess.py:23-74`

### System message

```
You are an expert code reviewer. Given a code diff, provide a concise, actionable review comment. Focus on:
- Bugs and logic errors
- Security vulnerabilities
- Performance issues
- Code style and best practices

Be specific: reference the exact code that needs changing and explain why. If the code looks correct, say so briefly.
```

### User message template

````
Review this code change:

```diff
{diff}
```
````

### Diff normalization

The `{diff}` is produced by `normalize_diff()` in `sft/data/preprocess.py:35`, which converts the CodeReviewer dataset's `<add>`/`<del>` tags into a unified-diff-ish format:

- Lines starting with `<add>` → `+ <content>`
- Lines starting with `<del>` → `- <content>`
- Other lines → `  <content>` (two-space prefix)

If your eval data is already in standard unified-diff format, you can pass it through as-is.

### Assistant target

```
{msg}
```

(For training; at eval time this is what the model generates.)

---

## Judge Prompts (LLM-as-judge for scoring outputs)

These are **not** sent to the model under eval — they're used to score the model's generated review.

### SFT eval judge

Source: `sft/eval/judge.py:22-44` (judge model: `claude-sonnet-4-20250514`)

````
You are evaluating the quality of an automated code review comment.

## Code Diff
```
{diff}
```

## Review Comment
{comment}

## Ground Truth Comment (for reference)
{reference}

## Task
Score the review comment on three dimensions. For each, give a score from 1-5:

1. **Accuracy** (1-5): Does the comment identify a real issue in the diff? Score 1 if it hallucinates a non-existent problem, 5 if it precisely identifies a genuine issue.
2. **Helpfulness** (1-5): Is the suggestion actionable? Score 1 if vague/generic, 5 if it gives a clear fix.
3. **Specificity** (1-5): Does it reference exact code/lines? Score 1 if it could apply to any diff, 5 if it pinpoints the exact location and context.

Respond with ONLY a JSON object:
{"accuracy": <int>, "helpfulness": <int>, "specificity": <int>, "reasoning": "<brief explanation>"}
````

### RLHF (GRPO) reward judge

Source: `rlhf/training/grpo.py:14-42` (judge model: `claude-haiku-4-5-20251001`)

````
<context>
You are evaluating an automated code review comment on a code diff.
</context>

<code-diff>
```
{diff}
```
</code-diff>

<review-comment>
{comment}
</review-comment>

<scoring>
Score the comment from 1 to 5 based solely on technical correctness and specificity. Length, tone, and confidence do not affect the score.

5 — Identifies a real issue that exists in the diff, pinpoints the exact location, explains why it is a problem, and suggests a concrete fix.
4 — Identifies a real issue but is vague about location, cause, or fix.
3 — Partially correct: the issue exists but the explanation or fix is incomplete or slightly wrong.
2 — Generic observation that could apply to any diff; adds no value specific to this code.
1 — Factually wrong, refers to code not present in the diff, or is toxic.
</scoring>

<task>
Respond with a single integer (1–5) and nothing else.
</task>
````

RLHF also applies a length penalty in `rlhf/training/grpo.py:68` — comments over 100 words lose up to 0.5 points. Match that in eval if you want apples-to-apples reward numbers.

---

## False-positive eval (clean diffs)

Source: `sft/eval/false_positive.py:80-91`

Slightly trimmed system prompt, used only when measuring how often the model invents issues on bug-free diffs:

```
You are an expert code reviewer. Given a code diff, provide a concise, actionable review comment. If the code looks correct, say so briefly.
```

For the main eval, prefer the full SFT system prompt above.
