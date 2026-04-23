from loguru import logger
import chromadb
import re
from config.config_manager import settings
from rag.embeddings import embedding_service

class RepositoryVectorDatabase:
    def __init__(self):
        logger.info(f"Connecting to ChromaDB at: {settings.CHROMA.PERSIST_PATH}")
        self.client = chromadb.PersistentClient(path=settings.CHROMA.PERSIST_PATH)
        self.embedding_function = embedding_service

    def sanitize_repository_identifier(self, repository_id: str) -> str:
        sanitized_name = re.sub(r"[^a-zA-Z0-9_-]", "-", repository_id)
        if len(sanitized_name) < 3:
            sanitized_name = f"collection-{sanitized_name}"
        if len(sanitized_name) > 63:
            sanitized_name = sanitized_name[:63]
        if not sanitized_name[0].isalnum():
            sanitized_name = f"r{sanitized_name[1:]}"
        if not sanitized_name[-1].isalnum():
            sanitized_name = f"{sanitized_name[:-1]}z"
        return sanitized_name

    def get_collection_for_repository(self, repository_id: str):
        collection_name = self.sanitize_repository_identifier(repository_id)
        logger.debug(f"Retrieving or creating collection: {collection_name} for repository: {repository_id}")
        return self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}
        )

    def retrieve_collection_for_repository(self, repository_id: str):
        collection_name = self.sanitize_repository_identifier(repository_id)
        logger.debug(f"Retrieving existing collection: {collection_name} for repository: {repository_id}")
        return self.client.get_collection(
            name=collection_name,
            embedding_function=self.embedding_function
        )


repository_database_manager = RepositoryVectorDatabase()
