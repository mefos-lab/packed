# Packed — Campaign Finance & Lobbying MCP Server

MCP server that cross-references PAC contributions, federal lobbying
activity, and 501(c)(4) dark-money spending. Full scope and phased
build order: see `TODO.md` and the design doc this repo was scaffolded
from (`~/src/mefos-lab/PACKED_PLAN.md` in the private planning repo).

## Structure

- `packed/` — MCP server, API clients
- `tests/` — mocked-HTTP tests, no live API calls

## Status

Four data sources wired up and verified live (2026-08-12): OpenFEC
(`packed/openfec_client.py`), LDA (`packed/lda_client.py`), ProPublica
Nonprofit Explorer (`packed/propublica_client.py`), and
congress-legislators (`packed/congress_legislators_client.py`). Five
detection patterns built and live-verified in `packed/patterns.py`.
Two pairs share extracted helpers: leadership PAC transfers and JFC
obscuring share `_trace_committee_money_flow()`; lobbying money by
committee seat and industry concentration share `_CommitteeSeatTally`.
Each helper was extracted when a second consumer appeared, not
speculatively.

congress-legislators is the odd one out architecturally: it's static
YAML files fetched whole from raw GitHub, not a query API, so the
client caches each file in-process after first fetch. Its value is the
**FEC candidate ID ↔ bioguide ID join** that links committee
assignments to FEC money data without fuzzy name matching. That
unblocked the dual-role and industry-concentration patterns, which are
next up — see `TODO.md` phase 8.

## Data Sources

| Source | Coverage | Auth | Status |
|--------|----------|------|--------|
| OpenFEC | Committees, candidates, itemized contributions (A), disbursements (B), independent expenditures (E), coordinated party expenditures (F), committee/candidate totals, candidate-committee linkage | Free API key via api.data.gov | Verified live |
| LDA (Lobbying Disclosure Act) | Registrants, lobbyists, clients, filings (LD-1/LD-2), lobbyist political contributions (LD-203) | Free account + key via lda.gov | Verified live |
| ProPublica Nonprofit Explorer | 501(c)(4) Form 990 filings (dark money) | None | Verified live |
| congress-legislators | Congressional committee/subcommittee membership, legislator cross-reference IDs (incl. FEC candidate IDs) | None — static YAML files on GitHub | Verified live |

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
source, look up its documented rate limit and add an entry. LDA's
120/min limit is confirmed from its live OpenAPI schema; OpenFEC and
ProPublica NPE entries are conservative estimates pending confirmation.

## Pattern provenance

`patterns/SOURCES.yaml` is a keyed registry of works; `patterns/PATTERNS.yaml`
records what each says about each pattern. Loaded by `packed/provenance.py`,
exposed as the `pattern_provenance` tool, and attached to every result.

**Citations carry a stance** — `supports`, `limits`, `contradicts` — because a
work can do opposite things to two patterns. Hall & Wayman is evidence for
aggregating money by committee seat and evidence against a votes-based timing
pattern. A flat source list would let either citation read as endorsement.

One work can also take *both* stances on *one* pattern, and this is not a
contradiction to tidy up. FEC enforcement files show foreign-national
contributions are real and prosecuted (supports) and that an address test looks
the wrong way for them, since the prosecuted schemes use domestic straw donors
(contradicts). Evidence that a scheme exists is not evidence that a given test
finds it — keep the two claims as separate citations.

**Enforcement sources** (`kind: enforcement`) ground a pattern differently from
a study: the question is not what a scheme correlates with but whether a
regulator has pursued it. They carry an `access` field saying how to pull the
case files, because a typology whose cases cannot be retrieved is an assertion
about cases rather than a source. FEC MURs are the one here, reachable on the
OpenFEC key packed already holds.

**Status is derived, not asserted.** A pattern is PROPOSED when uncited,
SUPPORTED when a work supports it, CONTESTED when one contradicts it. A test
enforces that status matches the citations, so the two cannot drift.

When adding a pattern, add a registry entry — even an empty one. An uncited
pattern reporting PROPOSED is honest; a pattern with no entry at all reads as
"not checked", which is different and worse.

When adding a source, append to SOURCES.yaml and cite it. Never inline a
citation in a pattern; the registry is the single place a work is described, so
a revised edition is updated once. Run `provenance.validate()` — a citation
pointing at a renamed source fails silently otherwise.

## Skill

`/follow` (`.claude/skills/follow/SKILL.md`) is the orchestration layer.

It exists because no single pattern answers the question a user asks. A
PAC's direct giving is only part of its exposure — much of the money
goes to intermediary committees (party committees, victory funds,
leadership PACs) that pass it on. On a real corporate PAC, direct
attribution to sitting members covered a minority of committee-directed
money. Running one pattern gives a confidently incomplete answer;
composing them and reconciling is the job the skill automates.

Its routing keys on the FEC `designation` code, which is verified
against live data: `D` -> leadership PAC pattern, `J` -> joint
fundraising pattern, party committees -> reported as not attributable
(the committee allocates later by a process this data does not capture).

**This is deliberately not an N-deep money graph, unlike sift's
traversal.** Ownership is transitive, so sift can walk a chain and have
each hop still mean something. Money is not: an intermediary committee
commingles a donor's funds with everyone else's, so no portion of what
it later disburses is traceable to any particular donor. Amounts
therefore stop at the first hop; routes may extend further, reported as
connectivity with no figure attached. Any future traversal work here
must preserve that distinction — a graph that propagates dollar amounts
through commingled accounts would produce confident fiction.

When adding a pattern, add it to the skill's Step 2 as well, or it will
not be reached by the workflow anyone actually runs.

## Name matching

Delegated to `onoma` (mefos-lab/onoma), which consolidates the matching
that had been reimplemented separately in `congress_legislators_client`,
`patterns.py`, and twice in sift.

Two things it changed here beyond deduplication. It handles nicknames,
which a prefix rule structurally cannot reach — "Bob" is not derivable
from "Robert". And it classifies person vs. organisation, which matters
because the LD-203 honoree field holds party committees, caucus PACs and
placeholders alongside legislators; counting those as unresolved people
measures the wrong denominator.

**Prefer identifier joins where the data offers them.** Pattern 5 goes
FEC recipient committee -> candidate ID -> legislator, with no name
matching anywhere, and has no fuzzy tail as a result. Pattern 1 has to
match LD-203 honoree names because no identifier is published for them.
That asymmetry is a property of the sources, not a gap to close.

## Detection Patterns

No generic condition/rule engine like Sift's `pattern_matcher.py` —
Sift's engine evaluates declarative YAML conditions against a unified
cross-source traversal graph, and packed has no equivalent graph layer
(each MCP tool call returns flat records from one source, not a joined
entity graph). Building a generic engine before there's a real graph
to evaluate against would be premature abstraction. Instead, each
pattern in `packed/patterns.py` is a bespoke async function that
queries the relevant clients directly and applies domain-specific
matching logic. Revisit the generic-engine question once several
patterns exist and their shared structure is actually clear.

**The MCP server runs on mcp 2.x via a shim.** mcp 2.0 removed the
`@server.list_tools()` / `@server.call_tool()` decorator API this server
was built on, and replaced it with a tool manager that derives each
tool's schema from a Python function signature. Rather than rewrite all
32 tools as typed functions — which would silently lose the enums,
per-field descriptions and required/optional distinctions the
hand-authored schemas carry — `packed/mcp_compat.py` keeps those schemas
verbatim and adapts them to the 2.0 manager.

Tool definitions live in `server.py`'s `list_tools()` using a **local**
`Tool` dataclass, deliberately not the SDK's type: they're the source of
truth for what's advertised, so keeping them SDK-free means the next API
break touches the shim, not all 32 definitions.

The shim writes a private attribute of the SDK's tool manager, because
2.0 has no public way to register a pre-built schema. That seam is
guarded by `tests/test_server.py::test_registered_schemas_match_definitions`,
which asserts every advertised schema is byte-identical to its
definition — so an SDK change fails loudly instead of quietly degrading
what the model sees.

**Don't wrap cache-backed client methods in `api_call()`.** It charges
the per-service rate limit, which is correct for HTTP but wrong for
in-memory reads. Pattern 4 originally did this against the
congress-legislators client (which serves from cache after first
fetch) and took 5+ minutes; priming the cache once through `api_call()`
and then querying directly brought it to 6.4 seconds.

When adding a pattern: verify matching logic against live data before
trusting it. Pattern 1 (`lobbyist_contribution_corroboration`) shipped
with two real bugs caught only by live-testing against a real
registrant — a silently truncated result page (client defaulted to 20
results/page; a single contributor can exceed that) and a fuzzy-name-
match threshold that missed legitimate abbreviation/expansion pairs.
Mocked tests alone would not have caught either.

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
