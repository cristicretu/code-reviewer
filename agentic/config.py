import os
from dotenv import load_dotenv

load_dotenv("agentic/.env", override=True)

API_BASE = os.environ.get("API_BASE", "http://localhost:1234/v1")
MODEL_ID = os.environ.get("MODEL_ID", "model")
if not MODEL_ID.startswith("openai/"):
    MODEL_ID = f"openai/{MODEL_ID}"

if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = "dummy"
