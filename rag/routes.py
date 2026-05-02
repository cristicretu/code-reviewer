from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from rag.schemas import (
    IngestionRequest, 
    IngestionAcknowledgement, 
    SearchQuery, 
    RetrievalResults
)
from rag.service import ingest_repository, delete_repository_file, retrieve_semantic_context

router = APIRouter()

@router.get("/health")
async def verify_service_health():
    return {"status": "active"}

@router.post(
    "/api/v1/ingest/{repository_id:path}",
    response_model=IngestionAcknowledgement
)
async def ingest_repository_snippets(repository_id: str, payload: IngestionRequest):
    try:
        return ingest_repository(repository_id, payload)
    except Exception as error:
        logger.error(f"Ingestion failed for repository {repository_id}: {str(error)}")
        raise HTTPException(status_code=500, detail=str(error))

@router.delete(
    "/api/v1/repo/{repository_id}/file"
)
async def delete_repository_file_endpoint(repository_id: str, path: str = Query(..., description="The path of the file to remove from the vector database.")):
    try:
        delete_repository_file(repository_id, path)
        return {"status": "deleted", "repository_id": repository_id, "file_path": path}
    except Exception as error:
        if "not found" in str(error).lower():
             raise HTTPException(status_code=404, detail=str(error))
        logger.error(f"Deletion failed for repository {repository_id}, file {path}: {str(error)}")
        raise HTTPException(status_code=500, detail=str(error))

@router.post(
    "/api/v1/retrieve/{repository_id:path}",
    response_model=RetrievalResults
)
async def retrieve_semantic_context_endpoint(repository_id: str, query_payload: SearchQuery):
    try:
        return retrieve_semantic_context(repository_id, query_payload)
    except Exception as error:
        if "not found" in str(error).lower() or "not been ingested" in str(error).lower():
            raise HTTPException(status_code=404, detail=str(error))
        logger.exception(f"Unexpected error during retrieval for repository {repository_id}")
        raise HTTPException(status_code=500, detail=str(error))
