# Packed — Campaign Finance & Lobbying MCP Server

MCP server that cross-references PAC contributions, federal lobbying
activity, and 501(c)(4) dark-money spending. Full scope and phased
build order: see `TODO.md` and the design doc this repo was scaffolded
from (`~/src/mefos-lab/PACKED_PLAN.md` in the private planning repo).

## Structure

- `packed/` — MCP server, API clients
- `tests/` — mocked-HTTP tests, no live API calls

## Status

Early scaffold. OpenFEC (`packed/openfec_client.py`) is the only source
wired up so far — all 5 client methods verified against the live API
(2026-08-12). LDA and ProPublica Nonprofit Explorer are not yet built.

## Data Sources

| Source | Coverage | Auth | Status |
|--------|----------|------|--------|
| OpenFEC | Committees, candidates, itemized contributions (Schedule A), disbursements (Schedule B) | Free API key via api.data.gov | Verified live |
| LDA (Lobbying Disclosure Act) | Registrations (LD-1), quarterly activity (LD-2), lobbyist political contributions (LD-203) | Free account + key via lda.gov | Planned |
| ProPublica Nonprofit Explorer | 501(c)(4) Form 990 filings | None | Planned |

The LD-203 link (lobbyist political contributions) is the reason this
tool exists — it's the connective tissue between lobbying and campaign
finance that no single government database exposes on its own.

## MCP Setup

Add to `.mcp.json` in the project root (already present):

```json
{
  "mcpServers": {
    "packed": {
      "command": ".venv/bin/python",
      "args": ["-m", "packed.server"]
    }
  }
}
```

Requires a Python venv with dependencies installed:
```
python3 -m venv .venv
.venv/bin/pip install mcp httpx
```

## Configuration

Copy `.env.example` to `.env` and fill in:

```
OPENFEC_API_KEY=<your-key>   # Required — get from api.data.gov
```

## Error Handling

All external API calls MUST use `api_call()` from `packed/errors.py`.
Never use bare `try/except` around HTTP calls — the shared handler
provides consistent error tracking and surfaces warnings to users.

```python
from packed.errors import ServiceTracker, api_call

tracker = ServiceTracker()

# Pass a lambda so the call can be retried on transient errors
# (HTTP 429/500/502/503/504, timeouts, connection failures).
# Up to 3 total attempts (1 + 2 retries) with exponential backoff.
result = await api_call(tracker, "OpenFEC", "/candidates/search/",
                        lambda: fec_client.search_candidates(q=name))

# At the end, attach warnings to the response:
if tracker.warnings:
    result["service_warnings"] = tracker.warnings
```

**Important**: Always pass a `lambda` (not a bare coroutine) to
`api_call` so retries work. In loop bodies, capture loop variables
with default args: `lambda n=name: client.search(n)`.

### Rate limits

`api_call()` enforces per-service rate limits automatically via
`SERVICE_RATE_LIMITS` in `packed/errors.py`. When adding a new data
source, look up its documented rate limit and add an entry. Current
entries (OpenFEC, LDA, ProPublica NPE) are conservative estimates —
verify against live docs and tighten/loosen as confirmed.

## Identity and Privacy

This project uses pseudonymous identities. Before any action
that touches GitHub or other external services, consider whether
it will expose the user's real identity.

**Rules:**
- Never use the user's real name or personal email in commits,
  PRs, issues, documentation, or any public-facing content
- Do NOT create GitHub PRs, issues, or comments from a
  personally-authenticated `gh` session — these expose the
  authenticated GitHub account (username + avatar) and cannot be
  permanently deleted. PR creation and merges go through the
  `mefos-lab` account directly (web UI), not `gh`.
- Before any `gh` CLI command, consider: will this show the
  user's GitHub identity publicly?
- Strip metadata from images before committing (check for
  EXIF, XMP, GPS, author fields)
- Check all file contents for identifying paths, emails, or
  names before pushing
- This repo's detection patterns (once built) will name specific
  real people (lobbyists, candidates) more directly than sift's
  entity/ownership focus does — hold operational discipline to a
  higher bar here, not a lower one.

**Git identity for commits to this repo:**

```bash
git config user.name "mefos-lab"
git config user.email "mefos-lab@proton.me"
git config user.signingkey "~/.ssh/mefos-lab.pub"
```

Push via the `github-mefos` SSH alias, never the default remote
identity.

## Debugging API Errors

When an external API returns errors (500, 502, etc.), investigate
what we're sending before assuming the service is down.

1. **Examine the actual request** — log or print the parameters
   being sent. The problem is usually our query, not their server.
2. **Don't discard data to work around errors** — if results cause
   downstream problems, fix the handling, not the data.

## Versioning

Single source of truth: `packed/__init__.py` (`__version__`) and
`pyproject.toml` (kept in sync).

- **patch** (0.1.1): bug fixes, minor corrections
- **minor** (0.2.0): new features, new data sources
- **major** (1.0.0): breaking changes to tool schemas or output format

## Conventions

- All output uses professional, factual language
- FEC candidate/committee IDs and LDA registration/filing IDs are
  stable identifiers — prefer them over name matching once known
- Name matching across sources is fuzzy — verify identities through
  additional sources before treating two records as the same entity
