"""Main FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import config


# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan events."""
    # Startup
    logger.info("Starting Seattle Fire Department API service")
    logger.info(f"Configuration: polling_interval={config.polling_interval_minutes}min, "
                f"cache_retention={config.cache_retention_hours}h, "
                f"port={config.server_port}")
    
    # Validate configuration on startup
    try:
        config.validate()
        logger.info("Configuration validation passed")
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Seattle Fire Department API service")


# Create FastAPI application
app = FastAPI(
    title="Seattle Fire Department Incident API",
    description="API service for Seattle Fire Department live incident data",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "seattle-fire-api",
            "version": "1.0.0",
            "config": {
                "polling_interval_minutes": config.polling_interval_minutes,
                "cache_retention_hours": config.cache_retention_hours,
                "server_port": config.server_port
            }
        }
    )


@app.get("/")
async def root():
    """Root endpoint with service information."""
    return {
        "message": "Seattle Fire Department Incident API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting server on {config.server_host}:{config.server_port}")
    uvicorn.run(
        "seattle_api.main:app",
        host=config.server_host,
        port=config.server_port,
        log_level=config.log_level.lower(),
        reload=False
    )