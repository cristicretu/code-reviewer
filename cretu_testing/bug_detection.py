"""Per-bug LLM-judge classifier for cretu_testing.

For each planted bug: judge answers found / not-found.
For each clean example: judge answers false_positive / no_false_positive.

Aggregating across the dataset gives precision / recall / accuracy / F1, which
discriminates between models much more cleanly than keyword overlap because the
judge actually reads the prediction and checks grounding (right file, right line,
right underlying issue).

Backends:
  - gemini   : free tier OK at ~5 RPM (script paces itself)
  - anthropic: faster, uses ANTHROPIC_API_KEY

Caching: every judge call is cached in cretu_testing/judge_cache.json keyed by
(backend, model_label, judge_kind, example_idx, bug_idx, prediction_hash) so
re-running after a tweak only re-judges what's new.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# Load .env.local for API keys (same pattern as sft.eval.judge)
try:
    from dotenv import load_dotenv

    for p in [
        Path(__file__).resolve().parent.parent / ".env.local",
        Path(".env.local"),
    ]:
        if p.exists():
            load_dotenv(p, override=False)
            break
except ImportError:
    pass


CACHE_PATH = Path(__file__).parent / "judge_cache.json"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

FOUND_PROMPT = """\
You are deciding whether an automated code review correctly identified a planted bug.

## Code Diff
```
{diff}
```

## Planted Bug
- File: {file}
- Approximate lines: {line_start}-{line_end}
- Category: {category}
- Severity: {severity}
- Description: {description}

## Review Comment
{prediction}

## Task
Did the review comment identify THIS specific bug? To count as YES, the comment must:
1. Refer to roughly the right location (the same file, function, or line area as the planted bug), and
2. Describe the same underlying issue (same root cause, not just a related category).

Generic boilerplate ("consider adding validation", "watch for edge cases") that doesn't \
ground to the planted bug counts as NO. A comment that identifies *a* real issue but \
not this specific one counts as NO.

Respond with ONLY a JSON object on a single line:
{{"found": true_or_false, "reasoning": "one sentence"}}"""


FALSE_POSITIVE_PROMPT = """\
You are deciding whether an automated code review raised a false alarm on clean code.

## Code Diff
```
{diff}
```

This diff is intentionally CLEAN — it was hand-verified to have no real bug. It may \
*look* suspicious at a glance (e.g. an f-string in SQL, a bare except, an empty deps \
array) but each case is correct in context.

## Review Comment
{prediction}

## Task
Does the review comment raise a substantive concern — claim there is a bug, security \
issue, performance problem, race condition, etc. — that is NOT actually present?

Pure style nitpicks ("could be renamed", "consider extracting") and explicit approvals \
("looks good", "no issues") count as NO.

Substantive bug claims (e.g. "this is SQL injection", "race condition", "memory leak") \
that don't actually apply count as YES (a false positive).

Respond with ONLY a JSON object on a single line:
{{"false_positive": true_or_false, "reasoning": "one sentence"}}"""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def _pred_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _cache_key(
    backend: str,
    model_label: str,
    kind: str,
    example_idx: int,
    bug_idx: int,
    pred_hash: str,
) -> str:
    return f"{backend}|{model_label}|{kind}|{example_idx}|{bug_idx}|{pred_hash}"


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------


def _parse_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Be forgiving of trailing chatter
    if not text.startswith("{"):
        i = text.find("{")
        if i >= 0:
            text = text[i:]
    if "}" in text:
        text = text[: text.rfind("}") + 1]
    return json.loads(text)


def _gemini_call(prompt: str, client, model: str) -> str:
    """Call Gemini with exponential backoff on rate-limit / availability errors."""
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return resp.text
        except Exception as e:
            last_error = e
            msg = str(e)
            if any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                time.sleep(min((2 ** attempt) * 5, 30))
                continue
            raise
    raise last_error  # type: ignore[misc]


def _anthropic_call(prompt: str, client, model: str) -> str:
    resp = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class Judgement:
    found: bool | None  # None for clean examples
    false_positive: bool | None  # None for buggy examples
    reasoning: str
    cached: bool


def _make_judge_fn(backend: str):
    if backend == "gemini":
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        model = os.environ.get("GEMINI_JUDGE_MODEL", "gemini-2.5-flash")

        def call(prompt: str) -> str:
            return _gemini_call(prompt, client, model)

        # Free-tier pacing: 5 RPM = 12s minimum between calls
        per_call_delay = float(os.environ.get("GEMINI_JUDGE_DELAY", "13"))
    elif backend == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        model = os.environ.get(
            "ANTHROPIC_JUDGE_MODEL", "claude-sonnet-4-20250514"
        )

        def call(prompt: str) -> str:
            return _anthropic_call(prompt, client, model)

        per_call_delay = 0.0
    else:
        raise ValueError(f"unknown backend: {backend!r}")

    return call, per_call_delay


def judge_predictions(
    examples: list[dict],
    predictions: list[str],
    model_label: str,
    backend: str = "gemini",
    progress: bool = True,
) -> list[list[Judgement]]:
    """Judge each (example, prediction) pair.

    For a buggy example with N planted bugs, returns N Judgements (one per bug).
    For a clean example, returns one Judgement (the false-positive check).

    Output shape mirrors examples: result[i] is the list of judgements for example i.
    """
    assert len(examples) == len(predictions)

    cache = _load_cache()
    call, per_call_delay = _make_judge_fn(backend)

    results: list[list[Judgement]] = []
    n_calls = 0
    last_call_t = 0.0

    for i, (ex, pred) in enumerate(zip(examples, predictions)):
        per_example: list[Judgement] = []
        bugs: list[dict] = ex.get("bugs", []) or []

        if not bugs:
            key = _cache_key(backend, model_label, "fp", i, 0, _pred_hash(pred))
            if key in cache:
                cached = cache[key]
                per_example.append(
                    Judgement(
                        found=None,
                        false_positive=cached["false_positive"],
                        reasoning=cached.get("reasoning", ""),
                        cached=True,
                    )
                )
            else:
                if progress:
                    print(
                        f"  [{model_label}] ex {i+1}/{len(examples)} (clean) -> judging...",
                        end="\r",
                        flush=True,
                    )
                # Rate limit
                if per_call_delay and last_call_t:
                    wait = per_call_delay - (time.time() - last_call_t)
                    if wait > 0:
                        time.sleep(wait)
                prompt = FALSE_POSITIVE_PROMPT.format(diff=ex["diff"], prediction=pred)
                raw = call(prompt)
                last_call_t = time.time()
                n_calls += 1
                try:
                    parsed = _parse_json(raw)
                    fp = bool(parsed.get("false_positive", False))
                    reason = parsed.get("reasoning", "")
                except Exception as e:
                    print(f"\n  WARNING: parse failure on ex {i} (clean): {e}\n  raw: {raw!r}")
                    fp = False
                    reason = f"parse_error: {e}"
                cache[key] = {"false_positive": fp, "reasoning": reason}
                _save_cache(cache)
                per_example.append(
                    Judgement(found=None, false_positive=fp, reasoning=reason, cached=False)
                )
        else:
            for b_idx, bug in enumerate(bugs):
                key = _cache_key(
                    backend, model_label, "found", i, b_idx, _pred_hash(pred)
                )
                if key in cache:
                    cached = cache[key]
                    per_example.append(
                        Judgement(
                            found=cached["found"],
                            false_positive=None,
                            reasoning=cached.get("reasoning", ""),
                            cached=True,
                        )
                    )
                    continue

                if progress:
                    print(
                        f"  [{model_label}] ex {i+1}/{len(examples)} bug {b_idx+1}/{len(bugs)} -> judging...",
                        end="\r",
                        flush=True,
                    )
                if per_call_delay and last_call_t:
                    wait = per_call_delay - (time.time() - last_call_t)
                    if wait > 0:
                        time.sleep(wait)
                prompt = FOUND_PROMPT.format(
                    diff=ex["diff"],
                    file=bug.get("file", "?"),
                    line_start=bug.get("line_start", "?"),
                    line_end=bug.get("line_end", "?"),
                    category=bug.get("category", "?"),
                    severity=bug.get("severity", "?"),
                    description=bug.get("description", ""),
                    prediction=pred,
                )
                raw = call(prompt)
                last_call_t = time.time()
                n_calls += 1
                try:
                    parsed = _parse_json(raw)
                    found = bool(parsed.get("found", False))
                    reason = parsed.get("reasoning", "")
                except Exception as e:
                    print(
                        f"\n  WARNING: parse failure on ex {i} bug {b_idx}: {e}\n  raw: {raw!r}"
                    )
                    found = False
                    reason = f"parse_error: {e}"
                cache[key] = {"found": found, "reasoning": reason}
                _save_cache(cache)
                per_example.append(
                    Judgement(
                        found=found, false_positive=None, reasoning=reason, cached=False
                    )
                )

        results.append(per_example)

    if progress:
        print(f"  [{model_label}] judged {len(examples)} examples ({n_calls} new LLM calls)")

    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(judgements: list[list[Judgement]]) -> dict:
    """Compute confusion matrix and derived metrics from per-example judgements."""
    tp = fn = fp = tn = 0
    by_difficulty: dict[str, dict[str, int]] = {}

    for ex_judgements in judgements:
        for j in ex_judgements:
            if j.found is True:
                tp += 1
            elif j.found is False:
                fn += 1
            elif j.false_positive is True:
                fp += 1
            elif j.false_positive is False:
                tn += 1

    total = tp + fn + fp + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    accuracy = (tp + tn) / total if total else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    return {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
        "f1": round(f1, 4),
        "n_decisions": total,
    }


def aggregate_by_difficulty(
    examples: list[dict], judgements: list[list[Judgement]]
) -> dict:
    """Same metrics but bucketed by example difficulty."""
    buckets: dict[str, list[list[Judgement]]] = {}
    for ex, jud in zip(examples, judgements):
        buckets.setdefault(ex["difficulty"], []).append(jud)
    return {d: aggregate(b) for d, b in buckets.items()}
