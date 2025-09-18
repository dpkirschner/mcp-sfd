"""Configuration management for Seattle API service."""

import os
from dataclasses import dataclass


@dataclass
class FastAPIConfig:
    """Configuration for the FastAPI service."""

    # Polling configuration
    polling_interval_minutes: int = 5
    seattle_endpoint: str = (
        "https://web.seattle.gov/sfd/realtime911/getRecsForDatePub.asp?action=Today&incDate=&rad1=des"
    )

    # Cache configuration
    cache_retention_hours: int = 24

    # Server configuration
    server_port: int = 8000
    server_host: str = "0.0.0.0"

    # Logging configuration
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "FastAPIConfig":
        """Create configuration from environment variables."""
        return cls(
            polling_interval_minutes=int(os.getenv("POLLING_INTERVAL_MINUTES", "5")),
            seattle_endpoint=os.getenv(
                "SEATTLE_ENDPOINT_URL",
                "https://web.seattle.gov/sfd/realtime911/getRecsForDatePub.asp?action=Today&incDate=&rad1=des",
            ),
            cache_retention_hours=int(os.getenv("CACHE_RETENTION_HOURS", "24")),
            server_port=int(os.getenv("SERVER_PORT", "8000")),
            server_host=os.getenv("SERVER_HOST", "0.0.0.0"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def validate(self) -> None:
        """Validate configuration settings."""
        if self.polling_interval_minutes <= 0:
            raise ValueError("Polling interval must be positive")

        if self.cache_retention_hours <= 0:
            raise ValueError("Cache retention hours must be positive")

        if not self.seattle_endpoint:
            raise ValueError("Seattle endpoint URL is required")

        if self.server_port <= 0 or self.server_port > 65535:
            raise ValueError("Server port must be between 1 and 65535")


# Global configuration instance
config = FastAPIConfig.from_env()
