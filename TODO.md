# Packed — Roadmap

Phased build order, per the design doc this repo was scaffolded from.

## ~~1. Repo scaffold~~ ✓
- ~~pyproject.toml, .gitignore, .mcp.json~~ ✓
- ~~packed/errors.py — centralized api_call(), rate limiting~~ ✓
- ~~packed/openfec_client.py — candidates, committees, contributions~~ ✓
- ~~packed/server.py — MCP tools for the above~~ ✓
- ~~tests/ — mocked-HTTP tests for errors.py and openfec_client.py~~ ✓

## ~~2. OpenFEC — expand coverage~~ ✓
- [x] Confirm endpoint paths/params against a real key ✓ verified live 2026-08-12
- [x] Add disbursements (Schedule B) — `fec_search_disbursements`, live-verified 2026-08-12. `recipient_committee_id` traces committee-to-committee transfers (leadership PAC / JFC), which unblocks patterns 2-3 below. Known API quirk: `pagination.count` isn't reliably filtered for very high-volume committees (e.g. ActBlue) even though the actual results are — documented in the client docstring, don't trust count for those.
- [x] Add independent expenditures (Schedule E) — `fec_search_independent_expenditures`, live-verified 2026-08-12
- [x] Add coordinated party expenditures (Schedule F) — `fec_search_coordinated_expenditures`, live-verified 2026-08-12
- [x] Add committee/candidate financial totals — `fec_get_committee_totals`, `fec_get_candidate_totals`, live-verified 2026-08-12
- [x] Add candidate↔committee linkage — `fec_get_candidate_committees`, live-verified 2026-08-12
- All 5 additions came directly from the phase-7 provider capability review (confirmed gaps vs. a competing OpenFEC MCP server, each verified live before building). 11 fec_* tools now, 22 MCP tools total.

## ~~3. LDA (lobbying)~~ ✓
- ~~`packed/lda_client.py` — filings (LD-1/LD-2), registrants, clients~~ ✓
- ~~Lobbyist political contributions (LD-203) — the core lobbying↔contribution link~~ ✓
- ~~Add `LDA` tools to server.py~~ ✓
- ~~Lobbyist/client entity coverage — `search_lobbyists`, `get_lobbyist`, `get_client`,
  `get_contribution` (single LD-203 by UUID)~~ ✓ live-verified 2026-08-12. Closes the LDA
  gaps identified in the phase-7 review. Lobbyists are a distinct entity from registrants
  (a firm employs many) — 372 lobbyists under Akin Gump alone.
- All 11 client methods verified against the live API 2026-08-12
- Rate limit confirmed from live OpenAPI schema (120/min authenticated) — not a conservative guess like the others

## 4. Detection patterns
No generic graph/rule engine like Sift's `pattern_matcher.py` — packed has no
cross-source traversal layer, so each pattern is a bespoke function in
`packed/patterns.py`. See its module docstring for the reasoning.

- [x] **Pattern 1: lobbyist_contribution_corroboration** ✓ — cross-references LD-203
  lobbyist contributions against FEC Schedule A. Live-verified 2026-08-12, found
  2 real corroborated matches (out of 9 items) for a real registrant. Found and
  fixed two real bugs during live testing: FEC lookup was silently truncated to
  the default 20-result page (fixed: request 100), and word-overlap name
  matching missed abbreviation/expansion pairs like "ARKANSAS LEADERSHIP PAC" vs
  "ARKANSAS FOR LEADERSHIP POLITICAL ACTION COMMITTEE (ARKPAC)" (fixed: ratio
  against the shorter name, require a non-generic shared word).
- [ ] **Dual role** — lobbyist for client X is also a bundler/major donor for a committee whose
  member sits on a committee X lobbies before. **No longer blocked** — source found, see
  phase 8 below. Ready to build once congress-legislators is integrated.
- [x] **Pattern 2: leadership_pac_transfers** ✓ — traces a leadership PAC's money flow: top
  Schedule A contributors funding it, and Schedule B transfers it makes to other committees
  (filtered to rows with a recipient_committee_id, i.e. not vendor spending). Live-verified
  2026-08-12 against ARKPAC (Sen. Boozman's leadership PAC): $5,000 max-out contributions
  from corporate PACs (Goldman Sachs, CoreCivic, Microsoft) in, $405,000 transferred out
  across 12 committees, including $275,000 to the Senate Leadership Fund. Found and fixed a
  real bug during live testing: tried to append custom warnings to `ServiceTracker.warnings`,
  which is a read-only computed property (derived from `.errors`), not a mutable list — the
  append silently did nothing. Fixed by tracking pattern-level warnings separately and
  combining with `tracker.warnings` at return time.
- [x] **Pattern 3: jfc_obscuring** ✓ — same money-in/money-out shape as pattern 2, refactored
  into a shared `_trace_committee_money_flow()` helper (both patterns turned out to share
  identical structure — exactly the trigger the module docstring flagged for revisiting
  "bespoke per pattern"). Scoped to designation "J" instead of "D". Live-verified 2026-08-12
  against Collins Victory Committee (C00692897): individual donor James Kennedy gave two
  separate $25,000 contributions (far above what any single committee could legally accept
  directly), and the JFC's $709,739 total split across 4 committees — $509,977 straight to
  Collins for Senator, plus NRSC and two allied PACs. Textbook example of the pattern.
  Research note: FEC Schedule A has a real memo_code/memo_text mechanism that could show the
  *exact* per-participant split of a single bundled check, but its semantics weren't
  confirmed precisely enough to build on with confidence — documented in the module
  docstring as a known gap, not silently guessed at.
- [ ] **Timing correlation** (contribution/lobbying spend vs. votes) — **no longer blocked**,
  source found (congress.gov API has House roll-call votes from the 118th Congress / 2023
  onward). See phase 8. Note the coverage limit: House only, 2023+ — Senate votes and
  pre-2023 history are not available from this source.
- [ ] **Industry concentration** — **no longer blocked**, same congress-legislators
  committee-assignment source as "dual role". See phase 8.

## ~~5. ProPublica Nonprofit Explorer (dark money)~~ ✓
- ~~`packed/propublica_client.py` — Form 990 filings, 501(c)(4) c_code filter~~ ✓
- Both client methods verified against the live API 2026-08-12
- [ ] Cross-tool dark-money → Sift-sanctioned-entity detection pattern (still needs phase 4)

## 6. Cross-tool composition
- [ ] Skill that calls both `packed` and `sift` for entity resolution

## ~~7. Provider capability review~~ ✓ (2026-08-12)

### Existing MCP toolsets for these providers
Not first movers on any of the 3 sources — real, existing (unofficial, third-party)
MCP servers found for all three:
- **OpenFEC**: several, most complete is cyanheads/openfec-mcp-server (12 tools —
  see below). Also sh-patterson/fec-mcp-server, reichaves/fec-mcp-server,
  hodgesmr/agent-fecfile (a Claude Code plugin specifically).
- **ProPublica Nonprofit Explorer**: cyanheads/nonprofit-explorer-mcp-server (3
  tools), asachs01/propublica-mcp.
- **LDA**: a hosted product (mcpbundles.com) covering Senate LDA disclosures —
  no open-source implementation found, so nothing to directly compare tool-for-tool.

None of them do cross-source correlation — every one is a single-provider wrapper.
**packed's actual differentiator isn't "having an FEC API wrapper," it's the
detection patterns that cross-reference LDA against FEC** (corroboration, money-flow
tracing). That's confirmed to be genuinely unaddressed by anything else found.

### Capability gaps confirmed against the live API (worth adding)
Cross-referencing cyanheads/openfec-mcp-server's 12-tool list against ours (6) and
verifying each candidate gap actually exists live before trusting it:
- [ ] **Independent expenditures** (`/schedules/schedule_e/`) — already on this TODO
  (phase 2), now double-confirmed valuable: a real competing tool has it as a
  dedicated tool, and live probe confirmed 19,506 real records for one candidate/cycle.
- [ ] **Coordinated party expenditures** (`/schedules/schedule_f/`) — new finding,
  confirmed live (200, valid response, though 0 results for the one committee tested
  — a party committee would show real data). Distinct disclosure category from
  independent expenditures.
- [ ] **Committee/candidate financial totals** (`/committee/{id}/totals/`,
  `/candidate/{id}/totals/`) — new finding, confirmed live. Cheap, high-value add:
  "how much has X raised/spent this cycle" without pulling itemized data.
- [ ] **Candidate↔committee linkage** (`/candidate/{id}/committees/`) — new finding,
  confirmed live. Resolves which committees belong to a candidate directly, instead
  of inferring from search results.
- [ ] **Filing index search** (`/filings/`) — new finding, confirmed live. Lower
  priority — useful for finding original source documents/dates, not core to
  money-flow tracing.
- [ ] **Legal/enforcement data** (advisory opinions, enforcement cases) — new
  finding from competitor tool list, not independently verified live. Different
  domain (FEC compliance actions) from our money-flow focus — lower priority, but
  could feed a future "under regulatory scrutiny" signal.
- LDA gaps identified from the already-fetched OpenAPI schema (not new research):
  `search_lobbyists`/`get_lobbyist(id)` (lobbyists are a separate entity from
  registrants — moderate value), `get_client(id)`, `get_contribution(filing_uuid)`
  (single filing lookup vs. our search-only). LDA's `constants/*` endpoints are
  just enum lookups (filing types, countries, etc.) — low value, skip.
- ProPublica: no real gap. Competitor splits `get_filings` into a separate tool
  from `get_organization`; ours already returns filing history embedded in
  `get_organization` (confirmed live earlier) — same coverage, different shape.

### Own MCP toolset organization
18 tools at review time (now 26), all in a flat per-source namespace.
cyanheads/openfec-mcp-server manages 12 tools the same flat way with no hierarchical
grouping. No evidence flat naming is causing discoverability problems yet — but at 26
tools we're now past the 20-25 threshold this review flagged, so worth an actual look
next time the count grows (especially once a 4th source lands).

## 8. New sources for previously-blocked patterns (researched 2026-08-12, not yet built)

All three remaining detection patterns were blocked on data none of the 3 current
sources have. Both blockers now have a confirmed, free, live-verified source.

### congress-legislators (committee assignments) — unblocks dual role + industry concentration
Static YAML/JSON/CSV data files in a public GitHub repo (github.com/unitedstates/
congress-legislators), maintained as a shared commons. No API key, no rate limit — just
raw file fetches. Verified live 2026-08-12:
- `committee-membership-current.yaml` (~292KB) — maps committee ID → list of members with
  `name`, `party`, `rank`, `title` (Chairman / Ranking Member), and `bioguide` ID.
- `committees-current.yaml` (~63KB) — committee metadata.
- `legislators-current.yaml` (~1MB, 537 legislators) — **critically, includes an `id` block
  with `fec` (a list of FEC candidate IDs), plus `bioguide`, `opensecrets`, `govtrack`, etc.**

**Why this matters:** the `fec` ID field is the join key. Committee assignments link to
legislators by `bioguide`, and legislators link to packed's existing FEC data by `fec`
candidate ID — so committee membership can be joined to contribution/expenditure data
without any fuzzy name matching. That was the thing that made these patterns infeasible.

Concrete example of the full chain, confirmed during research: bioguide `B001236` is
John Boozman, Chairman of `SSAF` (Senate Agriculture), FEC IDs `H2AR03176`/`S0AR00150` —
and ARKPAC (already live-verified in pattern 2) is his leadership PAC. Leadership PAC →
candidate → committee chairmanship, fully linkable.

Caveat: committee membership is **current-only** (no historical snapshots), so patterns
built on it describe the present, not a point-in-time past. Note that in any output.

- [x] **Add `congress_legislators_client.py`** ✓ built and live-verified 2026-08-12. Fetches
  and parses the three YAML files, caching each in-process after first fetch (they're static
  documents, not a query API — `refresh()` drops the cache). 5 MCP tools:
  `congress_find_legislator_by_fec_id` (the join), `congress_search_legislators`,
  `congress_get_legislator_committees`, `congress_get_committee_members` (roster with FEC
  IDs attached), `congress_search_committees`.
  - Live-verified the full join chain end to end: FEC ID `S0AR00150` → John Boozman
    (`B001236`) → 20 committee/subcommittee seats including **Chairman of Senate
    Agriculture** and Chairman of an Appropriations subcommittee. Reverse direction too:
    the Senate Agriculture roster returns 23 members, **all 23 resolving to FEC IDs**.
  - Implementation details worth knowing: subcommittee membership keys are parent
    `thomas_id` + the subcommittee's 2-digit `thomas_id` (SSAF + 13 = `SSAF13`) — the client
    flattens both into one index and resolves parent names. Added `pyyaml` as a real
    dependency (it was missing from pyproject.toml entirely). Added a
    `congress-legislators` entry to `SERVICE_RATE_LIMITS`, though caching means it rarely
    engages.
  - Edge cases handled and covered by tests: 2 of 537 legislators have no FEC ID at all,
    and 64 have multiple (up to 3, e.g. someone who ran for House then Senate) — so the
    FEC index is many-IDs-to-one-legislator.
- [x] **Pattern 4: lobbying_money_to_committee_seats** ✓ built and live-verified 2026-08-12.
  **Deliberately not "dual role" as originally specified** — that required knowing which
  committee a client lobbies before, and LDA does not record it: its `government_entities`
  field has 257 possible values and **zero are congressional committees** (only chamber-level
  "HOUSE OF REPRESENTATIVES"/"SENATE", which nearly every filing names, making a
  chamber-level version vacuous). Two alternatives were evaluated and rejected: the
  `covered_position` revolving-door field is only ~8% populated and is inconsistent free text
  ("CoS, Sen Leahy, 2005-11"); mapping issue codes to committees of jurisdiction would be our
  editorial construction rather than disclosed fact. What IS supported is the recipient side —
  LD-203 `honoree_name` carries clean legislator names that resolve to committee seats.
  Live result for Akin Gump 2025: $189,325 across 141 items, concentrating on Senate
  Judiciary, House Ways & Means (incl. its Ranking Member), and Senate Commerce (incl.
  Chairman Ted Cruz).
- [ ] Build industry concentration pattern — same shape as pattern 4 (aggregate a funder's
  giving by recipient committee seats), but sourced from FEC PAC contributions rather than
  LD-203. Worth checking whether it should share a helper with pattern 4 the way patterns
  2/3 do.

### congress.gov API (roll-call votes) — unblocks timing correlation
Official Library of Congress API at api.congress.gov. Requires a free API key (confirmed
live: returns `API_KEY_MISSING` 403 without one, so key request is a real prerequisite).
Covers bills, amendments, members, committees, and — added 2025 — House roll-call votes.

**Coverage limit, important:** House roll-call votes only, from the 118th Congress (2023)
onward. No Senate votes, no pre-2023 history. Timing correlation built on this can only
speak to recent House activity — state that plainly in the pattern's output rather than
implying full congressional coverage.

- [ ] Request congress.gov API key (free, same general pattern as the OpenFEC key)
- [ ] Add a `congress_gov_client.py`
- [ ] Build timing correlation pattern (scoped to House, 2023+)

### Also noted during research
- ProPublica's Congress API (historically the go-to for this data) is **no longer
  available** — don't reach for it, it's dead. Same for the Sunlight Congress API, whose
  parent organization wound down its open-data work.
- congress.gov also exposes committee data, overlapping congress-legislators. Prefer
  congress-legislators for membership (no key, simpler), congress.gov for votes.

## 9. Known issues / follow-ups (found 2026-08-12)

### mcp 2.0 API migration — server was silently broken
`packed/server.py` stopped importing entirely when pip resolved the unpinned
`mcp>=1.0.0` dependency to **mcp 2.0.0**, which removed the
`@server.list_tools()` / `@server.call_tool()` decorator API the server is built
on (and removed `mcp.server.fastmcp`). Nothing caught it: every test imported
clients and patterns directly and none imported the server, so the full suite
passed green while the actual product could not start.

Fixed for now by pinning `mcp>=1.0.0,<2` and adding `tests/test_server.py`,
which imports the server and asserts tools register — so this fails loudly next
time rather than silently.

- [ ] Migrate to the mcp 2.0 API and lift the pin. Latest 1.x is 1.29.0, so
      there's runway, but the pin shouldn't be permanent.

  **API research (done 2026-08-13, against a real mcp 2.0.0 install — not docs).**
  The two versions are structurally different, not renamed:

  | | mcp 1.x (what we use) | mcp 2.0 |
  |---|---|---|
  | Registration | `@server.list_tools()` returning `list[Tool]` with hand-written JSON Schema | tool-manager based; `@server.tool()` decorator or `add_tool(fn, name=, description=)`, **schema derived from the function signature** |
  | Dispatch | single `@server.call_tool()` if/elif dispatcher | per-tool callables, via `MCPServer.call_tool` -> `self._tool_manager.call_tool(...)` |
  | Transport | `async with stdio_server() as (r, w): await server.run(r, w, ...)` | `await server.run_stdio_async()` |
  | Class | `mcp.server.Server` | `mcp.server.MCPServer` (also exported as `Server`) |

  `MCPServer.__init__` does accept `tools: list[Tool] | None` (the `mcp_types.Tool`
  wire type, so explicit inputSchema is expressible) — worth confirming whether that
  path can register a handler alongside an explicit schema, since it would preserve
  the hand-authored schemas and make this a far smaller change than rewriting all 32
  tools as typed functions.

  **Why this needs its own session, not a tail-end sprint:** all 32 tools carry
  hand-authored schemas with enums (`office`: H/S/P, `support_oppose_indicator`:
  S/O), per-field descriptions, and required/optional distinctions. Signature-derived
  schemas would need `Annotated`/`Field` to preserve that fidelity. The failure mode
  is silent — a subtly degraded schema means the model calls the tool slightly wrong,
  and no test in this repo would catch it (the server smoke tests assert a schema
  exists, not that it's faithful). Budget real time and diff the generated schemas
  against the current hand-written ones before shipping.
- [ ] Consider whether Sift has the same exposure — it uses the same
      `@server.list_tools()` decorator pattern and may have the same unpinned
      dependency.

### Rate limiter was applied to in-memory cache reads
Pattern 4 initially routed every congress-legislators lookup through
`api_call()`, which charges the per-service rate limit. Since that client serves
everything from an in-process cache after the first fetch, this billed a
1-second wait for what were dict reads — the pattern took **5+ minutes**.
Restructured to prime the cache once through the rate-limited path, then do
lookups directly: **6.4 seconds**. Worth remembering when wiring future
cache-backed clients — `api_call()` belongs around actual HTTP, not around
methods that usually hit cache.
