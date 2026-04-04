"""LoRA SFT fine-tuning with Unsloth on Qwen3.5-9B.

Run on a cloud A100 80GB (RunPod):
    python -m sft.training.sft [--config sft/training/config.yaml]

Prerequisites:
    - Run setup_cloud.sh first to install Unsloth
    - Run the data pipeline to produce data/processed/train.jsonl
"""

import argparse
import json
from pathlib import Path

import yaml
from datasets import Dataset
from trl import SFTTrainer, SFTConfig


def load_config(config_path: str = "sft/training/config.yaml") -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_chat_dataset(path: str) -> Dataset:
    """Load a JSONL file of chat-format conversations into a HF Dataset."""
    examples = []
    with open(path) as f:
        for line in f:
            examples.append(json.loads(line))
    return Dataset.from_list(examples)


def main():
    parser = argparse.ArgumentParser(description="SFT fine-tuning with Unsloth")
    parser.add_argument("--config", default="sft/training/config.yaml")
    parser.add_argument("--small-run", action="store_true",
                        help="Train on 1K examples for pipeline validation")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # --- Load model with Unsloth ---
    from unsloth import FastLanguageModel

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg["model"]["name"],
        max_seq_length=cfg["model"]["max_seq_length"],
        dtype=cfg["model"]["dtype"],
        load_in_4bit=cfg["model"]["load_in_4bit"],
    )

    # --- Apply LoRA ---
    lora_cfg = cfg["lora"]
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_cfg["r"],
        lora_alpha=lora_cfg["alpha"],
        lora_dropout=lora_cfg["dropout"],
        target_modules=lora_cfg["target_modules"],
        bias="none",
        use_gradient_checkpointing="unsloth",  # Unsloth optimized
        random_state=cfg["training"]["seed"],
    )

    # --- Load data ---
    train_ds = load_chat_dataset(cfg["data"]["train_path"])
    val_ds = load_chat_dataset(cfg["data"]["val_path"])

    if args.small_run:
        train_ds = train_ds.select(range(min(1000, len(train_ds))))
        val_ds = val_ds.select(range(min(100, len(val_ds))))
        print(f"Small run: {len(train_ds)} train, {len(val_ds)} val")

    print(f"Training on {len(train_ds):,} examples, validating on {len(val_ds):,}")

    # --- Formatting function ---
    def formatting_func(examples):
        """Convert chat messages to the model's chat template format."""
        texts = []
        for messages in examples["messages"]:
            text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False
            )
            texts.append(text)
        return {"text": texts}

    train_ds = train_ds.map(formatting_func, batched=True, remove_columns=["messages"])
    val_ds = val_ds.map(formatting_func, batched=True, remove_columns=["messages"])

    # --- Training config ---
    tcfg = cfg["training"]
    output_dir = cfg["output"]["dir"]

    # Get the actual EOS token from the tokenizer (TRL defaults to a bad placeholder)
    eos_token = tokenizer.eos_token
    print(f"Using EOS token: {repr(eos_token)}")

    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=tcfg["num_epochs"],
        per_device_train_batch_size=tcfg["per_device_batch_size"],
        gradient_accumulation_steps=tcfg["gradient_accumulation_steps"],
        learning_rate=tcfg["learning_rate"],
        lr_scheduler_type=tcfg["lr_scheduler"],
        warmup_ratio=tcfg["warmup_ratio"],
        weight_decay=tcfg["weight_decay"],
        max_grad_norm=tcfg["max_grad_norm"],
        fp16=tcfg["fp16"],
        bf16=tcfg["bf16"],
        seed=tcfg["seed"],
        logging_steps=tcfg["logging_steps"],
        save_steps=tcfg["save_steps"],
        save_total_limit=tcfg["save_total_limit"],
        eval_strategy="steps",
        eval_steps=tcfg["save_steps"],
        max_length=cfg["model"]["max_seq_length"],
        dataset_text_field="text",
        packing=True,  # Unsloth efficient packing
        eos_token=eos_token,
        report_to="none",  # change to "wandb" if using W&B
    )

    # --- Train ---
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        args=training_args,
    )

    print("Starting training...")
    trainer.train()

    # --- Save ---
    print(f"Saving LoRA adapter to {output_dir}/final...")
    model.save_pretrained(f"{output_dir}/final")
    tokenizer.save_pretrained(f"{output_dir}/final")

    # Optionally push to Hub
    hub_id = cfg["output"].get("hub_model_id")
    if hub_id:
        print(f"Pushing to HuggingFace Hub: {hub_id}")
        model.push_to_hub(hub_id)
        tokenizer.push_to_hub(hub_id)

    print("Training complete!")


if __name__ == "__main__":
    main()
