import hashlib
from loguru import logger
from fastapi import FastAPI, HTTPException, Query
from rag.schemas import (
    IngestionRequest, 
    IngestionAcknowledgement, 
    SearchQuery, 
    RetrievalResults, 
    RetrievalMatch
)
from rag.database import repository_database_manager

code_reviewer_rag_api = FastAPI(
    title="Code Reviewer RAG Microservice",
    description="Vector ingestion and semantic retrieval for automated code reviews.",
    version="1.0.0"
)

@code_reviewer_rag_api.get("/health")
async def verify_service_health():
    return {"status": "active"}

def generate_deterministic_id(repository_id: str, file_path: str, chunk_index: int, content: str) -> str:
    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    raw_id = f"{repository_id}:{file_path}:{chunk_index}:{content_hash}"
    return hashlib.sha256(raw_id.encode('utf-8')).hexdigest()

@code_reviewer_rag_api.post(
    "/api/v1/ingest/{repository_id}", 
    response_model=IngestionAcknowledgement
)
async def ingest_repository_snippets(repository_id: str, payload: IngestionRequest):
    logger.info(f"Received ingestion request for repository: {repository_id} with {len(payload.snippets)} snippets")
    try:
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
            
            # Deterministic ID for deduplication and incremental updates
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
    except Exception as error:
        logger.error(f"Ingestion failed for repository {repository_id}: {str(error)}")
        raise HTTPException(status_code=500, detail=str(error))

@code_reviewer_rag_api.delete(
    "/api/v1/repo/{repository_id}/file"
)
async def delete_repository_file(repository_id: str, path: str = Query(..., description="The path of the file to remove from the vector database.")):
    logger.info(f"Received deletion request for repository: {repository_id}, file: {path}")
    try:
        try:
            collection = repository_database_manager.retrieve_collection_for_repository(repository_id)
        except Exception:
             raise HTTPException(
                status_code=404, 
                detail=f"Repository {repository_id} not found."
            )
        
        # ChromaDB allows filtering deletes by metadata
        collection.delete(where={"file_path": path})
        
        logger.success(f"Successfully deleted snippets for file: {path} from repository: {repository_id}")
        return {"status": "deleted", "repository_id": repository_id, "file_path": path}
    except HTTPException as api_error:
        raise api_error
    except Exception as error:
        logger.error(f"Deletion failed for repository {repository_id}, file {path}: {str(error)}")
        raise HTTPException(status_code=500, detail=str(error))

@code_reviewer_rag_api.post(
    "/api/v1/retrieve/{repository_id}", 
    response_model=RetrievalResults
)
async def retrieve_semantic_context(repository_id: str, query_payload: SearchQuery):
    logger.info(f"Received retrieval request for repository: {repository_id} with query: '{query_payload.query}' and filter: {query_payload.where}")
    try:
        try:
            collection = repository_database_manager.retrieve_collection_for_repository(repository_id)
        except Exception:
            logger.warning(f"Retrieval failed: Repository {repository_id} not found in database.")
            raise HTTPException(
                status_code=404, 
                detail=f"Repository {repository_id} has not been ingested."
            )

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
    except HTTPException as api_error:
        raise api_error
    except Exception as internal_error:
        logger.exception(f"Unexpected error during retrieval for repository {repository_id}")
        raise HTTPException(status_code=500, detail=str(internal_error))

if __name__ == "__main__":
    import uvicorn
    from config.config_manager import settings
    logger.info(f"Starting server on {settings.DEFAULT.HOST}:{settings.DEFAULT.PORT}")
    uvicorn.run(
        "src.main:code_reviewer_rag_api", 
        host=settings.DEFAULT.HOST, 
        port=settings.DEFAULT.PORT, 
        reload=True
    )
