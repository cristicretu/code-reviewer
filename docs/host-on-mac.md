# Host the model on your Mac (demo runbook)

Zero-cost setup for running `cretu-luca/code-reviewer-grpo` on Apple Silicon and exposing
it to the GitHub Action via a public tunnel. Tested on M4 Max / 36 GB.

## 0. Prereqs

```bash
brew install cloudflared
python -m pip install --upgrade pip
pip install mlx-lm huggingface_hub
huggingface-cli login   # only needed if the HF repo is private
```

Quick sanity: at least 16 GB free RAM (you have 36, no problem). Plug in the charger.

## 1. Check if the HF model is merged or adapter-only

mlx-lm needs a *merged* checkpoint. Look at the repo file list:
- Has `model.safetensors` / `model-00001-of-*.safetensors` and `config.json` with the
  full Qwen architecture → **merged**, skip step 2.
- Has `adapter_config.json` + `adapter_model.safetensors` only → **adapter-only**, do step 2.

```bash
huggingface-cli scan-cache  # or just open https://huggingface.co/cretu-luca/code-reviewer-grpo/tree/main
```

## 2. (If adapter-only) Merge once and push back

The repo already ships an export script that merges the LoRA on top of the Qwen base
and pushes a merged checkpoint:

```bash
python -m sft.training.export \
  --adapter cretu-luca/code-reviewer-grpo \
  --format merged \
  --hub-id <your-hf-username>/code-reviewer-grpo-merged
```

From here on, use that merged repo id wherever the doc says `<MODEL_ID>`.

If the model is already merged, `<MODEL_ID> = cretu-luca/code-reviewer-grpo`.

## 3. Convert to MLX 4-bit (one-time, ~5 minutes)

```bash
python -m mlx_lm convert \
  --hf-path <MODEL_ID> \
  --mlx-path ~/models/code-reviewer-grpo-mlx-q4 \
  -q
```

`-q` is 4-bit quantization (~5–6 GB resident, ~30 tok/s on M4 Max). Drop `-q` if you want
bf16 (~18 GB resident, ~12 tok/s). 4-bit is fine for the demo.

## 4. Serve an OpenAI-compatible endpoint

```bash
python -m mlx_lm server \
  --model ~/models/code-reviewer-grpo-mlx-q4 \
  --host 127.0.0.1 \
  --port 8001
```

Smoke test from another terminal:

```bash
curl -s http://127.0.0.1:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "code-reviewer",
    "messages": [{"role":"user","content":"reply with the single word: ready"}],
    "max_tokens": 8
  }' | jq .
```

You should get a `choices[0].message.content` back. If not, fix this before tunnelling.

## 5. Expose it publicly with cloudflared

```bash
cloudflared tunnel --url http://127.0.0.1:8001
```

Watch for the line:

```
Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):
https://random-words-here.trycloudflare.com
```

Copy that URL. The trycloudflare URL changes every time you restart cloudflared, so
**leave this terminal open until after the demo**.

Smoke test the public URL:

```bash
curl -s https://random-words-here.trycloudflare.com/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"code-reviewer","messages":[{"role":"user","content":"ping"}],"max_tokens":4}' | jq .
```

## 6. Wire the secrets into the consumer repo

In the test repo's *Settings → Secrets and variables → Actions*:

| Secret | Value |
| --- | --- |
| `MODEL_API_BASE` | `https://random-words-here.trycloudflare.com/v1` |
| `MODEL_ID` | The model id you used (e.g. `code-reviewer` or the HF id, mlx-lm accepts the served name) |
| `MODEL_API_KEY` | `dummy` (mlx-lm doesn't auth) |

Drop `examples/review.yml` into `.github/workflows/ai-review.yml` in the test repo,
open a PR, watch the Action tab.

## 7. Keep the Mac awake during the demo

In a separate terminal:

```bash
caffeinate -d -i -s
```

Leaves it running until you Ctrl-C. Prevents display sleep, idle sleep, and disk sleep.

## 8. Tear down

After the demo: Ctrl-C the cloudflared process, Ctrl-C the mlx-lm server, Ctrl-C
caffeinate. Nothing else to clean up.

## Troubleshooting

- **`mlx_lm.server` 404 on `/v1/chat/completions`** → upgrade `mlx-lm` (the OpenAI-style
  endpoints landed mid-2024). `pip install -U mlx-lm`.
- **Cloudflared URL works locally but the Action gets 502** → your laptop slept. Run
  `caffeinate -d -i -s` and restart the cloudflared process (note: new URL → update the
  `MODEL_API_BASE` secret).
- **Action times out at 25 minutes** → the agent is looping. Drop `max-agent-steps` to
  `12` in the workflow inputs, or increase the workflow `timeout-minutes`.
- **OOM on the Mac** → use 4-bit (`-q` during convert), close Chrome.
