"""Incident API routes for FastAPI."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..api_models import (
    IncidentResponse,
    IncidentsResponse,
)
from ..cache import IncidentCache
from ..models import Incident, IncidentStatus

logger = logging.getLogger(__name__)

# Create router for incident endpoints
router = APIRouter(prefix="/incidents", tags=["incidents"])

# Global cache instance (will be set by main application)
_cache: IncidentCache | None = None


def set_cache(cache: IncidentCache) -> None:
    """Set the global cache instance."""
    global _cache
    _cache = cache


def get_cache() -> IncidentCache:
    """Dependency to get the cache instance."""
    if _cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service not available",
        )
    return _cache


@router.get(
    "/active",
    response_model=IncidentsResponse,
    summary="Get active incidents",
    description="Returns all currently active incidents from the cache",
)
async def get_active_incidents(
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of incidents to return"
    ),
    offset: int = Query(0, ge=0, description="Number of incidents to skip"),
    cache: IncidentCache = Depends(get_cache),
) -> IncidentsResponse:
    """Get all currently active incidents.

    Args:
        limit: Maximum number of incidents to return
        offset: Number of incidents to skip for pagination
        cache: Cache dependency

    Returns:
        IncidentsResponse with active incidents

    Raises:
        HTTPException: If cache operation fails
    """
    try:
        logger.debug(f"Fetching active incidents with limit={limit}, offset={offset}")

        # Get active incidents from cache
        active_incidents = cache.get_active_incidents()

        # Apply pagination
        total_count = len(active_incidents)
        paginated_incidents = active_incidents[offset : offset + limit]

        logger.info(
            f"Retrieved {len(paginated_incidents)} active incidents out of {total_count} total"
        )

        return IncidentsResponse(
            success=True,
            message=f"Retrieved {len(paginated_incidents)} active incidents",
            data=paginated_incidents,
            count=len(paginated_incidents),
            metadata={
                "total_active": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count,
            },
        )

    except Exception as e:
        logger.error(f"Failed to retrieve active incidents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve active incidents: {str(e)}",
        ) from e


@router.get(
    "/all",
    response_model=IncidentsResponse,
    summary="Get all incidents",
    description="Returns all incidents (active and closed) from the cache",
)
async def get_all_incidents(
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of incidents to return"
    ),
    offset: int = Query(0, ge=0, description="Number of incidents to skip"),
    status_filter: IncidentStatus | None = Query(
        None, alias="status", description="Filter by incident status"
    ),
    incident_type: str | None = Query(
        None, description="Filter by incident type (partial match)"
    ),
    address: str | None = Query(None, description="Filter by address (partial match)"),
    priority: int | None = Query(
        None, ge=1, le=10, description="Filter by priority level"
    ),
    since: datetime | None = Query(
        None, description="Filter incidents after this datetime"
    ),
    until: datetime | None = Query(
        None, description="Filter incidents before this datetime"
    ),
    cache: IncidentCache = Depends(get_cache),
) -> IncidentsResponse:
    """Get all incidents with optional filtering.

    Args:
        limit: Maximum number of incidents to return
        offset: Number of incidents to skip for pagination
        status_filter: Filter by incident status
        incident_type: Filter by incident type (partial match)
        address: Filter by address (partial match)
        priority: Filter by priority level
        since: Filter incidents after this datetime
        until: Filter incidents before this datetime
        cache: Cache dependency

    Returns:
        IncidentsResponse with filtered incidents

    Raises:
        HTTPException: If cache operation fails or validation errors
    """
    try:
        logger.debug(
            f"Fetching all incidents with filters: status={status_filter}, "
            f"type={incident_type}, address={address}, priority={priority}"
        )

        # Validate datetime range
        if since and until and since > until:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'since' parameter must be before 'until' parameter",
            )

        # Get all incidents from cache
        all_incidents = cache.get_all_incidents()

        # Apply filters
        filtered_incidents = _apply_filters(
            all_incidents,
            status_filter=status_filter,
            incident_type=incident_type,
            address=address,
            priority=priority,
            since=since,
            until=until,
        )

        # Apply pagination
        total_count = len(filtered_incidents)
        paginated_incidents = filtered_incidents[offset : offset + limit]

        logger.info(
            f"Retrieved {len(paginated_incidents)} incidents out of {total_count} filtered "
            f"from {len(all_incidents)} total"
        )

        return IncidentsResponse(
            success=True,
            message=f"Retrieved {len(paginated_incidents)} incidents",
            data=paginated_incidents,
            count=len(paginated_incidents),
            metadata={
                "total_filtered": total_count,
                "total_available": len(all_incidents),
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count,
                "filters_applied": {
                    "status": status_filter if status_filter else None,
                    "incident_type": incident_type,
                    "address": address,
                    "priority": priority,
                    "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None,
                },
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve incidents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve incidents: {str(e)}",
        ) from e


@router.get(
    "/search",
    response_model=IncidentsResponse,
    summary="Search incidents",
    description="Search incidents with flexible filtering options",
)
async def search_incidents(
    q: str | None = Query(
        None, description="General search query (searches type and address)"
    ),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of incidents to return"
    ),
    offset: int = Query(0, ge=0, description="Number of incidents to skip"),
    status_filter: IncidentStatus | None = Query(
        None, alias="status", description="Filter by incident status"
    ),
    incident_type: str | None = Query(
        None, description="Filter by incident type (partial match)"
    ),
    address: str | None = Query(None, description="Filter by address (partial match)"),
    priority: int | None = Query(
        None, ge=1, le=10, description="Filter by priority level"
    ),
    since: datetime | None = Query(
        None, description="Filter incidents after this datetime"
    ),
    until: datetime | None = Query(
        None, description="Filter incidents before this datetime"
    ),
    cache: IncidentCache = Depends(get_cache),
) -> IncidentsResponse:
    """Search incidents with flexible filtering options.

    Args:
        q: General search query that searches both incident type and address
        limit: Maximum number of incidents to return
        offset: Number of incidents to skip for pagination
        status_filter: Filter by incident status
        incident_type: Filter by incident type (partial match)
        address: Filter by address (partial match)
        priority: Filter by priority level
        since: Filter incidents after this datetime
        until: Filter incidents before this datetime
        cache: Cache dependency

    Returns:
        IncidentsResponse with search results

    Raises:
        HTTPException: If cache operation fails or validation errors
    """
    try:
        logger.debug(
            f"Searching incidents with query='{q}', filters: status={status_filter}, "
            f"type={incident_type}, address={address}, priority={priority}"
        )

        # Validate datetime range
        if since and until and since > until:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="'since' parameter must be before 'until' parameter",
            )

        # Get all incidents from cache
        all_incidents = cache.get_all_incidents()

        # Apply search filters
        filtered_incidents = _apply_search_filters(
            all_incidents,
            general_query=q,
            status_filter=status_filter,
            incident_type=incident_type,
            address=address,
            priority=priority,
            since=since,
            until=until,
        )

        # Apply pagination
        total_count = len(filtered_incidents)
        paginated_incidents = filtered_incidents[offset : offset + limit]

        logger.info(
            f"Search returned {len(paginated_incidents)} incidents out of {total_count} matches "
            f"from {len(all_incidents)} total"
        )

        return IncidentsResponse(
            success=True,
            message=f"Found {len(paginated_incidents)} incidents matching search criteria",
            data=paginated_incidents,
            count=len(paginated_incidents),
            metadata={
                "total_matches": total_count,
                "total_available": len(all_incidents),
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count,
                "search_query": q,
                "filters_applied": {
                    "status": status_filter if status_filter else None,
                    "incident_type": incident_type,
                    "address": address,
                    "priority": priority,
                    "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None,
                },
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search incidents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search incidents: {str(e)}",
        ) from e


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Get specific incident",
    description="Returns a specific incident by its ID",
)
async def get_incident_by_id(
    incident_id: str, cache: IncidentCache = Depends(get_cache)
) -> IncidentResponse:
    """Get a specific incident by ID.

    Args:
        incident_id: The unique incident identifier
        cache: Cache dependency

    Returns:
        IncidentResponse with the incident data

    Raises:
        HTTPException: If incident not found or cache operation fails
    """
    try:
        logger.debug(f"Fetching incident with ID: {incident_id}")

        # Validate incident ID
        if not incident_id or not incident_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incident ID cannot be empty",
            )

        incident_id = incident_id.strip()

        # Get incident from cache
        incident = cache.get_incident(incident_id)

        if incident is None:
            logger.warning(f"Incident not found: {incident_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Incident with ID '{incident_id}' not found",
            )

        logger.info(f"Retrieved incident: {incident_id}")

        return IncidentResponse(
            success=True, message=f"Retrieved incident {incident_id}", data=incident
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve incident {incident_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve incident: {str(e)}",
        ) from e


def _apply_filters(
    incidents: list[Incident],
    status_filter: IncidentStatus | None = None,
    incident_type: str | None = None,
    address: str | None = None,
    priority: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Incident]:
    """Apply filters to incidents list.

    Args:
        incidents: List of incidents to filter
        status_filter: Filter by incident status
        incident_type: Filter by incident type (partial match)
        address: Filter by address (partial match)
        priority: Filter by priority level
        since: Filter incidents after this datetime
        until: Filter incidents before this datetime

    Returns:
        List of filtered incidents
    """
    filtered = incidents

    # Filter by status
    if status_filter is not None:
        # Filter by enum instance directly
        filtered = [i for i in filtered if i.status == status_filter]

    # Filter by incident type (partial match, case-insensitive)
    if incident_type:
        incident_type_lower = incident_type.lower()
        filtered = [
            i for i in filtered if incident_type_lower in i.incident_type.lower()
        ]

    # Filter by address (partial match, case-insensitive)
    if address:
        address_lower = address.lower()
        filtered = [i for i in filtered if address_lower in i.address.lower()]

    # Filter by priority
    if priority is not None:
        filtered = [i for i in filtered if i.priority == priority]

    # Filter by date range
    if since:
        filtered = [i for i in filtered if i.incident_datetime >= since]

    if until:
        filtered = [i for i in filtered if i.incident_datetime <= until]

    return filtered


def _apply_search_filters(
    incidents: list[Incident],
    general_query: str | None = None,
    status_filter: IncidentStatus | None = None,
    incident_type: str | None = None,
    address: str | None = None,
    priority: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Incident]:
    """Apply search filters to incidents list with general query support.

    Args:
        incidents: List of incidents to filter
        general_query: General search query that searches across multiple fields
        status_filter: Filter by incident status
        incident_type: Filter by incident type (partial match)
        address: Filter by address (partial match)
        priority: Filter by priority level
        since: Filter incidents after this datetime
        until: Filter incidents before this datetime

    Returns:
        List of filtered incidents
    """
    filtered = incidents

    # Apply general query first (searches across multiple fields)
    if general_query:
        query_lower = general_query.lower()
        filtered = [
            i
            for i in filtered
            if (
                query_lower in i.incident_type.lower()
                or query_lower in i.address.lower()
                or query_lower in i.incident_id.lower()
                or any(query_lower in unit.lower() for unit in i.units)
            )
        ]

    # Apply specific filters using existing logic
    return _apply_filters(
        filtered,
        status_filter=status_filter,
        incident_type=incident_type,
        address=address,
        priority=priority,
        since=since,
        until=until,
    )
