from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from loguru import logger
from sentence_transformers import SentenceTransformer

from config.config_manager import settings


class TrustedSentenceTransformerEmbedding(EmbeddingFunction):
    """Wraps SentenceTransformer with trust_remote_code=True so we can use
    custom-architecture embedders like nomic-ai/CodeRankEmbed under modern
    transformers/sentence-transformers releases.
    """

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model = SentenceTransformer(model_name, trust_remote_code=True)

    def name(self) -> str:
        return f"trusted-st:{self._model_name}"

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = self._model.encode(list(input), show_progress_bar=False)
        return embeddings.tolist()


def get_huggingface_embedding_function():
    logger.info(f"Loading embedding model: {settings.EMBEDDINGS.MODEL_NAME}")
    return TrustedSentenceTransformerEmbedding(settings.EMBEDDINGS.MODEL_NAME)


embedding_service = get_huggingface_embedding_function()
