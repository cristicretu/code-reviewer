"""Ingest a checked-out repository directly into the RAG service.

CI-friendly alternative to ingest_repository.py: walks the local filesystem instead
of hitting the GitHub raw API. Each file is split into overlapping line-window
chunks before ingestion, so retrieval can match a specific function/region rather
than the whole file (which would dilute the embedding).

Env:
  RAG_URL          base URL of the RAG service (default http://localhost:8000)
  REPO_ID          collection identifier (default $GITHUB_REPOSITORY or "default")
  REPO_PATH        filesystem root to walk (default current working directory)
  CHUNK_LINES      lines per chunk (default 60; 0 disables chunking)
  CHUNK_OVERLAP    lines of overlap between adjacent chunks (default 10)
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


def _chunk_lines(content: str, chunk_lines: int, overlap: int):
    """Yield (chunk_index, start_line_1based, chunk_text) windows over `content`.

    If chunk_lines <= 0 the whole file is returned as a single chunk."""
    lines = content.splitlines(keepends=True)
    if chunk_lines <= 0 or len(lines) <= chunk_lines:
        yield 0, 1, content
        return
    step = max(1, chunk_lines - overlap)
    idx = 0
    start = 0
    while start < len(lines):
        end = min(start + chunk_lines, len(lines))
        yield idx, start + 1, "".join(lines[start:end])
        idx += 1
        if end >= len(lines):
            break
        start += step


def main() -> int:
    rag_url = os.environ.get("RAG_URL", f"http://{settings.DEFAULT.HOST}:{settings.DEFAULT.PORT}").rstrip("/")
    repo_id = os.environ.get("REPO_ID") or os.environ.get("GITHUB_REPOSITORY", "default")
    repo_path = Path(os.environ.get("REPO_PATH", ".")).resolve()
    supported_extensions = tuple(settings.INGESTION.SUPPORTED_EXTENSIONS)
    chunk_lines = int(os.environ.get("CHUNK_LINES", "60"))
    chunk_overlap = int(os.environ.get("CHUNK_OVERLAP", "10"))

    api_url = f"{rag_url}/api/v1/ingest/{repo_id}"
    logger.info(
        f"Ingesting {repo_path} into {repo_id} via {api_url} "
        f"(chunk_lines={chunk_lines}, overlap={chunk_overlap})"
    )

    snippets = []
    skipped = 0
    n_files = 0
    for path in _iter_files(repo_path, supported_extensions):
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            skipped += 1
            continue
        if not content.strip() or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            skipped += 1
            continue
        n_files += 1
        rel = str(path.relative_to(repo_path))
        for idx, start_line, chunk_text in _chunk_lines(content, chunk_lines, chunk_overlap):
            snippets.append(
                {
                    "file_path": rel,
                    "content": chunk_text,
                    "chunk_index": idx,
                    "metadata": {
                        "language": path.suffix.lstrip(".") or "text",
                        "start_line": start_line,
                    },
                }
            )

    logger.info(f"Collected {len(snippets)} chunks across {n_files} files (skipped {skipped})")
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
