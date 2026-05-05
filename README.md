# code-reviewer

A code review agent that runs as a GitHub Action on `pull_request` events (`opened`, `synchronize`, `reopened`). On each run it pulls the PR diff, indexes the repository for retrieval, runs an agent loop with a set of investigation tools, and posts one review with inline comments and a verdict (`REQUEST_CHANGES`, `APPROVE`, or `COMMENT`).

## Model

Base model: [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), a 9B-parameter decoder-only causal LLM from Alibaba's Qwen team. For training we load it in 4-bit NF4 with `max_seq_length=2048` and `bf16` compute on an A100 80GB. For inference, the post-RLHF checkpoint [`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo) sits behind any OpenAI-compatible endpoint (vLLM, TGI, HF Inference Endpoints, mlx-lm) and the agent calls it through `LiteLLMModel`.

## Supervised Finetuning

We finetune on the [Microsoft CodeReviewer Comment Generation split](https://zenodo.org/records/6900648), filtering noisy comments (length < 10, generic acks like `lgtm` / `done` / `+1`, bare URLs, formatting-only changes) and converting each `(patch, msg)` pair into a chat-format conversation with a fixed system prompt. Training uses Unsloth + TRL `SFTTrainer` with QLoRA: rank 16, alpha 16, dropout 0, adapters attached to `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`. We run 1 epoch with per-device batch 32, learning rate 2e-4, cosine schedule, AdamW 8-bit, weight decay 0.01, gradient clipping 1.0, bf16. The resulting adapter is published as [`cristicretu/code-reviewer-lora`](https://huggingface.co/cristicretu/code-reviewer-lora).

## RLHF (GRPO)

Starting from the SFT adapter, we run a second training stage with [Group Relative Policy Optimization](https://arxiv.org/abs/2402.03300) using TRL's `GRPOTrainer`. For each prompt we sample 4 completions at temperature 0.8 (`max_prompt_length=512`, `max_completion_length=512`); each completion's reward is normalized against the other 3 in its group, which is what drives the gradient update and removes the need for a separate value network. The reward itself is an LLM-as-judge call to `claude-haiku-4-5-20251001`, which scores the candidate review 1-5 on technical correctness and specificity (real issue / exact location / explanation / concrete fix). We then subtract a length penalty of up to 0.5 for completions over 100 words, so the model is not rewarded for being verbose. Training: 1 epoch over 250 prompts at lr 2e-6, batch 1, gradient accumulation 4, bf16. Output: [`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo).

## RAG

During ingestion we walk the checked-out repository, skipping `.git`, `node_modules`, `.venv`, and build / cache directories, and dropping any file above 200KB. Each file is sent as a snippet (`file_path`, `content`, `chunk_index`, language metadata) to a FastAPI service (`rag/main.py`) in batches of 25. The service writes them to a per-repository collection in a persistent `chromadb.PersistentClient` configured with cosine HNSW. Document IDs are `sha256(repo_id, file_path, chunk_index, content)`, so re-running ingestion on the same content updates the existing entries in place instead of producing duplicates. Embeddings are computed with [`nomic-ai/CodeRankEmbed`](https://huggingface.co/nomic-ai/CodeRankEmbed), loaded through `SentenceTransformer(trust_remote_code=True)` because the model ships a custom `NomicBertModel` head. At query time `SemanticSearchTool` POSTs the agent's query to `/api/v1/retrieve/{repo_id}` and returns the top `k` chunks (default 10, capped at 20) with file path, a `1 - distance` relevance score, and metadata.

## Agent

The agent is a smolagents `CodeAgent` using `LiteLLMModel` (`agentic/agent.py`). The task prompt contains the truncated PR diff, PR metadata, the list of comments already posted on the PR (so the agent does not repeat them), and a catalog of framework-specific playbooks chosen by reading the repository's `package.json`, `pyproject.toml`, `Cargo.toml`, and `go.mod`. The agent runs a tool loop capped at `max-agent-steps` (default 20) and must terminate by calling exactly one verdict tool followed by `final_answer("done")`.

Available tools (`agentic/tools/`):

- **Retrieval** -- `semantic_search` (RAG over the indexed codebase), `search_keyword` (ripgrep), `search_symbol` (AST walk for Python definitions), `get_file` (full file or a line span).
- **Execution** -- `run_tests` (pytest), `run_linter` (ruff), `run_typecheck` (mypy), `run_snippet` (sandboxed Python exec with a 5s timeout).
- **History / context** -- `check_history` (git blame on the touched lines), `get_pr_metadata` (GitHub REST), `get_team_conventions` (reads `.cursorrules`, `CONTRIBUTING.md`, `CLAUDE.md`).
- **Playbooks** -- `load_skill` pulls a framework-specific markdown playbook (`react`, `nextjs`, `vite`, `supabase`, `async-js`) into context on demand. Which playbooks appear in the catalog is decided by triggers in the skill's frontmatter, matched against the repository's manifest files and the diff's file extensions.
- **Action** -- `post_comment(file, line, severity, category, suggestion)`, `propose_patch(file, line, diff)` (a GitHub-style suggested change), and the three verdict tools `request_changes` / `approve` / `comment_only`. The verdict is locked on the first call.

`agentic/review_state.py:ReviewState` buffers the comments, drops any second comment on the same `(file, line)`, enforces `comment-budget` (default 10), and at the end of the run sends one `POST /repos/{repo}/pulls/{pr}/reviews` with all comments and the chosen verdict.

## Local quantization for Apple Silicon

For local evaluation on a Mac (the post-RLHF model is too large to run unquantized on a 24GB M4 Pro), [`quantize/quantize.py`](./quantize/quantize.py) produces a 4-bit GGUF using llama.cpp's upstream toolchain. The pipeline is `convert_hf_to_gguf.py` (HF → GGUF f16) → `convert_lora_to_gguf.py` (PEFT adapter → GGUF LoRA) → `llama-export-lora` (bake adapter into base) → `llama-quantize Q4_K_M` (final ~5.2 GB GGUF). The script also stages a directory so the trained tokenizer + chat template from the GRPO repo end up baked into the GGUF metadata, not the base's. The result is served by `llama-server`, which exposes an OpenAI-compatible endpoint that drops in for `MODEL_API_BASE` with no agent code changes. Full setup, validation steps, and quant comparison are in [`docs/quantize-on-mac.md`](./docs/quantize-on-mac.md). The published quantization lives at [`cretu-luca/code-reviewer-grpo-GGUF`](https://huggingface.co/cretu-luca/code-reviewer-grpo-GGUF).

## Install in your repo (GitHub Action)

This project ships as a composite GitHub Action. To wire it into any repo:

1. **Host the model** somewhere that exposes an OpenAI-compatible endpoint. For a PoC / demo, the simplest path is to serve a Q4_K_M GGUF on a Mac with `llama-server` and tunnel via cloudflared — see [`docs/quantize-on-mac.md`](./docs/quantize-on-mac.md) for the build and [`docs/host-on-mac.md`](./docs/host-on-mac.md) for the tunnel. For production, [HF Inference Endpoints](https://ui.endpoints.huggingface.co/), vLLM/TGI on a GPU box, Together, Fireworks, or Modal all work.

2. **Add three repository secrets** under *Settings → Secrets and variables → Actions*:

   | Secret | Purpose |
   | --- | --- |
   | `MODEL_API_BASE` | OpenAI-compatible endpoint URL hosting [`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo) |
   | `MODEL_ID` | Model identifier the endpoint expects |
   | `MODEL_API_KEY` | Bearer token for the endpoint (use any non-empty string if open) |

3. **Drop this workflow** into the consumer repo at `.github/workflows/ai-review.yml` (full copy in [`examples/review.yml`](./examples/review.yml)):

   ```yaml
   name: AI Code Review
   on:
     pull_request:
       types: [opened, synchronize, reopened]
   permissions:
     contents: read
     pull-requests: write
   jobs:
     review:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
           with:
             ref: ${{ github.event.pull_request.head.sha }}
             fetch-depth: 0
         - uses: cristicretu/code-reviewer@v1
           with:
             model-api-base: ${{ secrets.MODEL_API_BASE }}
             model-id: ${{ secrets.MODEL_ID }}
             model-api-key: ${{ secrets.MODEL_API_KEY }}
   ```

That's it. On every PR open / push, the action: starts the RAG sidecar inside the runner, ingests the PR head into ChromaDB, runs the agent (which calls `semantic_search`, `search_keyword`, `get_file`, `check_history`, `run_tests`, …), buffers findings, and submits **one** batched review with inline comments + a verdict.

### Action inputs

| Input | Required | Default | Description |
| --- | :-: | :-: | --- |
| `model-api-base` | yes | — | OpenAI-compatible endpoint URL |
| `model-id` | yes | — | Model identifier |
| `model-api-key` | no | `dummy` | Bearer token for the endpoint |
| `github-token` | no | `${{ github.token }}` | Token used to fetch the PR & post the review |
| `max-agent-steps` | no | `20` | Hard cap on agent tool-loop iterations |
| `comment-budget` | no | `10` | Max inline comments per PR |
| `python-version` | no | `3.11` | Python used inside the action |

### How it works under the hood

1. Composite action installs deps, starts `rag/main.py` from the action's source.
2. `rag/scripts/ingest_local.py` walks the consumer's checkout and batch-POSTs files into Chroma.
3. `agentic/entrypoint.py` fetches the diff + PR metadata via the GitHub REST API, constructs a task prompt with already-flagged dedup hints, runs the smolagents `CodeAgent`.
4. Action tools (`PostCommentTool` / `ProposePatchTool`) buffer findings into an in-memory `ReviewState`.
5. Verdict tool (`request_changes` / `approve` / `comment_only`) plus `submit()` post one batched review via `POST /repos/{repo}/pulls/{pr}/reviews`.

### Local dry-run

```bash
DYNACONF_APP_PROFILE=dev python -m rag.main &
DYNACONF_APP_PROFILE=dev REPO_ID=local python -m rag.scripts.ingest_local
GITHUB_TOKEN=ghp_... REPO_ID=cristicretu/code-reviewer PR_NUMBER=3 \
  HEAD_SHA=$(git rev-parse HEAD) API_BASE=http://localhost:8001/v1 \
  MODEL_ID=cretu-luca/code-reviewer-grpo \
  python -m agentic.entrypoint
```

## Team
Name of the team is Messi. Members are (alphabetically) Cretu Cristian, Cretu Luca, Greholea Denis, Gosa Bogdan, Hiticas Paul.
