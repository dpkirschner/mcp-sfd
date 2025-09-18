"""
Implementation of sfd.fetch_raw tool.

This tool provides low-level access to the Seattle Fire Department data
via Socrata API with normalization and caching capabilities.
"""

import logging
from datetime import datetime
from typing import Any

from ..http_client import get_client
from ..normalize import normalize_full_response
from ..schemas import FetchRawInput, FetchRawResponse

logger = logging.getLogger(__name__)


def build_socrata_query_params(input_data: FetchRawInput) -> dict[str, Any]:
    """
    Build Socrata SoQL query parameters from our input schema.

    Maps our legacy parameters to Socrata API parameters using SoQL.
    """
    params = {}

    # Ordering (datetime is the primary field in Socrata)
    if input_data.order == "new":
        params["$order"] = "datetime DESC"
    else:
        params["$order"] = "datetime ASC"

    # Pagination
    params["$limit"] = str(input_data.length)
    params["$offset"] = str(input_data.start)

    # Date filtering
    where_clauses = []

    if input_data.date != "Today" or input_data.dateEnd != "Today":
        # Convert date strings to actual dates for filtering
        if input_data.date == "Today":
            start_date = datetime.now().strftime("%Y-%m-%d")
        else:
            # Assume YYYY-MM-DD format or try to parse
            start_date = input_data.date

        if input_data.dateEnd == "Today":
            end_date = datetime.now().strftime("%Y-%m-%d")
        else:
            end_date = input_data.dateEnd

        # Add date range filter
        where_clauses.append(f"datetime >= '{start_date}T00:00:00.000'")
        where_clauses.append(f"datetime <= '{end_date}T23:59:59.999'")
    else:
        # Default to today's incidents
        today = datetime.now().strftime("%Y-%m-%d")
        where_clauses.append(f"datetime >= '{today}T00:00:00.000'")

    # Text search across relevant fields
    if input_data.search != "Any" and input_data.search.strip():
        search_term = input_data.search.strip()
        # Search in type and address fields
        search_clause = f"(upper(type) like upper('%{search_term}%') OR upper(address) like upper('%{search_term}%'))"
        where_clauses.append(search_clause)

    # Location/address filtering
    if input_data.location != "Any" and input_data.location.strip():
        location_term = input_data.location.strip()
        where_clauses.append(f"upper(address) like upper('%{location_term}%')")

    # Incident type filtering
    if input_data.type != "Any" and input_data.type.strip():
        type_term = input_data.type.strip()
        where_clauses.append(f"upper(type) like upper('%{type_term}%')")

    # Note: area and unit filters are not supported in Socrata data
    # These parameters are kept for backward compatibility but ignored

    # Combine all where clauses
    if where_clauses:
        params["$where"] = " AND ".join(where_clauses)

    return params


async def fetch_raw(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Low-level proxy tool for Seattle Fire Department Socrata API with normalization.

    Fetches incident data from the Seattle Fire Department via Socrata API,
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
        raise ValueError(f"Invalid arguments: {e}") from e

    # Build Socrata query parameters
    query_params = build_socrata_query_params(input_data)

    # Add cache TTL to params for caching purposes
    query_params["cacheTtlSeconds"] = input_data.cacheTtlSeconds

    logger.info(
        "Fetching SFD incidents from Socrata",
        extra={
            "order": input_data.order,
            "limit": input_data.length,
            "offset": input_data.start,
            "cache_ttl": input_data.cacheTtlSeconds,
            "query_params": query_params,
        },
    )

    # Get HTTP client and make request
    client = await get_client()
    raw_incidents, cache_hit = await client.fetch_incidents(
        query_params, input_data.cacheTtlSeconds
    )

    # Construct the request URL for source information
    base_url = client.base_url
    # Build query string from params (excluding internal cache param)
    query_items = []
    for k, v in query_params.items():
        if k != "cacheTtlSeconds":
            query_items.append(f"{k}={v}")
    query_string = "&".join(query_items)
    request_url = f"{base_url}?{query_string}"

    # Normalize the response
    try:
        normalized_response = normalize_full_response(
            raw_incidents, request_url, cache_hit, query_params
        )
    except Exception as e:
        logger.error(f"Failed to normalize response: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Failed to parse Socrata response: {e}"
        ) from e

    # Validate output against schema
    try:
        validated_response = FetchRawResponse(**normalized_response)
        result = validated_response.model_dump()
    except Exception as e:
        logger.error(f"Response validation failed: {e}")
        from ..http_client import MCPToolError

        raise MCPToolError(
            "SCHEMA_VALIDATION_ERROR", f"Response validation failed: {e}"
        ) from e

    logger.info(
        "Successfully fetched and normalized incidents from Socrata",
        extra={
            "incident_count": len(result["incidents"]),
            "cache_hit": cache_hit,
        },
    )

    return result
