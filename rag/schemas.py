from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class SourceCodeSnippet(BaseModel):
    file_path: str
    content: str
    chunk_index: int = 0
    metadata: Optional[Dict[str, Any]] = None

class IngestionRequest(BaseModel):
    snippets: List[SourceCodeSnippet]
    metadata_overrides: Optional[Dict[str, Any]] = None

class IngestionAcknowledgement(BaseModel):
    repository_id: str
    collection_name: str
    snippets_processed: int
    status: str = "indexed"

class SearchQuery(BaseModel):
    query: str
    max_results: int = Field(default=5, ge=1, le=20)
    where: Optional[Dict[str, Any]] = None

class RetrievalMatch(BaseModel):
    content: str
    file_path: str
    relevance_score: float = Field(description="Cosine similarity score (0.0 to 1.0, where 1.0 is perfect match)")
    metadata: Dict[str, Any]

class RetrievalResults(BaseModel):
    repository_id: str
    matches: List[RetrievalMatch]
