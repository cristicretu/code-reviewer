"""Ingest a checked-out repository directly into the RAG service.

CI-friendly alternative to ingest_repository.py: walks the local filesystem instead
of hitting the GitHub raw API. Each file is sent as a single snippet (chunking is
deferred to a follow-up).

Env:
  RAG_URL    base URL of the RAG service (default http://localhost:8000)
  REPO_ID    collection identifier (default $GITHUB_REPOSITORY or "default")
  REPO_PATH  filesystem root to walk (default current working directory)
"""

import os
import sys
from pathlib import Path

import requests
from loguru import logger

from config.config_manager import settings


SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".chroma_data",
    "dist",
    "build",
    ".idea",
    ".github",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
MAX_FILE_BYTES = 200_000
BATCH_SIZE = 25


def _iter_files(root: Path, supported_extensions):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(supported_extensions):
                yield Path(dirpath) / fname


def main() -> int:
    rag_url = os.environ.get("RAG_URL", f"http://{settings.DEFAULT.HOST}:{settings.DEFAULT.PORT}").rstrip("/")
    repo_id = os.environ.get("REPO_ID") or os.environ.get("GITHUB_REPOSITORY", "default")
    repo_path = Path(os.environ.get("REPO_PATH", ".")).resolve()
    supported_extensions = tuple(settings.INGESTION.SUPPORTED_EXTENSIONS)

    api_url = f"{rag_url}/api/v1/ingest/{repo_id}"
    logger.info(f"Ingesting {repo_path} into {repo_id} via {api_url}")

    snippets = []
    skipped = 0
    for path in _iter_files(repo_path, supported_extensions):
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            skipped += 1
            continue
        if not content.strip() or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            skipped += 1
            continue
        snippets.append(
            {
                "file_path": str(path.relative_to(repo_path)),
                "content": content,
                "chunk_index": 0,
                "metadata": {"language": path.suffix.lstrip(".") or "text"},
            }
        )

    logger.info(f"Collected {len(snippets)} files (skipped {skipped})")
    if not snippets:
        logger.warning("Nothing to ingest.")
        return 0

    sent = 0
    for i in range(0, len(snippets), BATCH_SIZE):
        batch = snippets[i : i + BATCH_SIZE]
        try:
            r = requests.post(api_url, json={"snippets": batch}, timeout=300)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Batch {i}-{i + len(batch)} failed: {e}")
            return 1
        sent += len(batch)
        logger.info(f"Ingested {sent}/{len(snippets)}")

    logger.success(f"Ingestion complete: {sent} snippets in {repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
