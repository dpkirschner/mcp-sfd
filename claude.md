# Claude Development Configuration

## Project Overview
MCP Server for Seattle Fire Department Live Incident Proxy - provides tools for LLMs to fetch and analyze SFD live incident data.

## Development Commands

### Setup & Dependencies
```bash
# Install dependencies
pip install -e .

# Install dev dependencies
pip install pytest pytest-asyncio httpx pydantic mcp uvloop pytz

# Run tests
pytest

# Run specific test file
pytest tests/test_normalize.py

# Run with coverage
pytest --cov=mcp_sfd
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

### Running the Server
```bash
# Run MCP server locally
python -m mcp_sfd.server

# With environment variables
SFD_BASE_URL=https://sfdlive.com/api/data/ DEFAULT_CACHE_TTL=30 python -m mcp_sfd.server
```

## Project Structure
```
mcp_sfd/
  server.py                 # MCP server entry point, tool registration
  http_client.py            # httpx client with retry and headers
  schemas.py                # Pydantic models for request/response validation
  normalize.py              # data shaping and parsing helpers
  tools/
    fetch_raw.py           # Low-level proxy tool
    latest_incident.py     # Single latest incident
    is_fire_active.py      # Fire detection logic
    has_evac_orders.py     # Evacuation order detection
  tests/
    data/example_payload.json
    test_normalize.py
    test_tools.py
```

## Key Implementation Notes

### Tools to Implement
1. `sfd.fetch_raw` - Low-level API proxy with normalization
2. `sfd.latest_incident` - Returns single latest incident
3. `sfd.is_fire_active` - Fire detection with lookback logic
4. `sfd.has_evacuation_orders` - Evacuation keyword scanning

### Data Normalization Rules
- Flatten upstream `data` array structure
- Parse datetime as America/Los_Angeles → UTC
- Normalize lat/lng to numbers
- Split units like "E16*" to ["E16"]
- Convert active/late to booleans
- Preserve unknown fields under `raw`

### Error Handling
- Map HTTP errors to MCP tool errors with specific codes
- UPSTREAM_HTTP_ERROR, SCHEMA_VALIDATION_ERROR, UPSTREAM_TIMEOUT
- Include user-friendly messages for LLM

### Configuration
- `SFD_BASE_URL` (default: https://sfdlive.com/api/data/)
- `DEFAULT_CACHE_TTL` (default: 15 seconds)
- In-memory cache with TTL per query params

### Testing Strategy
- Unit tests for data normalization
- Integration tests with real API (feature flagged)
- Contract tests for Pydantic model validation
- Mock upstream responses for reliable CI