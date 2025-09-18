"""Data models for Seattle Fire Department incidents."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional


class IncidentStatus(Enum):
    """Status of an incident."""
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass
class Incident:
    """Represents a Seattle Fire Department incident."""
    
    incident_id: str
    datetime: datetime  # UTC timestamp
    priority: int
    units: List[str]  # ["E17", "L9"]
    address: str
    incident_type: str  # "Aid Response", "Rescue Elevator"
    status: IncidentStatus  # ACTIVE, CLOSED
    first_seen: datetime  # When first detected
    last_seen: datetime   # Last time in active feed
    closed_at: Optional[datetime] = None  # When marked closed
    
    def to_dict(self) -> dict:
        """Convert incident to dictionary for JSON serialization."""
        return {
            "incident_id": self.incident_id,
            "datetime": self.datetime.isoformat(),
            "priority": self.priority,
            "units": self.units,
            "address": self.address,
            "incident_type": self.incident_type,
            "status": self.status.value,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None
        }


@dataclass
class RawIncident:
    """Raw incident data from HTML parsing."""
    
    datetime_str: str
    incident_id: str
    priority_str: str
    units_str: str
    address: str
    incident_type: str


@dataclass
class IncidentSearchFilters:
    """Filters for searching incidents."""
    
    incident_type: Optional[str] = None
    address_contains: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    status: Optional[IncidentStatus] = None
    priority: Optional[int] = None


@dataclass
class HealthStatus:
    """Health status response."""
    
    status: str
    service: str
    version: str
    config: dict