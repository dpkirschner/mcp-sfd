"""
HTTP client for communicating with the Seattle Fire Department FastAPI service.

This module provides a robust HTTP client that handles retries, timeouts,
connection pooling, and error mapping for communication with the FastAPI service.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class MCPToolError(Exception):
    """Custom exception for MCP tool errors."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class SeattleAPIClient:
    """HTTP client for communicating with Seattle Fire Department FastAPI service."""

    def __init__(
        self, base_url: str | None = None, timeout: int = 30, max_retries: int = 3
    ):
        """
        Initialize the API client.

        Args:
            base_url: Base URL for the FastAPI service
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.base_url = base_url or os.getenv(
            "FASTAPI_BASE_URL", "http://localhost:8000"
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client with connection pooling."""
        if self._client is None:
            timeout = httpx.Timeout(self.timeout)
            headers = {
                "User-Agent": "mcp-sfd-client/1.0.0",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, br",
            }

            # Configure connection pooling
            limits = httpx.Limits(
                max_keepalive_connections=10, max_connections=20, keepalive_expiry=30.0
            )

            self._client = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                limits=limits,
                base_url=self.base_url or "http://localhost:8000",
            )
        return self._client

    async def _make_request_with_retry(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> httpx.Response:
        """Make HTTP request with retry logic and exponential backoff."""
        client = await self._get_client()
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):  # +1 for initial attempt
            try:
                logger.debug(
                    f"Making {method} request to {endpoint}",
                    extra={
                        "method": method,
                        "endpoint": endpoint,
                        "attempt": attempt + 1,
                        "max_attempts": self.max_retries + 1,
                    },
                )

                response = await client.request(method, endpoint, **kwargs)

                logger.info(
                    f"HTTP {method} request completed",
                    extra={
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                )

                # Check for successful response
                if response.status_code == 200:
                    return response

                # Handle 404 specifically
                if response.status_code == 404:
                    raise MCPToolError(
                        "RESOURCE_NOT_FOUND", f"Resource not found: {endpoint}"
                    )

                # Retry on server errors (5xx) and some client errors
                if (
                    response.status_code in (500, 502, 503, 504)
                    and attempt < self.max_retries
                ):
                    sleep_time = min(2**attempt, 32)  # Exponential backoff with max 32s
                    logger.warning(
                        f"Server error {response.status_code}, retrying in {sleep_time}s",
                        extra={
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                            "sleep_time": sleep_time,
                            "endpoint": endpoint,
                        },
                    )
                    await asyncio.sleep(sleep_time)
                    continue

                # Non-retryable HTTP error
                error_text = (
                    response.text
                    if len(response.text) < 500
                    else response.text[:500] + "..."
                )
                logger.error(
                    "HTTP error from FastAPI service",
                    extra={
                        "status_code": response.status_code,
                        "endpoint": endpoint,
                        "response_text": error_text,
                    },
                )
                raise MCPToolError(
                    "UPSTREAM_HTTP_ERROR",
                    f"FastAPI service returned HTTP {response.status_code}: {error_text}",
                )

            except httpx.TimeoutException as e:
                last_exception = e
                if attempt < self.max_retries:
                    sleep_time = min(2**attempt, 32)
                    logger.warning(
                        f"Request timeout, retrying in {sleep_time}s",
                        extra={
                            "attempt": attempt + 1,
                            "sleep_time": sleep_time,
                            "endpoint": endpoint,
                        },
                    )
                    await asyncio.sleep(sleep_time)
                    continue

            except httpx.ConnectError as e:
                last_exception = e
                logger.error(
                    "Connection error to FastAPI service",
                    extra={
                        "endpoint": endpoint,
                        "error": str(e),
                        "attempt": attempt + 1,
                    },
                )
                raise MCPToolError(
                    "SERVICE_UNAVAILABLE",
                    f"Cannot connect to FastAPI service at {self.base_url}: {e}",
                ) from e

            except httpx.RequestError as e:
                last_exception = e
                if attempt < self.max_retries:
                    sleep_time = min(2**attempt, 32)
                    logger.warning(
                        f"Network error, retrying in {sleep_time}s",
                        extra={
                            "error": str(e),
                            "attempt": attempt + 1,
                            "sleep_time": sleep_time,
                            "endpoint": endpoint,
                        },
                    )
                    await asyncio.sleep(sleep_time)
                    continue

        # All retries exhausted
        if isinstance(last_exception, httpx.TimeoutException):
            logger.error(
                "Request timed out after all retries",
                extra={"endpoint": endpoint, "max_retries": self.max_retries},
            )
            raise MCPToolError(
                "UPSTREAM_TIMEOUT",
                f"FastAPI service request timed out after {self.max_retries} retries",
            )
        else:
            logger.error(
                "Network error after all retries",
                extra={
                    "error": str(last_exception),
                    "endpoint": endpoint,
                    "max_retries": self.max_retries,
                },
            )
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR",
                f"Network error after {self.max_retries} retries: {last_exception}",
            )

    def _validate_and_parse_incidents(self, data: Any) -> list[dict[str, Any]]:
        """Validate and parse incident data from API response."""
        if not isinstance(data, list):
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Expected list of incidents, got {type(data)}",
            )

        # For now, return the raw data. In a full implementation,
        # we would validate each incident against the Incident model
        return data

    async def get_active_incidents(self) -> list[dict[str, Any]]:
        """Get currently active incidents from the FastAPI service."""
        try:
            response = await self._make_request_with_retry("GET", "/incidents/active")
            data = response.json()
            return self._validate_and_parse_incidents(data)

        except httpx.HTTPStatusError as e:
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR",
                f"Failed to fetch active incidents: HTTP {e.response.status_code}",
            ) from e
        except ValidationError as e:
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Invalid response format for active incidents: {e}",
            ) from e

    async def get_all_incidents(self) -> list[dict[str, Any]]:
        """Get all incidents from the FastAPI service."""
        try:
            response = await self._make_request_with_retry("GET", "/incidents/all")
            data = response.json()
            return self._validate_and_parse_incidents(data)

        except httpx.HTTPStatusError as e:
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR",
                f"Failed to fetch all incidents: HTTP {e.response.status_code}",
            ) from e
        except ValidationError as e:
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Invalid response format for all incidents: {e}",
            ) from e

    async def search_incidents(
        self,
        incident_type: str | None = None,
        address_contains: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        status: str | None = None,
        priority: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search incidents with filters."""
        params = {}

        if incident_type:
            params["type"] = incident_type
        if address_contains:
            params["address"] = address_contains
        if since:
            params["since"] = since.isoformat()
        if until:
            params["until"] = until.isoformat()
        if status:
            params["status"] = status
        if priority is not None:
            params["priority"] = str(priority)

        try:
            response = await self._make_request_with_retry(
                "GET", "/incidents/search", params=params
            )
            data = response.json()
            return self._validate_and_parse_incidents(data)

        except httpx.HTTPStatusError as e:
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR",
                f"Failed to search incidents: HTTP {e.response.status_code}",
            ) from e
        except ValidationError as e:
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Invalid response format for incident search: {e}",
            ) from e

    async def get_incident(self, incident_id: str) -> dict[str, Any]:
        """Get a specific incident by ID."""
        try:
            response = await self._make_request_with_retry(
                "GET", f"/incidents/{incident_id}"
            )
            data = response.json()

            if not isinstance(data, dict):
                raise MCPToolError(
                    "SCHEMA_VALIDATION_ERROR",
                    f"Expected incident object, got {type(data)}",
                )

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise MCPToolError(
                    "RESOURCE_NOT_FOUND", f"Incident {incident_id} not found"
                ) from e
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR",
                f"Failed to fetch incident {incident_id}: HTTP {e.response.status_code}",
            ) from e
        except ValidationError as e:
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Invalid response format for incident {incident_id}: {e}",
            ) from e

    async def get_health(self) -> dict[str, Any]:
        """Get service health status."""
        try:
            response = await self._make_request_with_retry("GET", "/health")
            data = response.json()

            if not isinstance(data, dict):
                raise MCPToolError(
                    "SCHEMA_VALIDATION_ERROR",
                    f"Expected health status object, got {type(data)}",
                )

            return data

        except httpx.HTTPStatusError as e:
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR",
                f"Failed to fetch health status: HTTP {e.response.status_code}",
            ) from e
        except ValidationError as e:
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Invalid response format for health status: {e}",
            ) from e

    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("FastAPI client closed")


# Global client instance
_client: SeattleAPIClient | None = None


async def get_client() -> SeattleAPIClient:
    """Get the global FastAPI client instance."""
    global _client
    if _client is None:
        # Load configuration from environment
        base_url = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")
        timeout = int(os.getenv("REQUEST_TIMEOUT", "30"))
        max_retries = int(os.getenv("MAX_RETRIES", "3"))

        _client = SeattleAPIClient(
            base_url=base_url, timeout=timeout, max_retries=max_retries
        )
        logger.info(
            "FastAPI client initialized",
            extra={
                "base_url": base_url,
                "timeout": timeout,
                "max_retries": max_retries,
            },
        )
    return _client


async def close_client() -> None:
    """Close the global FastAPI client instance."""
    global _client
    if _client:
        await _client.close()
        _client = None
