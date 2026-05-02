# code-reviewer

The scope of our project is to create a Code Review Agent that is triggered as a Github Action when a pull request is opened or a new commit is pushed to an existing pull request. 

## Model 
We pick the open source [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) model, the 9B parameters large language model series developed by Qwen team, Alibaba Cloud. 

## Finetuning
We finetune our model on the [CodeReviewer dataset](https://zenodo.org/records/6900648), which contains data for 3 tasks -- Quality Estimation, Comment Generation and Code Refinement. We work with the Comment Generation split. As a finetuning strategy, we use QLoRA (Quantized Low-Rank Adaptation). 

## RAG
We incorporate RAG within our agent in order to obtain more reliable answers, grounded in the codebase. 
When integrating the agent, we chunk the repository using language-aware, recursive splitting by LangChain, which splits at class and function boundaries before falling back to lines splits. Afterwards, we generate embeddings using [nomic-ai/CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed), which we store inside a ChromaDB vector database. At query time, we embed the PR diff and use it as a query against the indexed codebase, retrieving the 5 most relevant code chunks to inject as context into the review prompt.

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
