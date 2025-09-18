"""
HTTP client for Seattle Socrata API with retry logic and caching.

This module provides a robust HTTP client that handles retries, timeouts,
and in-memory caching for the Seattle Fire Department data via Socrata API.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class CacheEntry:
    """A single cache entry with TTL support."""

    def __init__(self, data: Any, ttl_seconds: int):
        self.data = data
        self.expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return datetime.utcnow() > self.expires_at


class SFDClient:
    """HTTP client for Seattle Fire Department Socrata API with caching and retry logic."""

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "SFD_BASE_URL", "https://data.seattle.gov/resource/kzjm-xkqj.json"
        )
        self.default_cache_ttl = int(os.getenv("DEFAULT_CACHE_TTL", "15"))
        self._cache: dict[str, CacheEntry] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client."""
        if self._client is None:
            timeout = httpx.Timeout(10.0)
            headers = {
                "User-Agent": "mcp-sfd/1.0.0",
                "Accept": "application/json",
                "Accept-Encoding": "gzip, br",
            }
            self._client = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    def _make_cache_key(self, params: dict[str, Any]) -> str:
        """Create a cache key from sorted query parameters."""
        # Sort parameters for consistent cache keys
        sorted_params = sorted(params.items())
        return urlencode(sorted_params)

    def _clean_expired_cache(self) -> None:
        """Remove expired entries from cache."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]
        for key in expired_keys:
            del self._cache[key]

    async def _make_request_with_retry(
        self, url: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Make HTTP request with retry logic."""
        client = await self._get_client()
        last_exception: httpx.RequestError | httpx.TimeoutException | None = None

        for attempt in range(3):  # Initial attempt + 2 retries
            try:
                # Use params directly for Socrata API
                request_params = params.copy()
                # Remove internal cache parameter
                if "cacheTtlSeconds" in request_params:
                    del request_params["cacheTtlSeconds"]

                start_time = time.time()
                response = await client.get(url, params=request_params)
                elapsed_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    "HTTP request completed",
                    extra={
                        "url": str(response.url),
                        "status_code": response.status_code,
                        "elapsed_ms": elapsed_ms,
                        "attempt": attempt + 1,
                    },
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                        return data, False  # False = not from cache
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Failed to parse JSON response",
                            extra={
                                "status_code": response.status_code,
                                "error": str(e),
                            },
                        )
                        raise MCPToolError(
                            "SCHEMA_VALIDATION_ERROR",
                            f"Invalid JSON response from Socrata API: {e}",
                        ) from e

                # Retry on server errors
                if response.status_code in (502, 503, 504):
                    if attempt < 2:  # Don't sleep on the last attempt
                        sleep_time = 2**attempt  # Exponential backoff: 1s, 2s
                        logger.warning(
                            f"Server error {response.status_code}, retrying in {sleep_time}s",
                            extra={
                                "status_code": response.status_code,
                                "attempt": attempt + 1,
                                "sleep_time": sleep_time,
                            },
                        )
                        await asyncio.sleep(sleep_time)
                        continue

                # Non-retryable HTTP error
                logger.error(
                    "HTTP error from upstream",
                    extra={
                        "status_code": response.status_code,
                        "response_text": response.text[:500],
                    },
                )
                raise MCPToolError(
                    "UPSTREAM_HTTP_ERROR",
                    f"Socrata API returned HTTP {response.status_code}",
                )

            except httpx.TimeoutException as e:
                last_exception = e
                if attempt < 2:
                    sleep_time = 2**attempt
                    logger.warning(
                        f"Request timeout, retrying in {sleep_time}s",
                        extra={"attempt": attempt + 1, "sleep_time": sleep_time},
                    )
                    await asyncio.sleep(sleep_time)
                    continue

            except httpx.RequestError as e:
                last_exception = e
                if attempt < 2:
                    sleep_time = 2**attempt
                    logger.warning(
                        f"Network error, retrying in {sleep_time}s",
                        extra={
                            "error": str(e),
                            "attempt": attempt + 1,
                            "sleep_time": sleep_time,
                        },
                    )
                    await asyncio.sleep(sleep_time)
                    continue

        # All retries exhausted
        if isinstance(last_exception, httpx.TimeoutException):
            logger.error("Request timed out after all retries")
            raise MCPToolError(
                "UPSTREAM_TIMEOUT", "Socrata API request timed out after retries"
            )
        else:
            logger.error(
                "Network error after all retries", extra={"error": str(last_exception)}
            )
            raise MCPToolError(
                "UPSTREAM_HTTP_ERROR", f"Network error: {last_exception}"
            )

    async def fetch_incidents(
        self, params: dict[str, Any], cache_ttl_seconds: int | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        """
        Fetch incidents from Socrata API with caching.

        Returns:
            Tuple of (response_data, cache_hit) where response_data is a list of incidents
        """
        if cache_ttl_seconds is None:
            cache_ttl_seconds = self.default_cache_ttl

        # Clean expired cache entries
        self._clean_expired_cache()

        # Check cache if TTL > 0
        cache_hit = False
        if cache_ttl_seconds > 0:
            cache_key = self._make_cache_key(params)
            if cache_key in self._cache and not self._cache[cache_key].is_expired():
                logger.info("Cache hit", extra={"cache_key": cache_key})
                return self._cache[cache_key].data, True

        # Make API request
        data, _ = await self._make_request_with_retry(self.base_url, params)

        # Socrata returns array directly, not wrapped in object
        if not isinstance(data, list):
            logger.error(f"Expected list response from Socrata, got {type(data)}")
            raise MCPToolError(
                "SCHEMA_VALIDATION_ERROR",
                f"Expected list response from Socrata API, got {type(data)}",
            )

        # Store in cache if TTL > 0
        if cache_ttl_seconds > 0:
            cache_key = self._make_cache_key(params)
            self._cache[cache_key] = CacheEntry(data, cache_ttl_seconds)
            logger.info(
                "Cached response",
                extra={"cache_key": cache_key, "ttl_seconds": cache_ttl_seconds},
            )

        return data, cache_hit

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class MCPToolError(Exception):
    """Custom exception for MCP tool errors."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# Global client instance
_client: SFDClient | None = None


async def get_client() -> SFDClient:
    """Get the global Socrata client instance."""
    global _client
    if _client is None:
        _client = SFDClient()
    return _client


async def close_client() -> None:
    """Close the global Socrata client instance."""
    global _client
    if _client:
        await _client.close()
        _client = None
