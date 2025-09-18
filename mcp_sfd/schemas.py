"""
Pydantic schemas for SFD MCP server.

This module defines all the data models used for validating input and output
of the MCP tools that interact with Seattle Fire Department data via Socrata API.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportLocation(BaseModel):
    """Geospatial point for incident location."""

    type: str = "Point"
    coordinates: list[float] = Field(default_factory=list)  # [longitude, latitude]


class Incident(BaseModel):
    """A single emergency incident from the Seattle Socrata API."""

    incident_number: str
    type: str
    address: str
    datetime_local: datetime
    datetime_utc: datetime
    latitude: float | None = None
    longitude: float | None = None
    report_location: ReportLocation | None = None

    # Computed region fields from Socrata
    computed_region_ru88_fbhk: str | None = None
    computed_region_kuhn_3gp2: str | None = None
    computed_region_q256_3sug: str | None = None

    # Derived fields for compatibility
    estimated_active: bool = False  # Based on time heuristics
    raw: dict[str, Any] | None = None  # Preserve original data for debugging


class ResponseMeta(BaseModel):
    """Metadata about the Socrata API response."""

    results_returned: int
    order: str
    limit: int
    offset: int = 0
    query_params: dict[str, Any] = Field(default_factory=dict)


class ResponseSource(BaseModel):
    """Information about the data source and fetch details."""

    url: str
    fetched_at: datetime
    cache_hit: bool


class FetchRawResponse(BaseModel):
    """Response schema for sfd.fetch_raw tool."""

    meta: ResponseMeta
    incidents: list[Incident]
    source: ResponseSource


# Input schemas for tools


class FetchRawInput(BaseModel):
    """Input schema for sfd.fetch_raw tool."""

    order: str = Field(default="new", pattern="^(new|old)$")
    start: int = Field(default=0, ge=0)
    length: int = Field(default=100, ge=1, le=500)
    search: str = "Any"  # Free text search
    page: int = Field(default=1, ge=1)
    location: str = "Any"  # Address filter
    type: str = "Any"  # Incident type filter
    area: str = "Any"  # Not directly supported in Socrata
    date: str = "Today"  # Start date
    dateEnd: str = "Today"  # End date
    cacheTtlSeconds: int = Field(default=15, ge=0)

    # Legacy parameters kept for compatibility but ignored
    unit: str = "Any"  # Units not available in Socrata data


class LatestIncidentInput(BaseModel):
    """Input schema for sfd.latest_incident tool."""

    pass  # No parameters required


class LatestIncidentResponse(BaseModel):
    """Response schema for sfd.latest_incident tool."""

    incident: Incident
    source: ResponseSource


class IsFireActiveInput(BaseModel):
    """Input schema for sfd.is_fire_active tool."""

    lookbackMinutes: int = Field(default=120, ge=15, le=360)


class IsFireActiveResponse(BaseModel):
    """Response schema for sfd.is_fire_active tool."""

    is_fire_active: bool
    matching_incidents: list[Incident]
    reasoning: str


class HasEvacuationOrdersInput(BaseModel):
    """Input schema for sfd.has_evacuation_orders tool."""

    lookbackMinutes: int = Field(default=180, ge=30, le=720)


class HasEvacuationOrdersResponse(BaseModel):
    """Response schema for sfd.has_evacuation_orders tool."""

    has_evacuation_orders: bool
    supporting_incidents: list[Incident]
    notes: str


class ActiveIncidentsInput(BaseModel):
    """Input schema for sfd.active_incidents tool."""

    cacheTtlSeconds: int = Field(default=15, ge=0)


class ActiveIncidentSummary(BaseModel):
    """Lightweight incident summary for active incidents tool."""

    incident_number: str
    type: str
    time: str  # Local time formatted as "6:55 PM"
    address: str
    estimated_active: bool = True


class ActiveIncidentsResponse(BaseModel):
    """Response schema for sfd.active_incidents tool."""

    meta: ResponseMeta
    incidents: list[Incident]
    source: ResponseSource


class ActiveIncidentsLightResponse(BaseModel):
    """Lightweight response schema for sfd.active_incidents tool."""

    count: int
    incidents: list[ActiveIncidentSummary]
    fetched_at: str
    cache_hit: bool


# Constants for fire detection logic
FIRE_KEYWORDS = [
    "fire",
    "fire in building",
    "brush fire",
    "car fire",
    "marine fire",
    "fir",  # type_code
]

FIRE_EXCLUSIONS = [
    "water rescue",  # Only excluded if description doesn't contain fire
]

# Constants for evacuation detection logic
EVACUATION_KEYWORDS = [
    "evacuation",
    "evacuate",
    "evacuation order",
    "evacuation advisory",
    "evacuations in progress",
]
