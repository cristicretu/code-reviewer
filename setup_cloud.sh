#!/bin/bash
# ============================================================
# Cloud GPU Setup Script for RunPod A100
# ============================================================
#
# This script sets up the training environment on a RunPod pod.
# Run this ONCE after SSH-ing into your pod.
#
# Usage:
#   chmod +x setup_cloud.sh && ./setup_cloud.sh
#
# Prerequisites:
#   - RunPod pod with A100 80GB GPU
#   - Template: "RunPod PyTorch 2.4" (or similar with CUDA 12.x)
# ============================================================

set -e

echo "=========================================="
echo "Setting up SFT training environment"
echo "=========================================="

# Check GPU
echo ""
echo "GPU Info:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# Install Unsloth (their recommended install for CUDA 12.x + PyTorch 2.4+)
echo "Installing Unsloth..."
pip install --upgrade pip
pip install unsloth
# Unsloth installs its own optimized versions of transformers, trl, etc.

# Install remaining dependencies
echo "Installing project dependencies..."
pip install datasets huggingface-hub safetensors sentencepiece
pip install pyyaml tqdm pandas requests
pip install sacrebleu rouge-score bert-score
pip install code-bert-score

# Optional: Anthropic SDK for LLM-as-judge eval
pip install anthropic

# RLHF / GRPO dependencies (needed by TRL GRPO trainer import path)
pip install mergekit llm-blender weave

# Clone repo (if not already done)
if [ ! -d "code-reviewer" ]; then
    echo ""
    echo "NOTE: Clone your repo manually:"
    echo "  git clone <your-repo-url> code-reviewer"
    echo "  cd code-reviewer"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. cd code-reviewer"
echo "  2. python -m sft.data.download           # Download CodeReviewer dataset"
echo "  3. python -m sft.data.download_labels     # Download Zenodo labels"
echo "  4. python -m sft.data.filter              # Filter to valid examples"
echo "  5. python -m sft.data.preprocess          # Convert to SFT format"
echo "  6. python -m sft.data.split               # Train/val/test split"
echo "  7. python -m sft.training.sft --small-run # Sanity check on 1K examples"
echo "  8. python -m sft.training.sft             # Full training (~1-2 hours)"
echo "  9. python -m sft.eval.run_eval --model outputs/sft/final"
echo " 10. source .env    # Set ANTHROPIC_API_KEY for GRPO"
echo " 11. python -m rlhf.training.grpo"
echo ""
