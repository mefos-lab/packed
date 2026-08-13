"""Packed — MCP server for cross-referencing PAC contributions, lobbying, and dark money."""

import json
import os
from dataclasses import asdict
from pathlib import Path
import asyncio
from dataclasses import dataclass
import httpx
from mcp.server import MCPServer
from mcp_types import TextContent

from .mcp_compat import register_tools


@dataclass
class Tool:
    """This server's own tool definition.

    Deliberately local rather than the SDK's type: these definitions are
    the source of truth for what is advertised, and keeping them free of
    the SDK means an API change like the 1.x -> 2.x one touches the
    registration shim (packed/mcp_compat.py) instead of all 32 tools.
    """

    name: str
    description: str
    inputSchema: dict

from .openfec_client import OpenFECClient
from .lda_client import LDAClient
from .propublica_client import ProPublicaNPEClient
from .congress_legislators_client import CongressLegislatorsClient
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

server = MCPServer(name="packed")

_fec_key = os.environ.get("OPENFEC_API_KEY", "").strip()
fec_client = OpenFECClient(api_key=_fec_key) if _fec_key else None

_lda_key = os.environ.get("LDA_API_KEY", "").strip()
lda_client = LDAClient(api_key=_lda_key) if _lda_key else None

# No auth required
propublica_client = ProPublicaNPEClient()
congress_client = CongressLegislatorsClient()


def _not_configured(source: str, env_var: str) -> list[TextContent]:
    """Return a helpful message when an API key is missing."""
    return [TextContent(
        type="text",
        text=json.dumps({
            "error": f"{source} is not configured — API key missing",
            "fix": f"Set {env_var} in your .env file",
        }, indent=2),
    )]


async def list_tools() -> list[Tool]:
    """The advertised tool set — source of truth for every schema."""
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
        Tool(
            name="fec_search_disbursements",
            description=(
                "Search itemized disbursements — where committee money goes "
                "out (Schedule B). Set recipient_committee_id to trace "
                "payments to another committee (leadership PAC / joint "
                "fundraising committee transfers). Scope with committee_id, "
                "recipient_name, and/or recipient_committee_id — this "
                "dataset is very large."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID of the spending committee (optional, but recommended)"},
                    "recipient_name": {"type": "string", "description": "Recipient name (optional)"},
                    "recipient_committee_id": {"type": "string", "description": "FEC committee ID of the receiving committee — use to trace transfers (optional)"},
                    "two_year_transaction_period": {"type": "integer", "description": "Election cycle, e.g. 2026 (optional)"},
                    "min_amount": {"type": "number", "description": "Minimum disbursement amount (optional)"},
                    "max_amount": {"type": "number", "description": "Maximum disbursement amount (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="fec_search_independent_expenditures",
            description=(
                "Search independent expenditures (Schedule E) — spending "
                "by a committee not coordinated with a candidate, "
                "expressly advocating for or against them. Scope with "
                "candidate_id and/or committee_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "FEC candidate ID (optional, but recommended)"},
                    "committee_id": {"type": "string", "description": "FEC committee ID of the spending committee (optional, but recommended)"},
                    "support_oppose_indicator": {"type": "string", "enum": ["S", "O"], "description": "S=supporting, O=opposing (optional)"},
                    "two_year_transaction_period": {"type": "integer", "description": "Election cycle, e.g. 2026 (optional)"},
                    "min_amount": {"type": "number", "description": "Minimum expenditure amount (optional)"},
                    "max_amount": {"type": "number", "description": "Maximum expenditure amount (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="fec_search_coordinated_expenditures",
            description=(
                "Search coordinated party expenditures (Schedule F) — "
                "spending by a party committee made on behalf of a "
                "candidate, a distinct disclosure category from "
                "independent expenditures. Scope with committee_id "
                "and/or candidate_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID of the party committee (optional, but recommended)"},
                    "candidate_id": {"type": "string", "description": "FEC candidate ID (optional, but recommended)"},
                    "two_year_transaction_period": {"type": "integer", "description": "Election cycle, e.g. 2026 (optional)"},
                    "min_amount": {"type": "number", "description": "Minimum expenditure amount (optional)"},
                    "max_amount": {"type": "number", "description": "Maximum expenditure amount (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="fec_get_committee_totals",
            description="Get a committee's aggregated financial totals (receipts, disbursements, cash on hand) per reporting period, without pulling itemized data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID"},
                    "cycle": {"type": "integer", "description": "Two-year election cycle, e.g. 2026 (optional)"},
                },
                "required": ["committee_id"],
            },
        ),
        Tool(
            name="fec_get_candidate_totals",
            description="Get a candidate's aggregated financial totals (receipts, disbursements, cash on hand) per election, without pulling itemized data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "FEC candidate ID"},
                    "cycle": {"type": "integer", "description": "Two-year election cycle, e.g. 2026 (optional)"},
                },
                "required": ["candidate_id"],
            },
        ),
        Tool(
            name="fec_get_candidate_committees",
            description="Get the committees associated with a candidate — resolves candidate-to-committee linkage directly instead of inferring it from search results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "FEC candidate ID"},
                    "cycle": {"type": "integer", "description": "Two-year election cycle, e.g. 2026 (optional)"},
                },
                "required": ["candidate_id"],
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
        Tool(
            name="lda_get_client",
            description="Get a single LDA lobbying client's full record by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer", "description": "Client ID (from lda_search_clients)"},
                },
                "required": ["client_id"],
            },
        ),
        Tool(
            name="lda_search_lobbyists",
            description=(
                "Search individual lobbyists by name, optionally scoped "
                "to a registrant. Lobbyists are a distinct entity from "
                "registrants — a registrant (firm) employs many lobbyists."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lobbyist_name": {"type": "string", "description": "Lobbyist name to search for (optional)"},
                    "registrant_id": {"type": "integer", "description": "Scope to a specific registrant ID (optional)"},
                    "registrant_name": {"type": "string", "description": "Scope to a registrant by name (optional)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="lda_get_lobbyist",
            description="Get a single lobbyist's full record by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lobbyist_id": {"type": "integer", "description": "Lobbyist ID (from lda_search_lobbyists)"},
                },
                "required": ["lobbyist_id"],
            },
        ),
        Tool(
            name="lda_get_contribution",
            description="Get a single LD-203 contribution report by its filing UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filing_uuid": {"type": "string", "description": "Contribution report filing UUID (from lda_search_contributions)"},
                },
                "required": ["filing_uuid"],
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
        # congress-legislators tools (committee assignments, legislator IDs)
        # =====================================================================
        Tool(
            name="congress_find_legislator_by_fec_id",
            description=(
                "Resolve an FEC candidate ID to a sitting member of "
                "Congress. This is the join between FEC money data and "
                "committee assignments — use it to go from a candidate "
                "committee to the member's committee seats. Returns null "
                "if no current member holds that FEC ID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fec_id": {"type": "string", "description": "FEC candidate ID, e.g. S0AR00150"},
                },
                "required": ["fec_id"],
            },
        ),
        Tool(
            name="congress_search_legislators",
            description="Search sitting members of Congress by name. Returns their bioguide ID, FEC candidate IDs, and other cross-reference identifiers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Full or partial legislator name"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="congress_get_legislator_committees",
            description=(
                "Get all committees and subcommittees a member of "
                "Congress sits on, including their rank and any "
                "leadership title (Chairman / Ranking Member). "
                "Note: current assignments only — no historical data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "bioguide": {"type": "string", "description": "Bioguide ID (from congress_search_legislators or congress_find_legislator_by_fec_id)"},
                },
                "required": ["bioguide"],
            },
        ),
        Tool(
            name="congress_get_committee_members",
            description=(
                "Get the full roster of a congressional committee or "
                "subcommittee, with each member's FEC candidate IDs "
                "attached so the roster can be joined directly to FEC "
                "money data. Note: current membership only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "Committee ID, e.g. SSAF (Senate Agriculture) or SSAF13 (a subcommittee)"},
                },
                "required": ["committee_id"],
            },
        ),
        Tool(
            name="congress_search_committees",
            description="Search congressional committees and subcommittees by name. Returns committee IDs for use with congress_get_committee_members.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Full or partial committee name, e.g. 'agriculture'"},
                },
                "required": ["query"],
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
        Tool(
            name="pattern_leadership_pac_transfers",
            description=(
                "Trace a leadership PAC's money flow: top contributors "
                "funding it (Schedule A), and which committees it "
                "transfers money to (Schedule B disbursements that went "
                "to another registered committee, not vendor spending). "
                "A transfer to a candidate isn't inherently improper — "
                "leadership PACs exist for exactly this — but this "
                "surfaces who funds the PAC and who it funds in turn."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID of the leadership PAC (optional if committee_name given)"},
                    "committee_name": {"type": "string", "description": "Leadership PAC name to resolve to a committee ID (optional if committee_id given)"},
                    "two_year_transaction_period": {"type": "integer", "description": "Election cycle, e.g. 2026 (optional)"},
                    "min_transfer_amount": {"type": "number", "description": "Only include transfers at or above this amount (optional, default 0)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="pattern_jfc_obscuring",
            description=(
                "Trace a joint fundraising committee's money flow: top "
                "contributors funding it (Schedule A), and which "
                "participant committees it splits proceeds to (Schedule "
                "B disbursements that went to another registered "
                "committee). A JFC lets a donor write one large check "
                "that gets divided across multiple committees, each "
                "within its own legal limit — this surfaces the flow so "
                "the real per-candidate scale of support is visible."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "committee_id": {"type": "string", "description": "FEC committee ID of the joint fundraising committee (optional if committee_name given)"},
                    "committee_name": {"type": "string", "description": "JFC name to resolve to a committee ID (optional if committee_id given)"},
                    "two_year_transaction_period": {"type": "integer", "description": "Election cycle, e.g. 2026 (optional)"},
                    "min_transfer_amount": {"type": "number", "description": "Only include transfers at or above this amount (optional, default 0)"},
                },
                "required": [],
            },
        ),
        Tool(
            name="pattern_lobbying_money_to_committee_seats",
            description=(
                "Aggregate a lobbying registrant's LD-203 political "
                "giving by the congressional committees its recipients "
                "sit on. Answers 'whose committee seats does this firm's "
                "money land on'. Note: LDA does not record which "
                "committee a client lobbies before (only chamber), so "
                "this deliberately does not claim a lobbying-target "
                "match — see the module docstring. Committee totals sum "
                "to more than the contribution total because a "
                "recipient sits on multiple committees."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "registrant_name": {"type": "string", "description": "Lobbying firm/registrant name, e.g. 'Akin Gump'"},
                    "filing_year": {"type": "integer", "description": "LD-203 filing year, e.g. 2025 (optional)"},
                    "include_subcommittees": {"type": "boolean", "description": "Include subcommittee seats as well as full committees (optional, default false)"},
                },
                "required": ["registrant_name"],
            },
        ),
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    _fec_tools = {
        "fec_search_candidates", "fec_get_candidate",
        "fec_search_committees", "fec_get_committee",
        "fec_search_contributions", "fec_search_disbursements",
        "fec_search_independent_expenditures", "fec_search_coordinated_expenditures",
        "fec_get_committee_totals", "fec_get_candidate_totals",
        "fec_get_candidate_committees",
    }
    _lda_tools = {
        "lda_search_filings", "lda_get_filing", "lda_search_contributions",
        "lda_search_registrants", "lda_get_registrant", "lda_search_clients",
        "lda_get_client", "lda_search_lobbyists", "lda_get_lobbyist",
        "lda_get_contribution",
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
    if name == "pattern_leadership_pac_transfers" and fec_client is None:
        return _not_configured("OpenFEC", "OPENFEC_API_KEY")
    if name == "pattern_jfc_obscuring" and fec_client is None:
        return _not_configured("OpenFEC", "OPENFEC_API_KEY")
    if name == "pattern_lobbying_money_to_committee_seats" and lda_client is None:
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

        elif name == "fec_search_disbursements":
            result = await api_call(
                tracker, "OpenFEC", "/schedules/schedule_b/",
                lambda: fec_client.search_disbursements(
                    committee_id=arguments.get("committee_id"),
                    recipient_name=arguments.get("recipient_name"),
                    recipient_committee_id=arguments.get("recipient_committee_id"),
                    two_year_transaction_period=arguments.get("two_year_transaction_period"),
                    min_amount=arguments.get("min_amount"),
                    max_amount=arguments.get("max_amount"),
                ),
            )

        elif name == "fec_search_independent_expenditures":
            result = await api_call(
                tracker, "OpenFEC", "/schedules/schedule_e/",
                lambda: fec_client.search_independent_expenditures(
                    candidate_id=arguments.get("candidate_id"),
                    committee_id=arguments.get("committee_id"),
                    support_oppose_indicator=arguments.get("support_oppose_indicator"),
                    two_year_transaction_period=arguments.get("two_year_transaction_period"),
                    min_amount=arguments.get("min_amount"),
                    max_amount=arguments.get("max_amount"),
                ),
            )

        elif name == "fec_search_coordinated_expenditures":
            result = await api_call(
                tracker, "OpenFEC", "/schedules/schedule_f/",
                lambda: fec_client.search_coordinated_expenditures(
                    committee_id=arguments.get("committee_id"),
                    candidate_id=arguments.get("candidate_id"),
                    two_year_transaction_period=arguments.get("two_year_transaction_period"),
                    min_amount=arguments.get("min_amount"),
                    max_amount=arguments.get("max_amount"),
                ),
            )

        elif name == "fec_get_committee_totals":
            result = await api_call(
                tracker, "OpenFEC", "/committee/{id}/totals/",
                lambda: fec_client.get_committee_totals(
                    arguments["committee_id"], cycle=arguments.get("cycle"),
                ),
            )

        elif name == "fec_get_candidate_totals":
            result = await api_call(
                tracker, "OpenFEC", "/candidate/{id}/totals/",
                lambda: fec_client.get_candidate_totals(
                    arguments["candidate_id"], cycle=arguments.get("cycle"),
                ),
            )

        elif name == "fec_get_candidate_committees":
            result = await api_call(
                tracker, "OpenFEC", "/candidate/{id}/committees/",
                lambda: fec_client.get_candidate_committees(
                    arguments["candidate_id"], cycle=arguments.get("cycle"),
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

        elif name == "lda_get_client":
            result = await api_call(
                tracker, "LDA", "/clients/{id}/",
                lambda: lda_client.get_client(arguments["client_id"]),
            )

        elif name == "lda_search_lobbyists":
            result = await api_call(
                tracker, "LDA", "/lobbyists/",
                lambda: lda_client.search_lobbyists(
                    lobbyist_name=arguments.get("lobbyist_name"),
                    registrant_id=arguments.get("registrant_id"),
                    registrant_name=arguments.get("registrant_name"),
                ),
            )

        elif name == "lda_get_lobbyist":
            result = await api_call(
                tracker, "LDA", "/lobbyists/{id}/",
                lambda: lda_client.get_lobbyist(arguments["lobbyist_id"]),
            )

        elif name == "lda_get_contribution":
            result = await api_call(
                tracker, "LDA", "/contributions/{filing_uuid}/",
                lambda: lda_client.get_contribution(arguments["filing_uuid"]),
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

        elif name == "congress_find_legislator_by_fec_id":
            legislator = await api_call(
                tracker, "congress-legislators", "/legislators-current.yaml",
                lambda: congress_client.find_legislator_by_fec_id(arguments["fec_id"]),
            )
            result = {
                "fec_id": arguments["fec_id"],
                "legislator": legislator,
                "found": legislator is not None,
            }

        elif name == "congress_search_legislators":
            legislators = await api_call(
                tracker, "congress-legislators", "/legislators-current.yaml",
                lambda: congress_client.search_legislators_by_name(arguments["name"]),
            )
            result = {"count": len(legislators or []), "results": legislators or []}

        elif name == "congress_get_legislator_committees":
            committees = await api_call(
                tracker, "congress-legislators", "/committee-membership-current.yaml",
                lambda: congress_client.get_committees_for_legislator(arguments["bioguide"]),
            )
            result = {
                "bioguide": arguments["bioguide"],
                "count": len(committees or []),
                "committees": committees or [],
                "note": "Current committee assignments only — this source has no historical snapshots.",
            }

        elif name == "congress_get_committee_members":
            roster = await api_call(
                tracker, "congress-legislators", "/committee-membership-current.yaml",
                lambda: congress_client.get_committee_members(arguments["committee_id"]),
            )
            result = roster or {}
            if isinstance(result, dict):
                result["note"] = "Current membership only — this source has no historical snapshots."

        elif name == "congress_search_committees":
            committees = await api_call(
                tracker, "congress-legislators", "/committees-current.yaml",
                lambda: congress_client.search_committees(arguments["query"]),
            )
            result = {"count": len(committees or []), "results": committees or []}

        elif name == "pattern_lobbyist_contribution_corroboration":
            match = await patterns_module.detect_lobbyist_contribution_corroboration(
                lda_client, fec_client,
                lobbyist_name=arguments.get("lobbyist_name"),
                registrant_name=arguments.get("registrant_name"),
                filing_year=arguments.get("filing_year"),
            )
            result = asdict(match)

        elif name == "pattern_leadership_pac_transfers":
            match = await patterns_module.detect_leadership_pac_transfers(
                fec_client,
                committee_id=arguments.get("committee_id"),
                committee_name=arguments.get("committee_name"),
                two_year_transaction_period=arguments.get("two_year_transaction_period"),
                min_transfer_amount=arguments.get("min_transfer_amount", 0.0),
            )
            result = asdict(match)

        elif name == "pattern_jfc_obscuring":
            match = await patterns_module.detect_jfc_obscuring(
                fec_client,
                committee_id=arguments.get("committee_id"),
                committee_name=arguments.get("committee_name"),
                two_year_transaction_period=arguments.get("two_year_transaction_period"),
                min_transfer_amount=arguments.get("min_transfer_amount", 0.0),
            )
            result = asdict(match)

        elif name == "pattern_lobbying_money_to_committee_seats":
            match = await patterns_module.detect_lobbying_money_to_committee_seats(
                lda_client, congress_client,
                registrant_name=arguments["registrant_name"],
                filing_year=arguments.get("filing_year"),
                include_subcommittees=arguments.get("include_subcommittees", False),
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


async def _register() -> None:
    """Register the tool set on the 2.x server, schemas preserved verbatim."""
    register_tools(server, await list_tools(), call_tool)


def main():
    async def run():
        await _register()
        await server.run_stdio_async()

    asyncio.run(run())


if __name__ == "__main__":
    main()
