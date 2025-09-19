"""
Implementation of seattle.get_active_incidents MCP tool.

This tool fetches currently active incidents from the FastAPI service
and formats them for LLM consumption with clear incident details.
"""

import logging
from datetime import datetime
from typing import Any

from mcp.types import TextContent

from ..api_client import MCPToolError, get_client

logger = logging.getLogger(__name__)


async def get_active_incidents(arguments: dict[str, Any]) -> list[TextContent]:
    """
    Fetch currently active incidents from Seattle Fire Department.

    This tool retrieves active incidents from the FastAPI service and formats
    them in a clear, readable format for LLM analysis and user consumption.

    Args:
        arguments: Tool arguments containing:
            - cache_ttl_seconds (optional): Cache TTL override (default: 15)

    Returns:
        List containing a single TextContent with formatted incident data

    Raises:
        MCPToolError: When the FastAPI service is unavailable or returns invalid data
    """
    cache_ttl = arguments.get("cache_ttl_seconds", 15)

    logger.info(
        "Fetching active incidents",
        extra={"cache_ttl": cache_ttl, "tool": "get_active_incidents"},
    )

    try:
        # Get the API client
        client = await get_client()

        # Fetch active incidents from FastAPI service
        incidents = await client.get_active_incidents()

        # Format response for LLM consumption
        if not incidents:
            response_text = (
                "No active Seattle Fire Department incidents found.\n\n"
                f"Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
        else:
            # Format incidents in a clear, readable way
            formatted_incidents = []
            for incident in incidents:
                # Extract key fields with safe defaults
                incident_id = incident.get("incident_id", "Unknown")
                incident_time = _format_incident_time(incident.get("incident_datetime"))
                incident_type = incident.get("incident_type") or "Unknown Type"
                address = incident.get("address") or "Unknown Address"
                units = _format_units(incident.get("units"))
                status = incident.get("status") or "unknown"
                priority = incident.get("priority", "unknown")

                # Create formatted line for this incident
                incident_line = (
                    f"{incident_id} | {incident_time} | {incident_type} | {address}"
                )
                if units:
                    incident_line += f" | Units: {units}"
                if priority != "unknown":
                    incident_line += f" | Priority: {priority}"
                if status != "unknown":
                    incident_line += f" | Status: {status}"

                formatted_incidents.append(incident_line)

            # Build complete response
            header = f"Active Seattle Fire Department Incidents ({len(incidents)} incidents found)\n"
            separator = "=" * 80 + "\n"
            incidents_text = "\n".join(formatted_incidents)
            footer = (
                f"\nLast updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )

            response_text = header + separator + incidents_text + footer

        logger.info(
            "Successfully fetched active incidents",
            extra={"incident_count": len(incidents), "tool": "get_active_incidents"},
        )

        return [TextContent(type="text", text=response_text)]

    except MCPToolError as e:
        # Re-raise MCP tool errors with context
        logger.error(
            "FastAPI service error while fetching active incidents",
            extra={
                "error_code": e.code,
                "error_message": e.message,
                "tool": "get_active_incidents",
            },
        )

        # Provide user-friendly error messages
        if e.code == "SERVICE_UNAVAILABLE":
            error_text = (
                "❌ Cannot connect to the Seattle Fire Department data service.\n\n"
                "This could mean:\n"
                "- The FastAPI service is not running\n"
                "- Network connectivity issues\n"
                "- Service is temporarily unavailable\n\n"
                "Please check that the FastAPI service is running and accessible."
            )
        elif e.code == "UPSTREAM_TIMEOUT":
            error_text = (
                "⏱️ Request to Seattle Fire Department data service timed out.\n\n"
                "The service may be experiencing high load or temporary issues. "
                "Please try again in a few moments."
            )
        elif e.code == "SCHEMA_VALIDATION_ERROR":
            error_text = (
                "📋 Received invalid data format from the service.\n\n"
                "This indicates a potential issue with the data service. "
                "Please check the service logs or try again later."
            )
        else:
            error_text = (
                f"🚨 Unexpected error from Seattle Fire Department service: {e.message}\n\n"
                "Please check the service status and try again."
            )

        return [TextContent(type="text", text=error_text)]

    except Exception as e:
        # Handle unexpected errors
        logger.error(
            "Unexpected error in get_active_incidents",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "tool": "get_active_incidents",
            },
            exc_info=True,
        )

        error_text = (
            f"💥 An unexpected error occurred: {str(e)}\n\n"
            "This is likely a bug in the tool implementation. "
            "Please check the logs for more details."
        )

        return [TextContent(type="text", text=error_text)]


def _format_incident_time(incident_datetime: str | None) -> str:
    """Format incident datetime for display."""
    if not incident_datetime:
        return "Unknown Time"

    try:
        # Try to parse ISO format datetime
        if "T" in incident_datetime:
            dt = datetime.fromisoformat(incident_datetime.replace("Z", "+00:00"))
            return dt.strftime("%I:%M %p")
        else:
            # Fallback for other formats
            return incident_datetime
    except (ValueError, AttributeError):
        return incident_datetime or "Unknown Time"


def _format_units(units: list[str] | None) -> str:
    """Format units list for display."""
    if not units:
        return ""

    # Handle case where units might be a single string
    if isinstance(units, str):
        return units

    # Join multiple units with commas
    if isinstance(units, list):
        return ", ".join(str(unit) for unit in units if unit)

    return str(units)
