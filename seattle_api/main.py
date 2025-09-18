"""Main FastAPI application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api_models import HealthResponse
from .cache import IncidentCache
from .config import config
from .http_client import SeattleHTTPClient
from .poller import IncidentPoller
from .routes import incidents_router
from .routes.incidents import set_cache

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global services
cache: IncidentCache = None
http_client: SeattleHTTPClient = None
poller: IncidentPoller = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan events."""
    global cache, http_client, poller

    # Startup
    logger.info("Starting Seattle Fire Department API service")
    logger.info(
        f"Configuration: polling_interval={config.polling_interval_minutes}min, "
        f"cache_retention={config.cache_retention_hours}h, "
        f"port={config.server_port}"
    )

    # Validate configuration on startup
    try:
        config.validate()
        logger.info("Configuration validation passed")
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise

    # Initialize services
    try:
        # Initialize cache
        cache = IncidentCache(
            retention_hours=config.cache_retention_hours, cleanup_interval_minutes=15
        )
        logger.info("Incident cache initialized")

        # Initialize HTTP client
        http_client = SeattleHTTPClient(config)
        await http_client.start()
        logger.info("HTTP client initialized")

        # Initialize and start poller
        poller = IncidentPoller(config, http_client, cache)
        await poller.start_polling()
        logger.info("Incident poller started")

        # Set cache for incident routes
        set_cache(cache)
        logger.info("Routes configured with cache")

        logger.info("All services started successfully")

    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        # Cleanup on failure
        if poller:
            await poller.shutdown()
        if http_client:
            await http_client.close()
        raise

    yield

    # Shutdown
    logger.info("Shutting down Seattle Fire Department API service")

    try:
        # Shutdown services in reverse order
        if poller:
            logger.info("Shutting down poller...")
            await poller.shutdown()

        if http_client:
            logger.info("Shutting down HTTP client...")
            await http_client.close()

        if cache:
            logger.info("Stopping cache cleanup...")
            await cache.stop_background_cleanup()

        logger.info("All services shut down successfully")

    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        # Don't raise here to allow graceful shutdown


# Create FastAPI application
app = FastAPI(
    title="Seattle Fire Department Incident API",
    description="API service for Seattle Fire Department live incident data",
    version="1.0.0",
    lifespan=lifespan,
)

# Include incident routes
app.include_router(incidents_router)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Enhanced health check endpoint with service status."""
    global cache, poller

    # Determine overall service status
    service_status = "healthy"
    poller_status = None

    try:
        if poller is not None:
            poller_status = poller.get_health_status()

            # Determine service status based on poller health
            if poller_status["status"] in ["stopped", "unhealthy"]:
                service_status = "unhealthy"
            elif poller_status["status"] in ["degraded", "circuit_open"]:
                service_status = "degraded"

        elif poller is None:
            service_status = "starting"

    except Exception as e:
        logger.error(f"Error checking poller health: {e}")
        service_status = "unhealthy"

    return HealthResponse(
        status=service_status,
        service="seattle-fire-api",
        version="1.0.0",
        config={
            "polling_interval_minutes": config.polling_interval_minutes,
            "cache_retention_hours": config.cache_retention_hours,
            "server_port": config.server_port,
            "server_host": config.server_host,
        },
        poller_status=poller_status,
    )


@app.get("/")
async def root():
    """Root endpoint with service information."""
    return {
        "message": "Seattle Fire Department Incident API",
        "version": "1.0.0",
        "description": "API service for Seattle Fire Department live incident data",
        "endpoints": {
            "health": "/health",
            "active_incidents": "/incidents/active",
            "all_incidents": "/incidents/all",
            "specific_incident": "/incidents/{incident_id}",
            "docs": "/docs",
            "redoc": "/redoc",
        },
        "documentation": {
            "swagger_ui": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
        },
    }


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting server on {config.server_host}:{config.server_port}")
    uvicorn.run(
        "seattle_api.main:app",
        host=config.server_host,
        port=config.server_port,
        log_level=config.log_level.lower(),
        reload=False,
    )
