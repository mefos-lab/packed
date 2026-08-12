"""Packed — MCP server for cross-referencing PAC contributions, lobbying, and dark money."""

import json
import os
from dataclasses import asdict
from pathlib import Path
import asyncio
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .openfec_client import OpenFECClient
from .lda_client import LDAClient
from .propublica_client import ProPublicaNPEClient
from .errors import ServiceTracker, api_call
from . import patterns as patterns_module


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

_lda_key = os.environ.get("LDA_API_KEY", "").strip()
lda_client = LDAClient(api_key=_lda_key) if _lda_key else None

# No auth required
propublica_client = ProPublicaNPEClient()


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

        # =====================================================================
        # LDA (Lobbying Disclosure Act) tools
        # =====================================================================
        Tool(
            name="lda_search_filings",
            description=(
                "Search LD-1 lobbying registrations and LD-2 quarterly activity "
                "filings by registrant, client, or lobbyist name. At least one "
                "filter should be set."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "registrant_name": {"type": "string", "description": "Lobbying firm/individual name (optional)"},
                    "client_name": {"type": "string", "description": "Lobbying client name (optional)"},
                    "lobbyist_name": {"type": "string", "description": "Individual lobbyist name (optional)"},
                    "filing_year": {"type": "integer", "description": "Filing year, e.g. 2026 (optional)"},
                    "filing_type": {"type": "string", "description": "Filing type code, e.g. 'RR' (registration), 'Q1'-'Q4' (quarterly) (optional)"},
                    "filing_period": {"type": "string", "description": "Filing period code (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="lda_get_filing",
            description="Get a single LDA filing's full record by its UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filing_uuid": {"type": "string", "description": "Filing UUID (from lda_search_filings)"},
                },
                "required": ["filing_uuid"],
            },
        ),
        Tool(
            name="lda_search_contributions",
            description=(
                "Search LD-203 contribution reports — lobbyist political "
                "contributions. This is the link between lobbying activity "
                "and campaign finance. At least one filter should be set."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "registrant_name": {"type": "string", "description": "Lobbying firm/individual name (optional)"},
                    "lobbyist_name": {"type": "string", "description": "Individual lobbyist name (optional)"},
                    "contribution_contributor": {"type": "string", "description": "Name of the contributor (optional)"},
                    "filing_year": {"type": "integer", "description": "Filing year, e.g. 2026 (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="lda_search_registrants",
            description="Search LDA registrants (lobbying firms/individuals) by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "registrant_name": {"type": "string", "description": "Registrant name to search for"},
                },
                "required": ["registrant_name"],
            },
        ),
        Tool(
            name="lda_get_registrant",
            description="Get a single LDA registrant's full record by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "registrant_id": {"type": "integer", "description": "Registrant ID (from lda_search_registrants)"},
                },
                "required": ["registrant_id"],
            },
        ),
        Tool(
            name="lda_search_clients",
            description="Search LDA lobbying clients by name, optionally scoped to a registrant.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_name": {"type": "string", "description": "Client name to search for (optional)"},
                    "registrant_id": {"type": "integer", "description": "Scope to a specific registrant ID (optional)"},
                },
                "required": [],
            },
        ),

        # =====================================================================
        # ProPublica Nonprofit Explorer tools
        # =====================================================================
        Tool(
            name="propublica_search",
            description=(
                "Search Form 990 filings for tax-exempt organizations. Pass "
                "c_code=4 to scope to 501(c)(4) social welfare organizations "
                "— the dark-money category that doesn't have to disclose "
                "donors but does have to file spending."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Keyword search — org name, alternate name, or city (optional)"},
                    "page": {"type": "integer", "description": "Zero-indexed page number (optional, default 0)"},
                    "state": {"type": "string", "description": "Two-letter US state/territory code (optional)"},
                    "ntee": {"type": "integer", "description": "NTEE major group, 1-10 (optional)"},
                    "c_code": {"type": "integer", "description": "501(c) subsection, e.g. 4 for 501(c)(4) (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="propublica_get_organization",
            description="Get full profile and Form 990 filing history for an organization by EIN.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ein": {"type": "string", "description": "Employer Identification Number, with or without dashes (from propublica_search)"},
                },
                "required": ["ein"],
            },
        ),

        # =====================================================================
        # Detection patterns
        # =====================================================================
        Tool(
            name="pattern_lobbyist_contribution_corroboration",
            description=(
                "Cross-reference a lobbyist or registrant's LD-203 political "
                "contributions against FEC Schedule A itemized receipts. "
                "Corroboration across both independently-filed sources is a "
                "credibility signal — an unconfirmed contribution isn't "
                "necessarily suspicious (it may fall under FEC's itemization "
                "threshold), but the pattern surfaces which contributions "
                "can and can't be independently verified."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lobbyist_name": {"type": "string", "description": "Individual lobbyist name (optional)"},
                    "registrant_name": {"type": "string", "description": "Registrant/firm name (optional)"},
                    "filing_year": {"type": "integer", "description": "LD-203 filing year, e.g. 2025 (optional)"},
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
    _lda_tools = {
        "lda_search_filings", "lda_get_filing", "lda_search_contributions",
        "lda_search_registrants", "lda_get_registrant", "lda_search_clients",
    }

    if name in _fec_tools and fec_client is None:
        return _not_configured("OpenFEC", "OPENFEC_API_KEY")
    if name in _lda_tools and lda_client is None:
        return _not_configured("LDA", "LDA_API_KEY")
    if name == "pattern_lobbyist_contribution_corroboration":
        if fec_client is None:
            return _not_configured("OpenFEC", "OPENFEC_API_KEY")
        if lda_client is None:
            return _not_configured("LDA", "LDA_API_KEY")

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

        elif name == "lda_search_filings":
            result = await api_call(
                tracker, "LDA", "/filings/",
                lambda: lda_client.search_filings(
                    registrant_name=arguments.get("registrant_name"),
                    client_name=arguments.get("client_name"),
                    lobbyist_name=arguments.get("lobbyist_name"),
                    filing_year=arguments.get("filing_year"),
                    filing_type=arguments.get("filing_type"),
                    filing_period=arguments.get("filing_period"),
                ),
            )

        elif name == "lda_get_filing":
            result = await api_call(
                tracker, "LDA", "/filings/{uuid}/",
                lambda: lda_client.get_filing(arguments["filing_uuid"]),
            )

        elif name == "lda_search_contributions":
            result = await api_call(
                tracker, "LDA", "/contributions/",
                lambda: lda_client.search_contributions(
                    registrant_name=arguments.get("registrant_name"),
                    lobbyist_name=arguments.get("lobbyist_name"),
                    contribution_contributor=arguments.get("contribution_contributor"),
                    filing_year=arguments.get("filing_year"),
                ),
            )

        elif name == "lda_search_registrants":
            result = await api_call(
                tracker, "LDA", "/registrants/",
                lambda: lda_client.search_registrants(
                    registrant_name=arguments["registrant_name"],
                ),
            )

        elif name == "lda_get_registrant":
            result = await api_call(
                tracker, "LDA", "/registrants/{id}/",
                lambda: lda_client.get_registrant(arguments["registrant_id"]),
            )

        elif name == "lda_search_clients":
            result = await api_call(
                tracker, "LDA", "/clients/",
                lambda: lda_client.search_clients(
                    client_name=arguments.get("client_name"),
                    registrant_id=arguments.get("registrant_id"),
                ),
            )

        elif name == "propublica_search":
            result = await api_call(
                tracker, "ProPublica NPE", "/search.json",
                lambda: propublica_client.search(
                    q=arguments.get("q"),
                    page=arguments.get("page", 0),
                    state=arguments.get("state"),
                    ntee=arguments.get("ntee"),
                    c_code=arguments.get("c_code"),
                ),
            )

        elif name == "propublica_get_organization":
            result = await api_call(
                tracker, "ProPublica NPE", "/organizations/{ein}.json",
                lambda: propublica_client.get_organization(arguments["ein"]),
            )

        elif name == "pattern_lobbyist_contribution_corroboration":
            match = await patterns_module.detect_lobbyist_contribution_corroboration(
                lda_client, fec_client,
                lobbyist_name=arguments.get("lobbyist_name"),
                registrant_name=arguments.get("registrant_name"),
                filing_year=arguments.get("filing_year"),
            )
            result = asdict(match)

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
