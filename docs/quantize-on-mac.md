# Quantize and run locally on Apple Silicon

This document covers producing a 4-bit GGUF of the post-RLHF checkpoint
[`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo)
and serving it on a Mac via `llama-server`. The full pipeline is implemented
in [`quantize/quantize.py`](../quantize/quantize.py); this doc explains the
choices and the validation steps.

## Target hardware

A 14" MacBook Pro with the base **M4 Pro / 24 GB unified memory** SKU is the
worst-case target — anything bigger has more headroom. All numbers below
assume that machine.

## Quantization choice: Q4_K_M

| Format  | On-disk | Resident RAM at runtime | Quality |
|---------|--------:|------------------------:|---------|
| bf16    | ~17 GB  | ~19 GB                  | reference |
| Q8_0    |  ~9 GB  | ~10 GB                  | near-lossless |
| **Q4_K_M** | **~5.2 GB** | **~6.5 GB**       | **target** |
| Q4_K_S  | ~4.9 GB | ~6 GB                   | slightly worse than Q4_K_M |

`Q4_K_M` was chosen because:

1. **Memory budget.** Q8_0 leaves ~10 GB for KV cache + macOS + IDE +
   browser on a 24 GB machine, which trips swap under realistic load.
   Q4_K_M leaves comfortable headroom.
2. **Quality.** Unlike uniform Q4 quantization, K-quants are mixed-precision:
   Q4_K_M stores attention output and FFN-down in Q6_K and the rest in Q4_K.
   On Mac perplexity benchmarks the gap to bf16 is small.
3. **Training fit.** The model was QLoRA-trained at NF4 (per the SFT recipe),
   so it is natively tolerant of 4-bit inference.

## Pipeline

Every step is delegated to a battle-tested upstream tool from
[`ggml-org/llama.cpp`](https://github.com/ggerganov/llama.cpp). The script
just orchestrates and stages files.

```
  HF safetensors ──► convert_hf_to_gguf.py    ──► base-f16.gguf
  PEFT adapter   ──► convert_lora_to_gguf.py  ──► grpo-lora.gguf
  base + lora    ──► llama-export-lora        ──► grpo-fused-f16.gguf
  fused          ──► llama-quantize Q4_K_M    ──► code-reviewer-grpo-Q4_K_M.gguf
```

One thing the script does itself: it stages an HF-style directory whose
weights/config come from the base (`Qwen/Qwen3.5-9B`) but whose tokenizer
and `chat_template.jinja` come from the GRPO adapter. The chat template
the model was trained with thereby ends up baked into the GGUF metadata.

## Setup (one-time)

```bash
# llama-quantize, llama-server, llama-cli (Homebrew formula)
brew install llama.cpp

# llama-export-lora is not in the brew formula, build it from source
git clone https://github.com/ggerganov/llama.cpp ./.quantize-work/llama.cpp-src
cmake -S .quantize-work/llama.cpp-src \
      -B .quantize-work/llama.cpp-src/build \
      -DGGML_METAL=ON
cmake --build .quantize-work/llama.cpp-src/build \
      --target llama-export-lora -j

# Python deps for the convert_*.py scripts
uv pip install --index-strategy unsafe-best-match \
  -r .quantize-work/llama.cpp-src/requirements.txt
```

The script auto-discovers `llama-export-lora` under
`.quantize-work/llama.cpp-src/build/bin/` if it's not on `PATH`.

## Run

```bash
uv run python quantize/quantize.py
# default: Q4_K_M -> ./code-reviewer-grpo-Q4_K_M.gguf

uv run python quantize/quantize.py --quant Q5_K_M   # ~6.5 GB, better quality
uv run python quantize/quantize.py --quant Q8_0     # ~9.5 GB, near-lossless
uv run python quantize/quantize.py --keep-intermediate  # keep the f16 fused GGUF for re-quantization
```

Wall clock on M4 Pro: ~10 min total (dominated by I/O).

| Step | Wall clock | Peak RAM | Disk delta |
|------|-----------:|---------:|-----------:|
| `convert_hf_to_gguf.py` (f16)   | 3–5 min | ~6 GB | +18 GB |
| `convert_lora_to_gguf.py`       | <30 s   | <1 GB | +0.15 GB |
| `llama-export-lora`             | ~2 min  | ~6 GB | peak +18 GB, then -18 GB after cleanup |
| `llama-quantize Q4_K_M`         | ~40 s   | ~10 GB | +5.2 GB final, -18 GB after cleanup |

Peak free disk required: **~40 GB** (briefly, during `llama-export-lora`).
Final on-disk artifact: **~5.2 GB**.

## Validation

### 1. Smoke test through `llama-cli`

```bash
llama-cli -m code-reviewer-grpo-Q4_K_M.gguf -ngl 999 --jinja \
  -p "Review this diff in one sentence:
+ def add(a, b): return a - b" \
  -n 400 --temp 0.2 -no-cnv
```

Reasoning + draft answer should appear within 400 tokens. Typical generation
speed on M4 Pro: ~34 t/s decode, ~78 t/s prompt.

### 2. End-to-end through the OpenAI-compatible server

The agent talks to the model via `llama-server`, which applies the
GGUF-baked chat template and splits reasoning out into `reasoning_content`:

```bash
llama-server -m code-reviewer-grpo-Q4_K_M.gguf \
             --port 8080 --host 127.0.0.1 --jinja \
             -c 4096 -ngl 999
```

Confirm with the **trained system prompt** (see `sft/data/preprocess.py`) — without
it, reasoning models drift off-distribution and can stall in a redraft loop.

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model":"code-reviewer-grpo-Q4_K_M",
    "messages":[
      {"role":"system","content":"You are an expert code reviewer. Given a code diff, provide a concise, actionable review comment. Focus on:\n- Bugs and logic errors\n- Security vulnerabilities\n- Performance issues\n- Code style and best practices\n\nBe specific: reference the exact code that needs changing and explain why. If the code looks correct, say so briefly."},
      {"role":"user","content":"+ def add(a, b): return a - b"}
    ],
    "max_tokens":1024,
    "temperature":0.2
  }' | jq '.choices[0].message'
```

Healthy response shape:

```json
{
  "role": "assistant",
  "content": "This function is named `add` but it performs subtraction. I think this is a bug.",
  "reasoning_content": "..."
}
```

Two things to watch for, both observed during validation:

- **`max_tokens` too low.** Reasoning models need headroom — set at least
  1024. Below that, generation can terminate inside the thinking block and
  return an empty `content`.
- **No system prompt.** Without the trained system prompt, the model can
  enter a self-second-guessing redraft loop and never close the thinking
  block. Always send the SFT system prompt; the agent does this by default.

## Serving the agent against the local model

```bash
llama-server -m code-reviewer-grpo-Q4_K_M.gguf --port 8080 --jinja -c 4096 -ngl 999

export MODEL_API_BASE=http://localhost:8080/v1
export MODEL_API_KEY=anything
export MODEL_ID=code-reviewer-grpo-Q4_K_M
```

The agent then runs unmodified — `llama-server`'s `/v1/chat/completions` is
a drop-in for the OpenAI endpoint listed in the README.

## Publishing the GGUF to Hugging Face

```bash
hf auth login

hf repo create code-reviewer-grpo-GGUF --repo-type model -y

hf upload cretu-luca/code-reviewer-grpo-GGUF \
  ./code-reviewer-grpo-Q4_K_M.gguf \
  code-reviewer-grpo-Q4_K_M.gguf
```

Recommended convention: publish under `<owner>/<source-repo>-GGUF`, one
file per quant level. Add a model card linking back to
`cretu-luca/code-reviewer-grpo` and naming the llama.cpp build used.
