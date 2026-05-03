# code-reviewer

A code review agent that runs as a GitHub Action on `pull_request` events (`opened`, `synchronize`, `reopened`). It fetches the PR diff and metadata through the GitHub REST API, retrieves grounding context from the repository via a local RAG sidecar, drives a tool-using agent loop to investigate the changes, and submits a single batched review with inline comments and one verdict (`REQUEST_CHANGES`, `APPROVE`, or `COMMENT`).

## Model

Base model: [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), a 9B-parameter decoder-only causal LLM from Alibaba's Qwen team. During training the base is loaded in 4-bit NF4 with `max_seq_length=2048` and `bf16` compute on an A100 80GB. At inference the post-RLHF checkpoint [`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo) is served behind any OpenAI-compatible endpoint (vLLM, TGI, HF Inference Endpoints, mlx-lm) and the agent talks to it through `LiteLLMModel`.

## Supervised Finetuning

We finetune on the [Microsoft CodeReviewer Comment Generation split](https://zenodo.org/records/6900648), filtering noisy comments (length < 10, generic acks like `lgtm` / `done` / `+1`, bare URLs, formatting-only changes) and converting each `(patch, msg)` pair into a chat-format conversation with a fixed system prompt. Training uses Unsloth + TRL `SFTTrainer` with QLoRA: rank 16, alpha 16, dropout 0, adapters attached to `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`. We run 1 epoch with per-device batch 32, learning rate 2e-4, cosine schedule, AdamW 8-bit, weight decay 0.01, gradient clipping 1.0, bf16. The resulting adapter is published as [`cristicretu/code-reviewer-lora`](https://huggingface.co/cristicretu/code-reviewer-lora).

## RLHF (GRPO)

Starting from the SFT adapter, we further align the policy with [Group Relative Policy Optimization](https://arxiv.org/abs/2402.03300) using TRL's `GRPOTrainer`. For each prompt we sample 4 completions at temperature 0.8 (`max_prompt_length=512`, `max_completion_length=512`); the relative reward of each completion within its group is what drives the gradient update, removing the need for a separate value network. The reward signal is an LLM-as-judge call to `claude-haiku-4-5-20251001`, which scores the candidate review 1-5 on technical correctness and specificity (real issue / exact location / explanation / concrete fix). A length penalty of up to 0.5 is subtracted for completions over 100 words so the policy does not reward-hack via verbosity. Training: 1 epoch over 250 prompts at lr 2e-6, batch 1, gradient accumulation 4, bf16. Output: [`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo).

## RAG

At ingestion the consumer repo is walked from the runner checkout, skipping `.git`, `node_modules`, `.venv`, and build / cache directories, and dropping any file above 200KB. Each file is sent as a snippet (`file_path`, `content`, `chunk_index`, language metadata) to a FastAPI sidecar (`rag/main.py`) in batches of 25. The service writes them to a per-repository collection in a persistent `chromadb.PersistentClient` configured with cosine HNSW; document IDs are `sha256(repo_id, file_path, chunk_index, content)` so re-ingestion is idempotent. Embeddings are computed with [`nomic-ai/CodeRankEmbed`](https://huggingface.co/nomic-ai/CodeRankEmbed), loaded through `SentenceTransformer(trust_remote_code=True)` because the model ships a custom `NomicBertModel` head. At query time `SemanticSearchTool` POSTs the agent's query to `/api/v1/retrieve/{repo_id}` and returns the top `k` chunks (default 10, capped at 20) with file path, a `1 - distance` relevance score, and metadata.

## Agent

The agent is a smolagents `CodeAgent` driven by `LiteLLMModel` (`agentic/agent.py`). It is given a task prompt containing the truncated PR diff, PR metadata, the list of already-flagged comments (for dedup), and a catalog of framework-specific playbooks selected against the consumer repo's manifest files. It iterates a ReAct-style tool loop bounded by `max-agent-steps` (default 20) and must terminate by calling exactly one verdict tool followed by `final_answer("done")`.

Available tools (`agentic/tools/`):

- **Retrieval** -- `semantic_search` (RAG over the indexed codebase), `search_keyword` (ripgrep), `search_symbol` (AST walk for Python definitions), `get_file` (full file or a line span).
- **Execution** -- `run_tests` (pytest), `run_linter` (ruff), `run_typecheck` (mypy), `run_snippet` (sandboxed Python exec with a 5s timeout).
- **History / context** -- `check_history` (git blame on the touched lines), `get_pr_metadata` (GitHub REST), `get_team_conventions` (reads `.cursorrules`, `CONTRIBUTING.md`, `CLAUDE.md`).
- **Playbooks** -- `load_skill` pulls a framework-specific markdown playbook (`react`, `nextjs`, `vite`, `supabase`, `async-js`) into context on demand, gated by triggers in the skill's frontmatter (matched against `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, and the diff's file extensions).
- **Action** -- `post_comment(file, line, severity, category, suggestion)`, `propose_patch(file, line, diff)` (GitHub-style suggested change), and the three first-call-wins verdict tools `request_changes` / `approve` / `comment_only`.

`agentic/review_state.py:ReviewState` buffers comments, dedupes by `(file, line)`, enforces `comment-budget` (default 10), and on completion submits a single `POST /repos/{repo}/pulls/{pr}/reviews` payload with all comments and the chosen verdict.

## Install in your repo (GitHub Action)

This project ships as a composite GitHub Action. To wire it into any repo:

1. **Host the model** somewhere that exposes an OpenAI-compatible endpoint. For a PoC / demo, the simplest path is to serve it on a Mac with mlx-lm and tunnel via cloudflared — see [`docs/host-on-mac.md`](./docs/host-on-mac.md). For production, [HF Inference Endpoints](https://ui.endpoints.huggingface.co/), vLLM/TGI on a GPU box, Together, Fireworks, or Modal all work.

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
