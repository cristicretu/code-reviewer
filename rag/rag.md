# RAG Code Reviewer API

A high-performance, Dockerized RAG (Retrieval-Augmented Generation) API service designed specifically for code review tools. It leverages FastAPI for the REST interface and ChromaDB for semantic retrieval of code snippets.

## Features
- **Repository Isolation:** Each repository is stored in its own isolated ChromaDB collection.
- **Semantic Retrieval:** Uses `nomic-ai/CodeRankEmbed` locally for high-quality embedding generation without external API dependencies.
- **FastAPI Backend:** Fully typed request/response models using Pydantic.
- **Persistent Storage:** Data is persisted in a local volume, ensuring durability across container restarts.
- **Modern Python Tooling:** Managed with `uv` for lightning-fast dependency resolution and deterministic builds.
- 
## Local Development (using `uv`)
1. **Install Dependencies:**
   ```bash
   uv sync
   ```
2. **Run the API:**
   ```bash
   uv run uvicorn rag.main:application --reload
   ```
3. **Run Tests:**
   ```bash
   uv run pytest
   ```

## API Endpoints

### 1. Ingestion (`POST /ingest/{repo_id}`)
Processes and stores code snippets for a specific repository.
- **Payload:**
  ```json
  {
    "snippets": [
      {
        "file_path": "src/utils.py",
        "content": "def sum(a, b): return a + b",
        "metadata": {"lang": "python"}
      }
    ],
    "branch": "main"
  }
  ```

### 2. Retrieval (`POST /retrieve/{repo_id}`)
Retrieves the most semantically relevant code chunks from a specific repository.
- **Payload:**
  ```json
  {
    "query": "How can I add numbers?",
    "max_results": 3
  }
  ```

### 3. Health Check (`GET /health`)
Verifies the operational status of the service.

## Configuration
The application is configured via environment variables (see `config/config.dev.yaml`)

