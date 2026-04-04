"""Export the fine-tuned LoRA adapter to various formats.

Supports:
    - Merged safetensors (full model with LoRA merged)
    - GGUF for llama.cpp inference
    - HuggingFace Hub upload

Usage:
    python -m sft.training.export --adapter outputs/sft/final --format gguf
    python -m sft.training.export --adapter outputs/sft/final --format merged
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Export fine-tuned model")
    parser.add_argument("--adapter", required=True, help="Path to LoRA adapter dir")
    parser.add_argument(
        "--format",
        choices=["gguf", "merged", "both"],
        default="both",
    )
    parser.add_argument("--output-dir", default="models/")
    parser.add_argument("--quantization", default="q4_k_m",
                        help="GGUF quantization method (default: q4_k_m)")
    parser.add_argument("--hub-id", default=None, help="HuggingFace Hub model ID")
    args = parser.parse_args()

    from unsloth import FastLanguageModel
    from pathlib import Path

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading adapter from {args.adapter}...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter,
        max_seq_length=4096,
        dtype=None,
        load_in_4bit=True,
    )

    if args.format in ("merged", "both"):
        merged_dir = output_dir / "merged"
        print(f"Saving merged model to {merged_dir}...")
        model.save_pretrained_merged(
            str(merged_dir),
            tokenizer,
            save_method="merged_16bit",
        )
        print("Merged model saved.")

    if args.format in ("gguf", "both"):
        gguf_dir = output_dir / "gguf"
        print(f"Exporting GGUF ({args.quantization}) to {gguf_dir}...")
        model.save_pretrained_gguf(
            str(gguf_dir),
            tokenizer,
            quantization_method=args.quantization,
        )
        print("GGUF export complete.")

    if args.hub_id:
        print(f"Pushing to HuggingFace Hub: {args.hub_id}")
        model.push_to_hub_merged(
            args.hub_id,
            tokenizer,
            save_method="merged_16bit",
        )
        print("Pushed to Hub.")

    print("Export complete!")


if __name__ == "__main__":
    main()
