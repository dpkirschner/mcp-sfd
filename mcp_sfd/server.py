"""
MCP Server for Seattle Fire Department Live Incident Proxy.

This server provides tools for LLMs to fetch and analyze Seattle Fire Department
live incident data through the Model Context Protocol.
"""

import asyncio
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Import tool implementations
from .tools.get_active_incidents import get_active_incidents

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
        name="seattle.get_active_incidents",
        description="Get currently active incidents from Seattle Fire Department",
        inputSchema={
            "type": "object",
            "properties": {
                "cache_ttl_seconds": {
                    "type": "integer",
                    "description": "Cache TTL override in seconds (default: 15)",
                    "minimum": 0,
                    "maximum": 300,
                    "default": 15,
                }
            },
            "additionalProperties": False,
        },
    )
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
        # Route to tool implementations
        if name == "seattle.get_active_incidents":
            return await get_active_incidents(arguments)
        else:
            logger.error(f"Unknown tool: {name}")
            raise ValueError(f"Unknown tool: {name}")

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


async def cleanup() -> None:
    """Cleanup resources on shutdown."""
    logger.info("Shutting down MCP server")
    # Clean up FastAPI client connections
    from .api_client import close_client

    await close_client()


async def main() -> None:
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


def cli_main() -> None:
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
