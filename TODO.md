# Packed — Roadmap

Phased build order, per the design doc this repo was scaffolded from.

## ~~1. Repo scaffold~~ ✓
- ~~pyproject.toml, .gitignore, .mcp.json~~ ✓
- ~~packed/errors.py — centralized api_call(), rate limiting~~ ✓
- ~~packed/openfec_client.py — candidates, committees, contributions~~ ✓
- ~~packed/server.py — MCP tools for the above~~ ✓
- ~~tests/ — mocked-HTTP tests for errors.py and openfec_client.py~~ ✓

## 2. OpenFEC — expand coverage
- [x] Confirm endpoint paths/params against a real key ✓ verified live 2026-08-12
- [x] Add disbursements (Schedule B) — `fec_search_disbursements`, live-verified 2026-08-12. `recipient_committee_id` traces committee-to-committee transfers (leadership PAC / JFC), which unblocks patterns 2-3 below. Known API quirk: `pagination.count` isn't reliably filtered for very high-volume committees (e.g. ActBlue) even though the actual results are — documented in the client docstring, don't trust count for those.
- [ ] Add independent expenditures

## ~~3. LDA (lobbying)~~ ✓
- ~~`packed/lda_client.py` — filings (LD-1/LD-2), registrants, clients~~ ✓
- ~~Lobbyist political contributions (LD-203) — the core lobbying↔contribution link~~ ✓
- ~~Add `LDA` tools to server.py~~ ✓
- All 6 client methods verified against the live API 2026-08-12
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
- [ ] Dual role — lobbyist for client X is also a bundler/major donor for a committee whose member sits on a committee X lobbies before. Still blocked: needs committee-assignment data (who sits on which committee) — not covered by any of the 3 current sources.
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
- [ ] Timing correlation (contribution/lobbying spend vs. votes) — still blocked: needs legislative vote data, out of scope for all 3 current sources. Would need a 4th source.
- [ ] Industry concentration — still blocked: needs committee-assignment data, same blocker as "dual role"

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
18 tools currently (6 fec_*, 6 lda_*, 2 propublica_*, 3 pattern_*), all in a flat
per-source namespace. cyanheads/openfec-mcp-server manages 12 tools the same flat
way with no hierarchical grouping. No evidence flat naming is causing discoverability
problems yet — reconsider only if/when the count grows meaningfully past what's
already been shown to work fine elsewhere (e.g. 20-25+).
