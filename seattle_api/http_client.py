"""HTTP client for Seattle government incident endpoint."""

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx
from httpx import AsyncClient, ConnectError, HTTPError, TimeoutException

from .config import FastAPIConfig

logger = logging.getLogger(__name__)


class SeattleHTTPClient:
    """Async HTTP client for Seattle government incident endpoint."""

    def __init__(self, config: FastAPIConfig):
        """Initialize the HTTP client.

        Args:
            config: FastAPI configuration containing endpoint URL and settings
        """
        self.config = config
        self.endpoint_url = config.seattle_endpoint
        self._client: AsyncClient | None = None

        # Retry configuration
        self.max_retries = 3
        self.base_delay = 1.0  # Base delay for exponential backoff
        self.max_delay = 60.0  # Maximum delay between retries

        # Request configuration
        self.timeout = 30.0
        self.headers = {
            "User-Agent": "Seattle-Incident-API/1.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def start(self) -> None:
        """Start the HTTP client."""
        if self._client is None:
            self._client = AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=self.headers,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
            logger.info("HTTP client started")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("HTTP client closed")

    async def fetch_incident_html(self) -> str:
        """Fetch incident HTML from Seattle government endpoint.

        Returns:
            HTML content as string

        Raises:
            HTTPClientError: When all retry attempts fail
        """
        if self._client is None:
            await self.start()

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(
                    f"Fetching incidents (attempt {attempt + 1}/{self.max_retries + 1})"
                )

                response = await self._client.get(self.endpoint_url)
                response.raise_for_status()

                html_content = response.text

                # Basic validation of response
                if not html_content or len(html_content.strip()) == 0:
                    raise HTTPClientError("Empty response received from server")

                # Check if response looks like HTML
                if not self._is_valid_html_response(html_content):
                    raise HTTPClientError("Response does not appear to be valid HTML")

                logger.info(
                    f"Successfully fetched incident data ({len(html_content)} characters)"
                )
                return html_content

            except (HTTPError, TimeoutException, ConnectError) as e:
                last_exception = e
                logger.warning(f"HTTP request failed (attempt {attempt + 1}): {e}")

                # Don't retry on client errors (4xx)
                if (
                    isinstance(e, httpx.HTTPStatusError)
                    and 400 <= e.response.status_code < 500
                ):
                    logger.error(f"Client error {e.response.status_code}, not retrying")
                    break

                # Calculate delay for exponential backoff
                if attempt < self.max_retries:
                    delay = min(self.base_delay * (2**attempt), self.max_delay)
                    logger.info(f"Retrying in {delay:.1f} seconds...")
                    await asyncio.sleep(delay)

            except Exception as e:
                last_exception = e
                logger.error(f"Unexpected error during HTTP request: {e}")
                break

        # All retries failed
        error_msg = (
            f"Failed to fetch incident data after {self.max_retries + 1} attempts"
        )
        if last_exception:
            error_msg += f": {last_exception}"

        logger.error(error_msg)
        raise HTTPClientError(error_msg) from last_exception

    def _is_valid_html_response(self, content: str) -> bool:
        """Validate that response content appears to be HTML.

        Args:
            content: Response content to validate

        Returns:
            True if content appears to be valid HTML
        """
        content_lower = content.lower().strip()

        # Check for basic HTML structure
        has_html_tag = "<html" in content_lower or "<!doctype html" in content_lower
        has_table = "<table" in content_lower

        # The Seattle endpoint should return a page with a table
        return has_html_tag or has_table

    async def health_check(self) -> dict[str, Any]:
        """Perform a health check on the Seattle endpoint.

        Returns:
            Dictionary with health check results
        """
        start_time = datetime.utcnow()

        try:
            if self._client is None:
                await self.start()

            response = await self._client.head(self.endpoint_url, timeout=10.0)
            response_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                "status": "healthy" if response.status_code == 200 else "degraded",
                "status_code": response.status_code,
                "response_time_seconds": response_time,
                "endpoint": self.endpoint_url,
                "timestamp": start_time.isoformat(),
            }

        except Exception as e:
            response_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_seconds": response_time,
                "endpoint": self.endpoint_url,
                "timestamp": start_time.isoformat(),
            }


class HTTPClientError(Exception):
    """Exception raised by HTTP client operations."""

    pass
