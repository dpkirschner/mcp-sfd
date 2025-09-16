"""
Implementation of sfd.fetch_raw tool.

This tool provides low-level access to the Seattle Fire Department API
with normalization and caching capabilities.
"""

import logging
from typing import Any

from ..http_client import get_client
from ..normalize import normalize_full_response
from ..schemas import FetchRawInput, FetchRawResponse

logger = logging.getLogger(__name__)


async def fetch_raw(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Low-level proxy tool for SFD API with normalization.

    Fetches incident data from the Seattle Fire Department API,
    normalizes the response format, and applies caching.

    Args:
        arguments: Tool arguments matching FetchRawInput schema

    Returns:
        Normalized response matching FetchRawResponse schema

    Raises:
        MCPToolError: On upstream API errors, timeouts, or validation failures
    """
    # Validate input arguments
    try:
        input_data = FetchRawInput(**arguments)
    except Exception as e:
        logger.error(f"Invalid input arguments: {e}")
        raise ValueError(f"Invalid arguments: {e}")

    # Prepare query parameters for upstream API
    query_params = {
        "draw": 1,  # Fixed value as specified in the API contract
        "order": input_data.order,
        "start": input_data.start,
        "length": input_data.length,
        "search": input_data.search,
        "page": input_data.page,
        "location": input_data.location,
        "unit": input_data.unit,
        "type": input_data.type,
        "area": input_data.area,
        "date": input_data.date,
        "dateEnd": input_data.dateEnd,
    }

    logger.info(
        "Fetching SFD incidents",
        extra={
            "order": input_data.order,
            "page": input_data.page,
            "length": input_data.length,
            "cache_ttl": input_data.cacheTtlSeconds,
        },
    )

    # Get HTTP client and make request
    client = await get_client()
    raw_response, cache_hit = await client.fetch_incidents(
        query_params, input_data.cacheTtlSeconds
    )

    # Construct the request URL for source information
    base_url = client.base_url
    query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
    request_url = f"{base_url}?{query_string}"

    # Normalize the response
    try:
        normalized_response = normalize_full_response(
            raw_response, request_url, cache_hit
        )
    except Exception as e:
        logger.error(f"Failed to normalize response: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Failed to parse upstream response: {e}"
        )

    # Validate output against schema
    try:
        validated_response = FetchRawResponse(**normalized_response)
        result = validated_response.model_dump()
    except Exception as e:
        logger.error(f"Response validation failed: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Response validation failed: {e}"
        )

    logger.info(
        "Successfully fetched and normalized incidents",
        extra={
            "incident_count": len(result["incidents"]),
            "cache_hit": cache_hit,
        },
    )

    return result
