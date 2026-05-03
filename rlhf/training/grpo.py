import anthropic 
import yaml
import time
import json
import os
import concurrent.futures as futures

from unsloth import FastLanguageModel
from trl import GRPOConfig, GRPOTrainer
from anthropic.types import TextBlock
from datasets import Dataset
from functools import partial

JUDGE_PROMPT = """\
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
"""

_JUDGE_POOL = futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="judge")

def load_config(path: str = "rlhf/training/grpo_config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def get_judge_score(diff, comment, client, judge_model, judge_sleep, max_attempts=4):
    prompt = JUDGE_PROMPT.format(diff=diff, comment=comment)
    for attempt in range(max_attempts):
        try:
            response = client.messages.create(
                model=judge_model, max_tokens=16,
                messages=[{"role": "user", "content": prompt}],
            )
            block = response.content[0]
            if not isinstance(block, TextBlock):
                return 1.0
            try:
                score = float(block.text.strip())
            except ValueError:
                return 1.0
            time.sleep(judge_sleep)
            
            word_count = len(comment.split())
            penalty = min(0.5, max(0.0, (word_count - 100) / 100) * 0.5)

            return max(1.0, min(5.0, score) - penalty)

        except anthropic.RateLimitError:
            time.sleep(2 ** attempt * 5)
        except (anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.InternalServerError):
            time.sleep(2 ** attempt * 2)
    return 1.0

def get_reward_fn(completions, prompts, client, judge_model, judge_sleep, **kwargs):
    jobs = [
        _JUDGE_POOL.submit(get_judge_score, p, c, client, judge_model, judge_sleep)
        for p, c in zip(prompts, completions)
    ]
    return [j.result() for j in jobs]

def load_dataset(path: str, tokenizer, max_samples: int | None) -> Dataset:
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ERROR: ANTHROPIC_API_KEY is not set.")

    config = load_config()

    model_config = config["model"]
    data_config = config["data"]
    train_config = config["training"]
    judge_config = config["judge"]
    output_config = config["output"]

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_config["adapter"], 
        max_seq_length=model_config["max_seq_length"],
        dtype=None,
        load_in_4bit=True,
    )

    train_ds = load_dataset(
        data_config["train_path"],
        tokenizer,
        max_samples=data_config.get("max_train_samples"),
    )

    client = anthropic.Anthropic()

    reward_fn = partial(
        get_reward_fn,
        client=client,
        judge_model=judge_config["model"],
        judge_sleep=judge_config["sleep_between_calls"],
    )

    grpo_args = GRPOConfig(
        output_dir=output_config["dir"],
        num_train_epochs=train_config["num_train_epochs"],
        per_device_train_batch_size=train_config["per_device_batch_size"],
        gradient_accumulation_steps=train_config["gradient_accumulation_steps"],
        learning_rate=train_config["learning_rate"],
        num_generations=train_config["num_generations"],
        temperature=train_config["temperature"],
        max_prompt_length=train_config["max_prompt_length"],
        max_completion_length=train_config["max_new_tokens"],
        logging_steps=output_config["logging_steps"],
        save_steps=output_config["save_steps"],
        seed=train_config["seed"],
        bf16=True,
        report_to=output_config.get("report_to", "none"),
    )

    trainer = GRPOTrainer(
        model=model,
        args=grpo_args,
        train_dataset=train_ds,
        reward_funcs=reward_fn,
        processing_class=tokenizer,
    )

    trainer.train()

    final_dir = f"{output_config['dir']}/final"

    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)

    hub_model_id = os.environ.get("GRPO_HUB_MODEL_ID") or output_config.get("hub_model_id")
    if hub_model_id:
        print(f"Pushing to Hub: {hub_model_id}")
        model.push_to_hub(hub_model_id)
        tokenizer.push_to_hub(hub_model_id)

if __name__ == "__main__":
    main()