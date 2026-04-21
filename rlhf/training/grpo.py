"""GRPO post-training for the code review LoRA adapter.

Uses Claude (Haiku) as an LLM-as-judge reward signal via the Anthropic API.

Run:
    python -m rlhf.training.grpo
    python -m rlhf.training.grpo --smoke-test
"""

import argparse
import json
import os
import time

import yaml
from datasets import Dataset


def _ensure_transformers_cache_symbol() -> None:
    """
    TRL's GRPO import path can pull in llm_blender, which expects
    `transformers.utils.hub.TRANSFORMERS_CACHE` (removed in Transformers v5).
    Patch the symbol before importing TRL.
    """
    try:
        import transformers.utils.hub as hub  # type: ignore
    except ModuleNotFoundError:
        return

    if hasattr(hub, "TRANSFORMERS_CACHE"):
        return

    cache = os.environ.get("TRANSFORMERS_CACHE")
    if not cache:
        try:
            from huggingface_hub.constants import HF_HUB_CACHE  # type: ignore

            cache = HF_HUB_CACHE
        except Exception:
            cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface")

    setattr(hub, "TRANSFORMERS_CACHE", cache)


def load_config(path: str = "rlhf/training/grpo_config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


JUDGE_PROMPT = """\
You are evaluating an automated code review comment.

## Code Diff
```
{diff}
```

## Review Comment
{comment}

## Task
Score this review comment from 1 to 5:
5 = identifies a real issue precisely, explains it clearly, suggests a concrete fix
4 = mostly correct with minor vagueness
3 = partially useful but missing key detail or slightly off
2 = vague or generic, could apply to any diff
1 = wrong, hallucinated a non-existent problem, or toxic

Respond with a single integer (1-5) and nothing else."""


def judge_completion(
    diff: str,
    comment: str,
    client,
    judge_model: str,
    judge_sleep: float,
) -> float:
    try:
        import anthropic  # type: ignore
    except ModuleNotFoundError as e:
        raise SystemExit(
            "ERROR: Missing dependency 'anthropic'. Install with: pip install anthropic"
        ) from e

    prompt = JUDGE_PROMPT.format(diff=diff, comment=comment)
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=judge_model,
                max_tokens=16,
                messages=[{"role": "user", "content": prompt}],
            )
            score = float(response.content[0].text.strip())
            time.sleep(judge_sleep)
            return max(1.0, min(5.0, score))
        except (ValueError, IndexError):
            return 1.0
        except anthropic.RateLimitError:
            wait = 2**attempt * 5
            print(f"\n  Rate limit — waiting {wait}s...")
            time.sleep(wait)
    return 1.0


def make_reward_fn(judge_model: str, judge_sleep: float):
    try:
        import anthropic  # type: ignore
    except ModuleNotFoundError as e:
        raise SystemExit(
            "ERROR: Missing dependency 'anthropic'. Install with: pip install anthropic"
        ) from e

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    def reward_fn(completions, prompts, **kwargs):
        return [
            judge_completion(prompt, completion, client, judge_model, judge_sleep)
            for prompt, completion in zip(prompts, completions)
        ]

    return reward_fn


def load_prompt_dataset(path: str, tokenizer, max_samples: int | None = None) -> Dataset:
    examples: list[dict] = []
    with open(path) as f:
        for line in f:
            ex = json.loads(line)
            prompt = tokenizer.apply_chat_template(
                ex["messages"][:2],
                tokenize=False,
                add_generation_prompt=True,
            )
            examples.append({"prompt": prompt})

    if max_samples:
        examples = examples[:max_samples]

    print(f"Loaded {len(examples):,} prompts from {path}")
    return Dataset.from_list(examples)


def main() -> None:
    parser = argparse.ArgumentParser(description="GRPO post-training for code review LoRA")
    parser.add_argument("--config", default="rlhf/training/grpo_config.yaml")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ERROR: ANTHROPIC_API_KEY is not set. See .env.example.")

    # Unsloth must be imported before transformers/trl/peft for full patching.
    from unsloth import FastLanguageModel

    _ensure_transformers_cache_symbol()
    from trl import GRPOConfig, GRPOTrainer

    cfg = load_config(args.config)
    model_cfg = cfg["model"]
    lora_cfg = cfg["lora"]
    data_cfg = cfg["data"]
    train_cfg = cfg["training"]
    judge_cfg = cfg["judge"]
    output_cfg = cfg["output"]

    print(f"Loading adapter: {model_cfg['adapter']}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_cfg["adapter"],
        max_seq_length=model_cfg["max_seq_length"],
        dtype=None,
        load_in_4bit=True,
    )

    # If the adapter repo already contains LoRA modules, Unsloth returns a PEFT model.
    # In that case, do not attempt to add LoRA a second time.
    already_lora = bool(getattr(model, "peft_config", None))
    if not already_lora:
        model = FastLanguageModel.get_peft_model(
            model,
            r=lora_cfg["r"],
            lora_alpha=lora_cfg["alpha"],
            lora_dropout=lora_cfg["dropout"],
            target_modules=lora_cfg["target_modules"],
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=train_cfg["seed"],
            init_lora_weights=False,
        )

    train_ds = load_prompt_dataset(
        data_cfg["train_path"],
        tokenizer,
        max_samples=data_cfg.get("max_train_samples"),
    )

    reward_fn = make_reward_fn(
        judge_model=judge_cfg["model"],
        judge_sleep=judge_cfg["sleep_between_calls"],
    )

    grpo_args = GRPOConfig(
        output_dir=output_cfg["dir"],
        num_train_epochs=train_cfg["num_train_epochs"],
        per_device_train_batch_size=train_cfg["per_device_batch_size"],
        gradient_accumulation_steps=train_cfg["gradient_accumulation_steps"],
        learning_rate=train_cfg["learning_rate"],
        num_generations=train_cfg["num_generations"],
        temperature=train_cfg["temperature"],
        max_prompt_length=train_cfg["max_prompt_length"],
        max_completion_length=train_cfg["max_new_tokens"],
        logging_steps=output_cfg["logging_steps"],
        save_steps=output_cfg["save_steps"],
        seed=train_cfg["seed"],
        bf16=True,
        report_to=output_cfg.get("report_to", "none"),
    )

    # TRL GRPO expects this attribute on some model classes.
    # With PEFT wrappers, it may be missing; add a minimal dict to satisfy TRL.
    def _ensure_warnings_issued(m) -> None:
        try:
            getattr(m, "warnings_issued")
            return
        except AttributeError:
            pass
        try:
            setattr(m, "warnings_issued", {})
        except Exception:
            return

    _ensure_warnings_issued(model)
    try:
        base = model.get_base_model()
        _ensure_warnings_issued(base)
    except Exception:
        pass

    trainer = GRPOTrainer(
        model=model,
        args=grpo_args,
        train_dataset=train_ds,
        reward_funcs=reward_fn,
        processing_class=tokenizer,
    )

    print("\nStarting GRPO training...")
    print(f"  Prompts:     {len(train_ds):,}")
    print(f"  Generations: {train_cfg['num_generations']} per prompt")
    print(f"  Judge:       {judge_cfg['model']}")
    print(f"  Output:      {output_cfg['dir']}\n")

    trainer.train()

    final_dir = f"{output_cfg['dir']}/final"
    print(f"\nSaving adapter to {final_dir}...")
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)

    hub_model_id = os.environ.get("GRPO_HUB_MODEL_ID") or output_cfg.get("hub_model_id")
    if hub_model_id:
        print(f"Pushing to Hub: {hub_model_id}")
        model.push_to_hub(hub_model_id)
        tokenizer.push_to_hub(hub_model_id)

    print("Done.")


if __name__ == "__main__":
    main()

