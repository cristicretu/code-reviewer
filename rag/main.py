from fastapi import FastAPI
from loguru import logger
from rag.routes import router as rag_router

code_reviewer_rag_api = FastAPI(
    title="Code Reviewer RAG Microservice",
    description="Vector ingestion and semantic retrieval for automated code reviews.",
    version="1.0.0"
)

code_reviewer_rag_api.include_router(rag_router)

if __name__ == "__main__":
    import uvicorn
    from config.config_manager import settings
    logger.info(f"Starting server on {settings.DEFAULT.HOST}:{settings.DEFAULT.PORT}")
    uvicorn.run(
        "rag.main:code_reviewer_rag_api", 
        host=settings.DEFAULT.HOST, 
        port=settings.DEFAULT.PORT, 
        reload=True
    )
