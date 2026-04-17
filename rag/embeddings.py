from loguru import logger
from chromadb.utils import embedding_functions
from config.config_manager import settings

def get_huggingface_embedding_function():
    logger.info(f"Loading embedding model: {settings.EMBEDDINGS.MODEL_NAME}")
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=settings.EMBEDDINGS.MODEL_NAME
    )


embedding_service = get_huggingface_embedding_function()
