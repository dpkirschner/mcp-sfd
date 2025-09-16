# MCP SFD - Seattle Fire Department MCP Server

A Model Context Protocol (MCP) server that provides tools for LLMs to fetch and analyze Seattle Fire Department live incident data.

## Features

- **Low-level API proxy** (`sfd.fetch_raw`) with normalization and caching
- **Latest incident retrieval** (`sfd.latest_incident`) for quick updates
- **Fire detection** (`sfd.is_fire_active`) with intelligent status analysis
- **Evacuation monitoring** (`sfd.has_evacuation_orders`) with keyword scanning
- Robust error handling and retry logic
- Comprehensive data normalization
- In-memory caching with configurable TTL

## Installation

```bash
# Install the package
pip install -e .

# Install development dependencies
pip install -e ".[dev]"
```

## Usage

### Running the MCP Server

```bash
# Run with default settings
python -m mcp_sfd.server

# Or use the CLI command
mcp-sfd
```

### Environment Variables

- `SFD_BASE_URL`: Base URL for SFD API (default: `https://sfdlive.com/api/data/`)
- `DEFAULT_CACHE_TTL`: Default cache TTL in seconds (default: 15)

### Available Tools

#### `sfd.fetch_raw`
Low-level proxy for the SFD API with full parameter control.

```json
{
  "order": "new",
  "length": 100,
  "search": "Any",
  "cacheTtlSeconds": 15
}
```

#### `sfd.latest_incident`
Returns the single most recent incident.

```json
{}
```

#### `sfd.is_fire_active`
Checks if there are any active fire incidents in Seattle.

```json
{
  "lookbackMinutes": 120
}
```

#### `sfd.has_evacuation_orders`
Scans for evacuation-related keywords in recent incidents.

```json
{
  "lookbackMinutes": 180
}
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mcp_sfd

# Run specific test file
pytest tests/test_normalize.py
```

### Code Quality

```bash
# Format code
black mcp_sfd/ tests/

# Lint
ruff check mcp_sfd/ tests/

# Type check
mypy mcp_sfd/
```

## Architecture

The server is built with several key components:

- **HTTP Client** (`http_client.py`): Handles API requests with retry logic and caching
- **Data Normalization** (`normalize.py`): Converts upstream API format to standardized schemas
- **Pydantic Schemas** (`schemas.py`): Type-safe data models for all inputs and outputs
- **Tool Implementations** (`tools/`): Individual MCP tool logic
- **Server** (`server.py`): MCP server registration and error handling

## Data Normalization

The server handles complex data transformations:

- Flattens nested upstream data structures
- Converts Seattle local time to UTC
- Normalizes coordinates from various formats
- Parses unit identifiers and status information
- Standardizes boolean fields

## Error Handling

All tools use standardized MCP error codes:

- `UPSTREAM_HTTP_ERROR`: API connectivity issues
- `UPSTREAM_TIMEOUT`: Request timeouts
- `SCHEMA_VALIDATION_ERROR`: Data parsing failures

## License

MIT
