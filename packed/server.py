"""Packed — MCP server for cross-referencing PAC contributions, lobbying, and dark money."""

import json
import os
from pathlib import Path
import asyncio
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .openfec_client import OpenFECClient
from .errors import ServiceTracker, api_call


def _load_env():
    """Load API keys from .env file in the project root."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


_load_env()

server = Server("packed")

_fec_key = os.environ.get("OPENFEC_API_KEY", "").strip()
fec_client = OpenFECClient(api_key=_fec_key) if _fec_key else None


def _not_configured(source: str, env_var: str) -> list[TextContent]:
    """Return a helpful message when an API key is missing."""
    return [TextContent(
        type="text",
        text=json.dumps({
            "error": f"{source} is not configured — API key missing",
            "fix": f"Set {env_var} in your .env file",
        }, indent=2),
    )]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # =====================================================================
        # OpenFEC tools
        # =====================================================================
        Tool(
            name="fec_search_candidates",
            description=(
                "Search FEC candidates by name. Returns candidate IDs, office "
                "sought, party, and election cycles."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Candidate name to search for"},
                    "office": {
                        "type": "string",
                        "enum": ["H", "S", "P"],
                        "description": "Filter by office: House, Senate, or President (optional)",
                    },
                    "cycle": {"type": "integer", "description": "Two-year election cycle, e.g. 2026 (optional)"},
                    "state": {"type": "string", "description": "Two-letter state code (optional)"},
                    "party": {"type": "string", "description": "Party abbreviation, e.g. 'DEM', 'REP' (optional)"},
                },
                "required": ["q"],
            },
        ),
        Tool(
            name="fec_get_candidate",
            description="Get a candidate's full record by FEC candidate ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "FEC candidate ID (from fec_search_candidates)"},
                },
                "required": ["candidate_id"],
            },
        ),
        Tool(
            name="fec_search_committees",
            description=(
                "Search FEC committees (PACs, party committees, candidate "
                "committees, leadership PACs) by name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Committee name to search for"},
                    "committee_type": {"type": "string", "description": "FEC committee type code (optional)"},
                    "designation": {
                        "type": "string",
                        "description": "A=authorized, J=joint fundraising, P=principal campaign, U=unauthorized, D=leadership PAC (optional)",
                    },
                    "cycle": {"type": "integer", "description": "Two-year election cycle, e.g. 2026 (optional)"},
                },
                "required": ["q"],
            },
        ),
        Tool(
            name="fec_get_committee",
            description="Get a committee's full record by FEC committee ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID (from fec_search_committees)"},
                },
                "required": ["committee_id"],
            },
        ),
        Tool(
            name="fec_search_contributions",
            description=(
                "Search itemized individual contributions (Schedule A). Scope "
                "with committee_id and/or contributor_name — this dataset is "
                "very large."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID (optional, but recommended)"},
                    "contributor_name": {"type": "string", "description": "Contributor name (optional, but recommended)"},
                    "two_year_transaction_period": {"type": "integer", "description": "Election cycle, e.g. 2026 (optional)"},
                    "min_amount": {"type": "number", "description": "Minimum contribution amount (optional)"},
                    "max_amount": {"type": "number", "description": "Maximum contribution amount (optional)"},
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    _fec_tools = {
        "fec_search_candidates", "fec_get_candidate",
        "fec_search_committees", "fec_get_committee",
        "fec_search_contributions",
    }

    if name in _fec_tools and fec_client is None:
        return _not_configured("OpenFEC", "OPENFEC_API_KEY")

    tracker = ServiceTracker()

    try:
        if name == "fec_search_candidates":
            result = await api_call(
                tracker, "OpenFEC", "/candidates/search/",
                lambda: fec_client.search_candidates(
                    q=arguments["q"],
                    office=arguments.get("office"),
                    cycle=arguments.get("cycle"),
                    state=arguments.get("state"),
                    party=arguments.get("party"),
                ),
            )

        elif name == "fec_get_candidate":
            result = await api_call(
                tracker, "OpenFEC", "/candidate/{id}/",
                lambda: fec_client.get_candidate(arguments["candidate_id"]),
            )

        elif name == "fec_search_committees":
            result = await api_call(
                tracker, "OpenFEC", "/committees/",
                lambda: fec_client.search_committees(
                    q=arguments["q"],
                    committee_type=arguments.get("committee_type"),
                    designation=arguments.get("designation"),
                    cycle=arguments.get("cycle"),
                ),
            )

        elif name == "fec_get_committee":
            result = await api_call(
                tracker, "OpenFEC", "/committee/{id}/",
                lambda: fec_client.get_committee(arguments["committee_id"]),
            )

        elif name == "fec_search_contributions":
            result = await api_call(
                tracker, "OpenFEC", "/schedules/schedule_a/",
                lambda: fec_client.search_contributions(
                    committee_id=arguments.get("committee_id"),
                    contributor_name=arguments.get("contributor_name"),
                    two_year_transaction_period=arguments.get("two_year_transaction_period"),
                    min_amount=arguments.get("min_amount"),
                    max_amount=arguments.get("max_amount"),
                ),
            )

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        if result is None:
            result = {"error": "request failed", "service_warnings": tracker.warnings}
        elif tracker.warnings:
            result["service_warnings"] = tracker.warnings

        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False),
        )]

    except httpx.HTTPStatusError as e:
        return [TextContent(
            type="text",
            text=f"API error: {e.response.status_code} — {e.response.text[:500]}",
        )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


def main():
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
