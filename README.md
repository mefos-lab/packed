# Packed

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)]()

An [MCP server](https://modelcontextprotocol.io/) for **cross-referencing PAC contributions, federal lobbying activity, and dark-money spending** — who is paying whom, to influence what, and who's on both sides of that transaction.

> [!NOTE]
> This is a research tool, not a compliance product. All data comes from public federal disclosures (FEC, Lobbying Disclosure Act filings, IRS Form 990s). Always verify findings against primary sources before drawing conclusions.

## What it does

Packed cross-references PAC/committee contributions, federal lobbying registrations and activity, and 501(c)(4) dark-money spending — connecting campaign finance to lobbying in a way no single government database does on its own. The key link is the LD-203 filing, where registered lobbyists disclose their own political contributions.

## Status

Four data sources are integrated and verified live: OpenFEC (candidates, committees, itemized contributions and disbursements, independent and coordinated expenditures, financial totals), LDA (registrants, lobbyists, clients, filings, lobbyist contributions), ProPublica Nonprofit Explorer (501(c)(4) dark-money filings), and congress-legislators (committee membership plus the FEC-ID cross-reference that links a member of Congress to their campaign finance record).

Five detection patterns are built and live-verified: corroborating LD-203 lobbyist contributions against FEC's independently-filed records, tracing a leadership PAC's money flow, and tracing a joint fundraising committee's money flow (who funds it — including donors giving far more than any single committee's limit — and which committees it splits proceeds to), aggregating a lobbying firm's political giving by the congressional committees its recipients sit on, and the same for a PAC's outbound giving — which reports money routed through intermediary committees as unattributed rather than following it. See `TODO.md`.

## Quick start

```bash
# Clone and install
git clone https://github.com/mefos-lab/packed.git
cd packed
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Add to `.mcp.json` in your project root (already present in this repo):

```json
{
  "mcpServers": {
    "packed": {
      "command": "/path/to/packed/.venv/bin/python",
      "args": ["-m", "packed.server"]
    }
  }
}
```

Copy `.env.example` to `.env` and fill in your API key:

```bash
cp .env.example .env
```

```
OPENFEC_API_KEY=<your-key>   # Required for fec_* tools — free at api.data.gov
LDA_API_KEY=<your-key>       # Required for lda_* tools — free account at lda.gov/api/register/
```

## Data sources

| Source | Coverage | Auth |
|--------|----------|------|
| OpenFEC | Committees, candidates, itemized contributions/disbursements/independent expenditures/coordinated party expenditures, financial totals, candidate-committee linkage | Free API key |
| LDA (Lobbying Disclosure Act) | Registrants, lobbyists, clients, filings (LD-1/LD-2), lobbyist political contributions (LD-203) | Free account + key |
| ProPublica Nonprofit Explorer | 501(c)(4) Form 990 filings (dark money) | None |
| congress-legislators | Congressional committee/subcommittee membership, legislator IDs (incl. FEC candidate IDs) | None |

## Error Handling

All external API calls MUST use `api_call()` from `packed/errors.py`. Never use bare `try/except` around HTTP calls — the shared handler provides consistent error tracking, retries, and per-service rate limiting. See `CLAUDE.md` for the full convention.

## License

MIT
