"""Generate model predictions via an OpenAI-compatible API (Ollama, vLLM, etc.).

Like run_eval.py but works on any device — no GPU or Unsloth needed.
Uses LiteLLMModel (same client as the agent) to call the model.

Usage:
    # Serve the model via Ollama:
    ollama run cretu-luca/code-reviewer-grpo

    # Generate predictions:
    API_BASE=http://localhost:11434/v1 MODEL_ID=cretu-luca/code-reviewer-grpo \
        python -m sft.eval.generate_via_api --model-label rlhf_local
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from smolagents import LiteLLMModel
from loguru import logger


def load_test_data(path: str, max_examples: int | None = None) -> list[dict]:
    examples = []
    with open(path) as f:
        for line in f:
            examples.append(json.loads(line))
    if max_examples:
        examples = examples[:max_examples]
    return examples


def build_prompt(messages: list[dict]) -> list[dict]:
    return messages[:2]


def extract_reference(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return ""


def extract_user_msg(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def generate(model: LiteLLMModel, ex: dict) -> dict | None:
    messages = ex.get("messages", [])
    prompt = build_prompt(messages)
    reference = extract_reference(messages)
    user_msg = extract_user_msg(messages)

    if not user_msg or not reference:
        return None

    try:
        response = model(prompt, max_tokens=256, temperature=0.1)
    except Exception as e:
        logger.error(f"Model call failed: {e}")
        return None

    content = response.content if hasattr(response, "content") else str(response)
    content = content.strip() or ""

    return {
        "diff": user_msg,
        "prediction": content,
        "reference": reference,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate predictions via API")
    parser.add_argument("--model-label", required=True, help="Label for output filename (e.g. rlhf_local)")
    parser.add_argument("--test-data", default="data/processed/test.jsonl")
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/eval"))
    parser.add_argument("--api-base", default=None, help="Override API_BASE env var")
    parser.add_argument("--model-id", default=None, help="Override MODEL_ID env var")
    args = parser.parse_args()

    import os
    if args.api_base:
        os.environ["API_BASE"] = args.api_base
    if args.model_id:
        os.environ["MODEL_ID"] = args.model_id

    api_base = os.environ.get("API_BASE", "http://localhost:11434/v1")
    model_id = os.environ.get("MODEL_ID", "model")
    if not model_id.startswith("openai/"):
        model_id = f"openai/{model_id}"
    os.environ.setdefault("OPENAI_API_KEY", "dummy")

    test_path = Path(args.test_data)
    if not test_path.exists():
        logger.error(f"Test data not found: {test_path}")
        return 1

    examples = load_test_data(str(test_path), args.max_examples)
    logger.info(f"Loaded {len(examples)} test examples from {test_path}")
    logger.info(f"Model endpoint: {api_base}")
    logger.info(f"Model ID: {model_id}")

    model = LiteLLMModel(model_id=model_id, api_base=api_base)

    results = []
    for i, ex in enumerate(examples):
        print(f"\rGenerating {i+1}/{len(examples)}...", end="", flush=True)
        result = generate(model, ex)
        if result:
            results.append(result)
    print()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"predictions_{args.model_label}.jsonl"
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    logger.info(f"Saved {len(results)} predictions to {output_path}")
    logger.info(f"Next: python -m sft.eval.deepeval_judge --predictions {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
