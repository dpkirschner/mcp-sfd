"""
Pydantic schemas for SFD MCP server.

This module defines all the data models used for validating input and output
of the MCP tools that interact with Seattle Fire Department incident data.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UnitStatus(BaseModel):
    """Status timestamps for emergency response units."""

    dispatched: str | None = None
    arrived: str | None = None
    transport: str | None = None
    in_service: str | None = None


class Incident(BaseModel):
    """A single emergency incident from the SFD live feed."""

    id: int
    incident_number: str
    type: str
    type_code: str | None = None
    description: str
    description_clean: str | None = None
    response_type: str | None = None
    response_mode: str | None = None
    datetime_local: datetime
    datetime_utc: datetime
    latitude: float | None = None
    longitude: float | None = None
    address: str
    area: str | None = None
    battalion: str | None = None
    units: list[str] = Field(default_factory=list)
    primary_unit: str | None = None
    unit_status: dict[str, UnitStatus] = Field(default_factory=dict)
    active: bool = False
    alarm: int | None = None
    late: bool = False
    raw: dict[str, Any] | None = None  # Preserve original data for debugging


class ResponseMeta(BaseModel):
    """Metadata about the API response."""

    page: int
    total_pages: int | None = None
    results_per_page: int
    total_incidents: int | None = None
    offset: int | None = None
    order: str
    users_online: int | None = None


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
    search: str = "Any"
    page: int = Field(default=1, ge=1)
    location: str = "Any"
    unit: str = "Any"
    type: str = "Any"
    area: str = "Any"
    date: str = "Today"
    dateEnd: str = "Today"
    cacheTtlSeconds: int = Field(default=15, ge=0)


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

    id: int
    incident_number: str
    type: str
    description: str
    time: str  # Local time formatted as "6:55 PM"
    address: str
    area: str | None = None
    units: list[str] = Field(default_factory=list)
    active: bool = True


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
