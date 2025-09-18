"""API response models for FastAPI endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .models import Incident, IncidentStatus


class APIResponse(BaseModel):
    """Base API response model."""

    success: bool = Field(..., description="Whether the request was successful")
    message: str = Field(..., description="Response message")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Response timestamp"
    )


class IncidentResponse(APIResponse):
    """Response model for single incident."""

    data: Incident | None = Field(None, description="Incident data")


class IncidentsResponse(APIResponse):
    """Response model for multiple incidents."""

    data: list[Incident] = Field(default_factory=list, description="List of incidents")
    count: int = Field(..., description="Number of incidents returned")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class ErrorResponse(APIResponse):
    """Error response model."""

    error_code: str = Field(..., description="Error code identifier")
    error_details: dict[str, Any] | None = Field(
        None, description="Additional error details"
    )

    def __init__(self, **data):
        """Initialize error response with success=False."""
        data.setdefault("success", False)
        super().__init__(**data)


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Health check timestamp"
    )
    config: dict[str, Any] = Field(
        default_factory=dict, description="Configuration details"
    )
    poller_status: dict[str, Any] | None = Field(
        None, description="Poller health status"
    )


class IncidentSearchParams(BaseModel):
    """Query parameters for incident search."""

    limit: int | None = Field(
        100, ge=1, le=1000, description="Maximum number of incidents to return"
    )
    offset: int | None = Field(0, ge=0, description="Number of incidents to skip")
    status: IncidentStatus | None = Field(None, description="Filter by incident status")
    incident_type: str | None = Field(
        None, description="Filter by incident type (partial match)"
    )
    address: str | None = Field(None, description="Filter by address (partial match)")
    priority: int | None = Field(
        None, ge=1, le=10, description="Filter by priority level"
    )
    since: datetime | None = Field(
        None, description="Filter incidents after this datetime"
    )
    until: datetime | None = Field(
        None, description="Filter incidents before this datetime"
    )

    class Config:
        """Pydantic configuration."""

        json_encoders = {
            datetime: lambda v: v.isoformat(),
            IncidentStatus: lambda v: v.value,
        }
