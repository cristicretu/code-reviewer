import hashlib
from loguru import logger
from typing import List, Dict, Any, Optional
from rag.schemas import (
    IngestionRequest, 
    IngestionAcknowledgement, 
    SearchQuery, 
    RetrievalResults, 
    RetrievalMatch
)
from rag.database import repository_database_manager

def generate_deterministic_id(repository_id: str, file_path: str, chunk_index: int, content: str) -> str:
    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    raw_id = f"{repository_id}:{file_path}:{chunk_index}:{content_hash}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest()

def ingest_repository(repository_id: str, payload: IngestionRequest) -> IngestionAcknowledgement:
    logger.info(f"Processing ingestion for repository: {repository_id} with {len(payload.snippets)} snippets")
    collection = repository_database_manager.get_collection_for_repository(repository_id)
    
    snippets_to_embed = []
    snippet_metadata_list = []
    unique_identifiers = []

    for snippet in payload.snippets:
        snippets_to_embed.append(snippet.content)
        
        base_metadata = snippet.metadata or {}
        base_metadata.update({
            "file_path": snippet.file_path,
            "repository_id": repository_id,
            "chunk_index": snippet.chunk_index
        })
        if payload.metadata_overrides:
            base_metadata.update(payload.metadata_overrides)
        
        snippet_metadata_list.append(base_metadata)
        
        deterministic_id = generate_deterministic_id(
            repository_id, 
            snippet.file_path, 
            snippet.chunk_index, 
            snippet.content
        )
        unique_identifiers.append(deterministic_id)

    collection.upsert(
        ids=unique_identifiers,
        documents=snippets_to_embed,
        metadatas=snippet_metadata_list
    )

    logger.success(f"Successfully ingested {len(payload.snippets)} snippets into collection: {collection.name}")
    return IngestionAcknowledgement(
        repository_id=repository_id,
        collection_name=collection.name,
        snippets_processed=len(payload.snippets)
    )

def delete_repository_file(repository_id: str, file_path: str):
    logger.info(f"Processing deletion for repository: {repository_id}, file: {file_path}")
    collection = repository_database_manager.retrieve_collection_for_repository(repository_id)
    collection.delete(where={"file_path": file_path})
    logger.success(f"Successfully deleted snippets for file: {file_path} from repository: {repository_id}")

def retrieve_semantic_context(repository_id: str, query_payload: SearchQuery) -> RetrievalResults:
    logger.info(f"Processing retrieval for repository: {repository_id} with query: '{query_payload.query}'")
    collection = repository_database_manager.retrieve_collection_for_repository(repository_id)

    logger.debug(f"Executing ChromaDB query with where={query_payload.where}")
    query_results = collection.query(
        query_texts=[query_payload.query],
        n_results=query_payload.max_results,
        where=query_payload.where,
        include=["documents", "metadatas", "distances"]
    )

    matches_list = []
    if query_results["documents"]:
        for index in range(len(query_results["documents"][0])):
            metadata = query_results["metadatas"][0][index]
            match = RetrievalMatch(
                content=query_results["documents"][0][index],
                file_path=metadata.get("file_path", "unknown"),
                relevance_score=1.0 - query_results["distances"][0][index],
                metadata=metadata
            )
            matches_list.append(match)

    logger.debug(f"Retrieved {len(matches_list)} relevant matches for repository: {repository_id}")
    return RetrievalResults(
        repository_id=repository_id,
        matches=matches_list
    )
