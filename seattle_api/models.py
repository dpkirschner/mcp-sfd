"""Data models for Seattle Fire Department incidents."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class IncidentStatus(Enum):
    """Status of an incident."""

    ACTIVE = "active"
    CLOSED = "closed"


class Incident(BaseModel):
    """Represents a Seattle Fire Department incident."""

    incident_id: str = Field(
        ..., min_length=1, description="Unique incident identifier"
    )
    incident_datetime: datetime = Field(..., description="Incident datetime in UTC")
    priority: int = Field(..., ge=1, le=10, description="Incident priority (1-10)")
    units: list[str] = Field(
        default_factory=list, description="List of responding units"
    )
    address: str = Field(..., min_length=1, description="Incident address")
    incident_type: str = Field(..., min_length=1, description="Type of incident")
    status: IncidentStatus = Field(
        default=IncidentStatus.ACTIVE, description="Current incident status"
    )
    first_seen: datetime = Field(..., description="When incident was first detected")
    last_seen: datetime = Field(
        ..., description="Last time incident was seen in active feed"
    )
    closed_at: datetime | None = Field(
        None, description="When incident was marked closed"
    )

    @field_validator("incident_id")
    @classmethod
    def validate_incident_id(cls, v):
        """Validate incident ID format."""
        if not v or not v.strip():
            raise ValueError("Incident ID cannot be empty")
        return v.strip()

    @field_validator("address")
    @classmethod
    def validate_address(cls, v):
        """Validate and clean address."""
        if not v or not v.strip():
            raise ValueError("Address cannot be empty")
        return v.strip()

    @field_validator("incident_type")
    @classmethod
    def validate_incident_type(cls, v):
        """Validate and clean incident type."""
        if not v or not v.strip():
            raise ValueError("Incident type cannot be empty")
        return v.strip()

    @field_validator("units")
    @classmethod
    def validate_units(cls, v):
        """Validate units list."""
        # Filter out empty strings and clean units
        cleaned_units = [unit.strip() for unit in v if unit and unit.strip()]
        return cleaned_units

    model_config = ConfigDict(
        use_enum_values=True,
    )

    @field_serializer("incident_datetime", "first_seen", "last_seen", "closed_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        """Serialize datetime fields to ISO format."""
        return value.isoformat() if value else None


class RawIncident(BaseModel):
    """Raw incident data from HTML parsing."""

    datetime_str: str = Field(
        ..., min_length=1, description="Raw datetime string from HTML"
    )
    incident_id: str = Field(..., min_length=1, description="Raw incident ID from HTML")
    priority_str: str = Field(..., description="Raw priority string from HTML")
    units_str: str = Field(default="", description="Raw units string from HTML")
    address: str = Field(..., min_length=1, description="Raw address from HTML")
    incident_type: str = Field(
        ..., min_length=1, description="Raw incident type from HTML"
    )

    @field_validator("datetime_str", "incident_id", "address", "incident_type")
    @classmethod
    def validate_required_fields(cls, v):
        """Validate required fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("units_str", "priority_str")
    @classmethod
    def clean_optional_fields(cls, v):
        """Clean optional fields."""
        return v.strip() if v else ""


class IncidentSearchFilters(BaseModel):
    """Filters for searching incidents."""

    incident_type: str | None = Field(None, description="Filter by incident type")
    address_contains: str | None = Field(
        None, description="Filter by address containing text"
    )
    since: datetime | None = Field(
        None, description="Filter incidents after this datetime"
    )
    until: datetime | None = Field(
        None, description="Filter incidents before this datetime"
    )
    status: IncidentStatus | None = Field(None, description="Filter by incident status")
    priority: int | None = Field(
        None, ge=1, le=10, description="Filter by priority level"
    )

    @field_validator("incident_type", "address_contains")
    @classmethod
    def clean_string_filters(cls, v):
        """Clean string filter values."""
        return v.strip() if v else None


class HealthStatus(BaseModel):
    """Health status response."""

    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    config: dict = Field(default_factory=dict, description="Configuration details")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        """Validate status is one of expected values."""
        valid_statuses = ["healthy", "degraded", "unhealthy"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {valid_statuses}")
        return v
