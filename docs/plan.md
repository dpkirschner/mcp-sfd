```markdown
# Spec: Python MCP Server for SFD Live Incident Proxy

Goal: Build a Python MCP server that exposes tools a local LLM can call to fetch and reason over Seattle Fire Department live incidents via `https://sfdlive.com/api/data/`. The server will proxy the GET API, normalize the data into stable schemas, and provide helper tools that answer common questions directly.

Audience: Local coding model that will implement the server. Keep interfaces explicit and deterministic.

## 1) Scope and Success Criteria

### In scope
- MCP server that runs locally and registers tools callable by an LLM.
- A low level proxy tool that mirrors the remote GET endpoint while validating and normalizing the response.
- High level helper tools that compute answers like:
  - “is there a fire in seattle?”
  - “what is the latest incident?”
  - “are there any evacuation orders?”
- Basic query parameters for time filters, pagination, and simple keyword search.
- Light caching to avoid hammering the origin.
- Deterministic JSON schemas with types, enums, and date parsing.

### Out of scope
- Webhooks, subscriptions, or push updates.
- Persistence beyond an in-memory cache.
- Auth or multi tenant features.

Success = The LLM can call MCP tools to:
- Retrieve the latest incidents with stable JSON.
- Ask yes/no about fires and get correct evidence.
- Ask about evacuation notices and get a definitive status based on current data.

## 2) External API Contract (Upstream)

Base URL:
```

GET [https://sfdlive.com/api/data/](https://sfdlive.com/api/data/)

````

Observed query params and defaults:
- `draw` int, default 1
- `order` "new" or "old", default "new"
- `start` int offset, default 0
- `length` page size, default 100
- `search` free text, default "Any"
- `page` 1-based page, default 1
- `location` default "Any"
- `unit` default "Any"
- `type` default "Any"
- `area` default "Any"
- `date` string like "Today" or date literal, default "Today"
- `dateEnd` string, default "Today"
- `_` cache buster timestamp, optional

Response shape example provided by user. Notable fields:
- `data` as an array, but items are objects keyed by index strings with nested incident objects at `"0"`.
- Latitude may be nested as `{source: string, parsedValue: float}` or a float in other cases.
- Timestamps like `"2025-09-15 16:05:27"` in local time.

## 3) MCP Server Interfaces

Use the official Python MCP library. The server must register the following tools. Names are concise, inputs are explicit JSON, outputs validate against the defined schemas.

### 3.1 Tool: `sfd.fetch_raw`
Low level pass through proxy with normalization and pagination controls.

**Input schema**
```json
{
  "type": "object",
  "properties": {
    "order": { "type": "string", "enum": ["new", "old"], "default": "new" },
    "start": { "type": "integer", "minimum": 0, "default": 0 },
    "length": { "type": "integer", "minimum": 1, "maximum": 500, "default": 100 },
    "search": { "type": "string", "default": "Any" },
    "page": { "type": "integer", "minimum": 1, "default": 1 },
    "location": { "type": "string", "default": "Any" },
    "unit": { "type": "string", "default": "Any" },
    "type": { "type": "string", "default": "Any" },
    "area": { "type": "string", "default": "Any" },
    "date": { "type": "string", "default": "Today" },
    "dateEnd": { "type": "string", "default": "Today" },
    "cacheTtlSeconds": { "type": "integer", "minimum": 0, "default": 15 }
  },
  "required": []
}
````

**Output schema**

```json
{
  "type": "object",
  "properties": {
    "meta": {
      "type": "object",
      "properties": {
        "page": { "type": "integer" },
        "total_pages": { "type": "integer" },
        "results_per_page": { "type": "integer" },
        "total_incidents": { "type": "integer" },
        "offset": { "type": "integer" },
        "order": { "type": "string" },
        "users_online": { "type": "integer" }
      },
      "required": ["page","results_per_page","order"]
    },
    "incidents": {
      "type": "array",
      "items": { "$ref": "#/$defs/Incident" }
    },
    "source": {
      "type": "object",
      "properties": {
        "url": { "type": "string" },
        "fetched_at": { "type": "string", "format": "date-time" },
        "cache_hit": { "type": "boolean" }
      },
      "required": ["url","fetched_at","cache_hit"]
    }
  },
  "required": ["incidents","source"],
  "$defs": {
    "Incident": {
      "type": "object",
      "properties": {
        "id": { "type": "integer" },
        "incident_number": { "type": "string" },
        "type": { "type": "string" },
        "type_code": { "type": "string" },
        "description": { "type": "string" },
        "description_clean": { "type": "string", "nullable": true },
        "response_type": { "type": "string" },
        "response_mode": { "type": "string" },
        "datetime_local": { "type": "string", "format": "date-time" },
        "datetime_utc": { "type": "string", "format": "date-time" },
        "latitude": { "type": "number", "nullable": true },
        "longitude": { "type": "number", "nullable": true },
        "address": { "type": "string" },
        "area": { "type": "string" },
        "battalion": { "type": "string" },
        "units": {
          "type": "array",
          "items": { "type": "string" }
        },
        "primary_unit": { "type": "string", "nullable": true },
        "unit_status": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "properties": {
              "dispatched": { "type": "string", "nullable": true },
              "arrived": { "type": "string", "nullable": true },
              "transport": { "type": "string", "nullable": true },
              "in_service": { "type": "string", "nullable": true }
            }
          }
        },
        "active": { "type": "boolean" },
        "alarm": { "type": "integer" },
        "late": { "type": "boolean" }
      },
      "required": ["id","incident_number","type","datetime_local","address"]
    }
  }
}
```

**Normalization rules**

* Flatten the upstream `data` so `incidents` is a simple array of incidents.
* Parse `datetime` as America/Los\_Angeles. Also include `datetime_utc`.
* Normalize latitude and longitude to numbers when present.
* Split `units_dispatched` like `"E16*"` to `["E16"]`. Ignore trailing markers like `*` in the list, but keep exact original in an `raw.units_dispatched` if you include a debug block.
* Convert `active` and `late` to booleans.
* Preserve unknown fields under `raw` when easily available for debugging.

### 3.2 Tool: `sfd.latest_incident`

Returns the single latest incident by `datetime`.

**Input**

```json
{ "type": "object", "properties": {}, "additionalProperties": false }
```

**Output**

```json
{
  "type": "object",
  "properties": {
    "incident": { "$ref": "sfd.fetch_raw#/$defs/Incident" },
    "source": {
      "type": "object",
      "properties": {
        "fetched_at": { "type": "string", "format": "date-time" }
      },
      "required": ["fetched_at"]
    }
  },
  "required": ["incident","source"]
}
```

### 3.3 Tool: `sfd.is_fire_active`

Answers “is there a fire in seattle?” by checking if any open or very recent incidents are fire related.

Definition

* Fire related if `type` or `description_clean` or `type_code` contains any of:

  * "Fire", "Fire in Building", "Brush Fire", "Car Fire", "Marine Fire", `type_code` like "FIR", "WATER RESCUE" not counted as fire unless description includes fire.
* Active if `active=true` or if `datetime_utc` within the last 90 minutes and no `in_service` timestamp yet in all listed units.

**Input**

```json
{
  "type": "object",
  "properties": {
    "lookbackMinutes": { "type": "integer", "minimum": 15, "maximum": 360, "default": 120 }
  }
}
```

**Output**

```json
{
  "type": "object",
  "properties": {
    "is_fire_active": { "type": "boolean" },
    "matching_incidents": {
      "type": "array",
      "items": { "$ref": "sfd.fetch_raw#/$defs/Incident" }
    },
    "reasoning": { "type": "string" }
  },
  "required": ["is_fire_active","matching_incidents","reasoning"]
}
```

### 3.4 Tool: `sfd.has_evacuation_orders`

Answers “are there any evacuation orders?” by scanning for keywords.

Detection logic

* Check `description`, `description_clean`, and any free text status fields if present.
* Keyword list (case insensitive): "evacuation", "evacuate", "evacuation order", "evacuation advisory", "evacuations in progress".
* If not present in live feed, return false. Include guidance that official evacuation orders usually come from SFD, SPD, or AlertSeattle. This tool only reflects the live incident feed.

**Input**

```json
{
  "type": "object",
  "properties": {
    "lookbackMinutes": { "type": "integer", "minimum": 30, "maximum": 720, "default": 180 }
  }
}
```

**Output**

```json
{
  "type": "object",
  "properties": {
    "has_evacuation_orders": { "type": "boolean" },
    "supporting_incidents": {
      "type": "array",
      "items": { "$ref": "sfd.fetch_raw#/$defs/Incident" }
    },
    "notes": { "type": "string" }
  },
  "required": ["has_evacuation_orders","supporting_incidents","notes"]
}
```

## 4) Implementation Details

### 4.1 Tech stack

* Python 3.11+
* `mcp` Python library
* `httpx` for HTTP client with gzip and brotli
* `pydantic` for request and response schemas
* `uvloop` optional
* `pytz` or `zoneinfo` for tz conversion
* `fastjsonschema` or Pydantic v2 for speed

### 4.2 HTTP behavior

* GET with provided query params. Always include a `_` cache buster locally if not using cache.
* Headers: set `User-Agent` and `Accept: application/json`. Do not ship browser headers like Sec-Fetch in production.
* Timeout: connect 3s, read 7s.
* Retries: 2 with exponential backoff on 502/503/504 and network errors.
* Respect `length` cap of 500 to avoid accidental large pulls.

### 4.3 Caching

* In memory cache keyed by the full query string after sorting params.
* TTL default 15s, configurable per call.
* Include `cache_hit` in `source`.

### 4.4 Normalization and parsing

* Timezone: Assume upstream `datetime` is local Seattle time. Convert to aware `America/Los_Angeles` then to UTC for `datetime_utc`.
* Units parsing: split by non alphanumerics, strip trailing markers like `*`.
* Latitude and longitude: if object with `parsedValue`, use it. If string, parse float. If missing, set null.
* Boolean fields: `active` 1 => true, 0 => false. Same for `late`.

### 4.5 Error handling

* Map upstream non 2xx to MCP tool error with code `UPSTREAM_HTTP_ERROR` and include status code.
* On parse errors, return `SCHEMA_VALIDATION_ERROR` with first failing path.
* Timeouts return `UPSTREAM_TIMEOUT`.
* Always return a short `user_message` that the LLM can show directly.

### 4.6 Logging

* Structured logs to stdout: level, tool, url, params, ms, status, cache\_hit, error.
* Redact none of these since there is no auth.

### 4.7 Configuration

* Environment variables

  * `SFD_BASE_URL` default `https://sfdlive.com/api/data/`
  * `DEFAULT_CACHE_TTL` default 15
  * `HTTP_TIMEOUTS` optional
* CLI flags for local runs are optional.

## 5) Tool Behavior Examples

### 5.1 Latest incident

* LLM calls `sfd.latest_incident`.
* Server fetches `order=new&start=0&length=1&page=1&date=Today&dateEnd=Today`.
* Return a single normalized incident.

### 5.2 Is there a fire in seattle

* LLM calls `sfd.is_fire_active` with default lookback 120.
* Server fetches last 100 or 200 rows ordered new. You may do `length=200` to widen coverage inside a single call.
* Filter by rules. If any match is active per definition, return `true` with a short reasoning like “Found 2 fire incidents within 60 minutes with no in\_service timestamps.”

### 5.3 Any evacuation orders

* LLM calls `sfd.has_evacuation_orders` with default lookback 180.
* Server fetches, scans for keywords, returns false if none found and adds note: “Live incident feed does not list official evacuation orders. Check AlertSeattle for formal notices.”

## 6) LLM Usage Guidelines

Provide a short system hint for the local LLM:

* Prefer calling `sfd.latest_incident` when the user asks for “latest incident.”
* Prefer `sfd.is_fire_active` when the user asks about fires. Do not try to infer from titles only. Use returned fields.
* Prefer `sfd.has_evacuation_orders` for evacuation queries.
* Use `sfd.fetch_raw` if you need custom filters or want the full page of incidents.

Example tool call plan for natural language questions:

* “is there a fire in seattle?” -> call `sfd.is_fire_active`, if false say “No active fires detected in the last 2 hours in the live feed.”
* “what is the latest incident?” -> call `sfd.latest_incident` and summarize address, type, and time.
* “are there any evacuation orders?” -> call `sfd.has_evacuation_orders`, include brief guidance about official sources.

## 7) Testing Plan

Unit tests

* Parse and normalize the provided example JSON verbatim.
* Mixed latitude representations.
* Units parsing with and without stars.
* Timezone conversion correctness for PDT and PST.

Integration tests

* Live call against the real endpoint behind a feature flag.
* Cache hit and miss logic.
* Retry on transient 503.

Contract tests

* Validate all tool outputs against the Pydantic models.
* Ensure `sfd.latest_incident` selects max `datetime_utc`.

## 8) File Layout

```
mcp_sfd/
  server.py                 # MCP server entry point, tool registration
  http_client.py            # httpx client with retry and headers
  schemas.py                # Pydantic models
  normalize.py              # data shaping and parsing helpers
  tools/
    fetch_raw.py
    latest_incident.py
    is_fire_active.py
    has_evac_orders.py
  tests/
    data/example_payload.json
    test_normalize.py
    test_tools.py
  pyproject.toml
  README.md
```

## 9) Non Functional

* Performance: typical call under 500 ms when cache hit, under 2 s when fresh.
* Resilience: tolerate brief upstream failures with 2 retries.
* Observability: logs at info and error, easy to grep by tool name.

## 10) Open Questions and Assumptions

* Upstream `datetime` assumed in Seattle local time. If upstream provides timezone later, prefer that.
* Evacuation signals may not live in this feed. The tool reports only what it can infer from descriptions.
* If upstream switches array shape, parser should fail loudly with schema error rather than guess.

```
