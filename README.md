# code-reviewer

The scope of our project is to create a Code Review Agent that is triggered as a Github Action when a pull request is opened or a new commit is pushed to an existing pull request. 

## Model 
We pick the open source [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) model, the 9B parameters large language model series developed by Qwen team, Alibaba Cloud. 

## Finetuning
We finetune our model on the [CodeReviewer dataset](https://zenodo.org/records/6900648), which contains data for 3 tasks -- Quality Estimation, Comment Generation and Code Refinement. We work with the Comment Generation split. As a finetuning strategy, we use QLoRA (Quantized Low-Rank Adaptation). 

## RAG
We incorporate RAG within our agent in order to obtain more reliable answers, grounded in the codebase. 
When integrating the agent, we chunk the repository using language-aware, recursive splitting by LangChain, which splits at class and function boundaries before falling back to lines splits. Afterwards, we generate embeddings using [nomic-ai/CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed), which we store inside a ChromaDB vector database. At query time, we embed the PR diff and use it as a query against the indexed codebase, retrieving the 5 most relevant code chunks to inject as context into the review prompt.

## End-to-end pipeline
On every PR (`opened` / `synchronize` / `reopened`), `.github/workflows/review.yml`:
1. Spins up the RAG service (`rag/main.py`) as a sidecar.
2. Ingests the PR head into ChromaDB via `rag/scripts/ingest_local.py`.
3. Runs `agentic/entrypoint.py`, which fetches the diff + PR metadata via the GitHub API,
   constructs the task prompt, and calls the smolagents `CodeAgent`.
4. The agent buffers inline findings (`PostCommentTool` / `ProposePatchTool`) and ends
   with `request_changes`, `approve`, or `comment_only`. All findings are submitted as a
   single GitHub review.

### Required secrets
| Secret | Purpose |
| --- | --- |
| `MODEL_API_BASE` | OpenAI-compatible endpoint hosting [`cretu-luca/code-reviewer-grpo`](https://huggingface.co/cretu-luca/code-reviewer-grpo) (e.g. vLLM `serve`, TGI, HF Inference Endpoint, Together) |
| `MODEL_ID` | Model identifier the endpoint expects (e.g. `cretu-luca/code-reviewer-grpo`) |
| `MODEL_API_KEY` | Bearer token for the endpoint, if any |

`GITHUB_TOKEN` is auto-injected by Actions; the workflow asks for `pull-requests: write`.

### Hosting the model
The RLHF'd checkpoint lives at https://huggingface.co/cretu-luca/code-reviewer-grpo. Easiest path:
```bash
vllm serve cretu-luca/code-reviewer-grpo --port 8001
# then point MODEL_API_BASE=http://<host>:8001/v1 and MODEL_ID=cretu-luca/code-reviewer-grpo
```

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
