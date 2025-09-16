"""
MCP Server for Seattle Fire Department Live Incident Proxy.

This server provides tools for LLMs to fetch and analyze Seattle Fire Department
live incident data through the Model Context Protocol.
"""

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .http_client import MCPToolError, close_client
from .tools.active_incidents import active_incidents
from .tools.fetch_raw import fetch_raw
from .tools.has_evac_orders import has_evacuation_orders
from .tools.is_fire_active import is_fire_active
from .tools.latest_incident import latest_incident

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("mcp-sfd")

# Create the MCP server
server = Server("mcp-sfd")


# Tool definitions with schemas
TOOLS = [
    Tool(
        name="sfd.fetch_raw",
        description=(
            "Low-level proxy tool for SFD API with normalization and pagination controls. "
            "Fetches incident data with customizable filters and returns normalized results."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "order": {
                    "type": "string",
                    "enum": ["new", "old"],
                    "default": "new",
                    "description": "Order incidents by date",
                },
                "start": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Starting offset for pagination",
                },
                "length": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                    "description": "Number of results per page",
                },
                "search": {
                    "type": "string",
                    "default": "Any",
                    "description": "Free text search filter",
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "Page number (1-based)",
                },
                "location": {
                    "type": "string",
                    "default": "Any",
                    "description": "Location filter",
                },
                "unit": {
                    "type": "string",
                    "default": "Any",
                    "description": "Unit filter",
                },
                "type": {
                    "type": "string",
                    "default": "Any",
                    "description": "Incident type filter",
                },
                "area": {
                    "type": "string",
                    "default": "Any",
                    "description": "Area filter",
                },
                "date": {
                    "type": "string",
                    "default": "Today",
                    "description": "Start date filter",
                },
                "dateEnd": {
                    "type": "string",
                    "default": "Today",
                    "description": "End date filter",
                },
                "cacheTtlSeconds": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 15,
                    "description": "Cache TTL in seconds",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="sfd.latest_incident",
        description=(
            "Returns the single latest incident by datetime. "
            "Gets the most recent incident from today's data."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="sfd.active_incidents",
        description=(
            "Returns only currently active incidents from today's SFD data. "
            "Filters for ongoing emergency situations by checking the active status. "
            "Ideal for getting a current snapshot of active emergencies."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cacheTtlSeconds": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 15,
                    "description": "Cache TTL in seconds",
                },
            },
        },
    ),
    Tool(
        name="sfd.is_fire_active",
        description=(
            "Answers 'is there a fire in Seattle?' by checking if any recent incidents "
            "are fire-related and still active. Uses intelligent detection of fire types "
            "and unit status to determine activity."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lookbackMinutes": {
                    "type": "integer",
                    "minimum": 15,
                    "maximum": 360,
                    "default": 120,
                    "description": "How many minutes back to look for fire incidents",
                },
            },
        },
    ),
    Tool(
        name="sfd.has_evacuation_orders",
        description=(
            "Answers 'are there any evacuation orders?' by scanning incident descriptions "
            "for evacuation keywords. Includes guidance about official evacuation sources."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lookbackMinutes": {
                    "type": "integer",
                    "minimum": 30,
                    "maximum": 720,
                    "default": 180,
                    "description": "How many minutes back to look for evacuation orders",
                },
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    """Handle tool calls."""
    if arguments is None:
        arguments = {}

    logger.info(f"Tool called: {name}", extra={"tool": name, "arguments": arguments})

    try:
        # Route to appropriate tool function
        if name == "sfd.fetch_raw":
            result = await fetch_raw(arguments)
        elif name == "sfd.latest_incident":
            result = await latest_incident(arguments)
        elif name == "sfd.active_incidents":
            result = await active_incidents(arguments)
        elif name == "sfd.is_fire_active":
            result = await is_fire_active(arguments)
        elif name == "sfd.has_evacuation_orders":
            result = await has_evacuation_orders(arguments)
        else:
            logger.error(f"Unknown tool: {name}")
            raise ValueError(f"Unknown tool: {name}")

        # Format response as JSON
        response_text = json.dumps(result, indent=2, default=str)

        logger.info(
            f"Tool {name} completed successfully",
            extra={
                "tool": name,
                "result_size": len(response_text),
                "status": "success",
            },
        )

        return [TextContent(type="text", text=response_text)]

    except MCPToolError as e:
        # Handle MCP-specific errors with proper error codes
        error_msg = f"Tool error ({e.code}): {e.message}"
        logger.error(
            f"Tool {name} failed with MCP error",
            extra={
                "tool": name,
                "error_code": e.code,
                "error_message": e.message,
                "status": "error",
            },
        )
        return [TextContent(type="text", text=error_msg)]

    except ValueError as e:
        # Handle validation errors
        error_msg = f"Validation error: {str(e)}"
        logger.error(
            f"Tool {name} failed with validation error",
            extra={
                "tool": name,
                "error": str(e),
                "status": "error",
            },
        )
        return [TextContent(type="text", text=error_msg)]

    except Exception as e:
        # Handle unexpected errors
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(
            f"Tool {name} failed with unexpected error",
            extra={
                "tool": name,
                "error": str(e),
                "status": "error",
            },
            exc_info=True,
        )
        return [TextContent(type="text", text=error_msg)]


async def cleanup():
    """Cleanup resources on shutdown."""
    logger.info("Shutting down MCP server")
    await close_client()


async def main():
    """Main entry point for the MCP server."""
    logger.info("Starting MCP SFD server")

    # Log configuration
    import os

    logger.info(
        "Server configuration",
        extra={
            "base_url": os.getenv("SFD_BASE_URL", "https://sfdlive.com/api/data/"),
            "default_cache_ttl": os.getenv("DEFAULT_CACHE_TTL", "15"),
            "tools_count": len(TOOLS),
        },
    )

    try:
        # Run the server with stdio transport
        async with stdio_server() as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
    finally:
        await cleanup()


def cli_main():
    """CLI entry point for the server."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
