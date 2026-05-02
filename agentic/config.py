import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)

API_BASE = os.environ.get("API_BASE", "http://localhost:1234/v1")
MODEL_ID = os.environ.get("MODEL_ID", "model")
if not MODEL_ID.startswith("openai/"):
    MODEL_ID = f"openai/{MODEL_ID}"

if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = "dummy"

RAG_URL = os.environ.get("RAG_URL", "http://localhost:8000").rstrip("/")
REPO_ID = os.environ.get("REPO_ID") or os.environ.get("GITHUB_REPOSITORY", "default_repo")
os.environ.setdefault("REPO_ID", REPO_ID)

MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "20"))
COMMENT_BUDGET = int(os.environ.get("COMMENT_BUDGET", "10"))
