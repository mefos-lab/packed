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
  `covered_position` revolving-door field named a committee too rarely and is inconsistent
  free text ("CoS, Sen Leahy, 2005-11") — **but see the correction under Pattern candidates
  below; the "~8% populated" figure recorded here was a mislabel and the member route was
  never evaluated**; mapping issue codes to committees of jurisdiction would be our
  editorial construction rather than disclosed fact. What IS supported is the recipient side —
  LD-203 `honoree_name` carries clean legislator names that resolve to committee seats.
  Live result for Akin Gump 2025: $189,325 across 141 items, concentrating on Senate
  Judiciary, House Ways & Means (incl. its Ranking Member), and Senate Commerce (incl.
  Chairman Ted Cruz).
- [x] **Pattern 5: industry_concentration** — aggregates a PAC's outbound giving by the
  congressional committees its recipients sit on. Shares `_CommitteeSeatTally` with
  pattern 4 (extracted when the second consumer appeared, same trigger as patterns 2/3).

  Unlike pattern 4 the join is **identifier-based end to end** — Schedule B
  `recipient_committee_id` -> the recipient's `candidate_ids` -> congress-legislators'
  `fec` field -> bioguide -> seats. No name matching, so no fuzzy-match tail to lose.

  **Coverage limit it reports rather than hides:** money sent to a committee with no
  candidate of its own (leadership PAC, party committee, joint fundraising committee)
  reaches a member through a hop this pattern does not follow. Those amounts surface as
  `unattributed_recipients`. On a real corporate PAC this was the majority of
  committee-directed money, so the headline understates exposure unless patterns 2 and 3
  are run alongside — which is a strong argument for the orchestration skill below.

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

- [x] **Migrated to mcp 2.0** ✓ (2026-08-13). `mcp>=2,<3` in pyproject; the 1.x->2.x
      break is absorbed by `packed/mcp_compat.py` rather than by rewriting tools.

      **Approach and why.** 2.0 derives each tool's schema from a Python function
      signature. Rewriting all 32 tools that way would have silently dropped enums
      (`office`: H/S/P, `support_oppose_indicator`: S/O), per-field descriptions and
      required/optional distinctions. Instead the shim: generates a handler whose
      *real* signature mirrors each schema (the manager validates against the
      function, not the advertised schema, so `**kwargs` is rejected), registers it
      via `Tool.from_function`, then overwrites the derived schema with the
      hand-authored one and points the handler at the existing dispatcher. Result:
      all 32 schemas advertised byte-identical, verified.

      Tool definitions now use a **local** `Tool` dataclass in `server.py` instead of
      the SDK type, so the next API break touches the shim rather than 32 definitions.

      **Known seam:** the shim writes `tool.parameters` and the manager's private
      `_tools` dict — 2.0 exposes no public way to register a pre-built schema, so
      this is deliberate. Guarded by
      `tests/test_server.py::test_registered_schemas_match_definitions`, which
      compares every advertised schema against its definition, so an SDK change
      fails loudly rather than degrading schemas silently.

      Other 2.0 changes hit along the way: `Server` -> `MCPServer`; `mcp.types` ->
      `mcp_types`; the wire type's `inputSchema` -> `input_schema`; and the stdio
      transport's `stdio_server()` context manager -> `await server.run_stdio_async()`.
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

## 10. Ground the detection patterns in the literature (not started)

sift's patterns cite institutional provenance — FATF typologies, FATF-Egmont on
beneficial ownership concealment, Moody's shell indicators, Wolfsberg, EU AMLD,
Transparency International. Each pattern file carries `sources:` and
`references:`, so a finding can be traced to an established typology rather than
resting on our own judgement.

packed's patterns carry none. They were derived from the project plan and from
what the data supports — defensible, but ungrounded. There is a substantial
literature for this domain that would serve the same role.

### One finding that bears directly on the current design

Hall & Wayman, "Buying Time: Moneyed Interests and the Mobilization of Bias in
Congressional Committees", *American Political Science Review* 84(3):797-820.
The empirical result: contribution effects appear **in committee rather than on
the floor**, and what shifts is legislators' *participation and effort*, not
their votes — contributions "mobilize legislative support and demobilize
opposition."

Two consequences:

- It **validates the committee-seat framing** of patterns 4 and 5. Aggregating
  money by the committees recipients sit on targets exactly where the literature
  locates the effect. That is worth citing in those patterns rather than leaving
  the choice to look arbitrary.
- It **argues against the timing-correlation pattern** on empirical grounds, not
  just interpretive caution. Roll-call votes are where the evidence for
  contribution influence is weakest, so a contributions-versus-votes pattern
  would be built on the least-supported link in the field. Reconsider whether to
  build it at all before spending a congress.gov key on it.

Kalla & Broockman's randomized field experiment on contributions and access to
congressional officials (*American Journal of Political Science*, 2016) points
the same way: access and attention, not vote-buying.

### Institutional sources — the FATF analogues

- **OECD Recommendation on Principles for Transparency and Integrity in
  Lobbying** (2010, revised 2024) — the first international standard on
  lobbying; closest structural analogue to the FATF Recommendations.
- **OECD, *Lobbying in the 21st Century: Transparency, Integrity and Access***
  (2021), and the *Anti-Corruption and Integrity Outlook* series — typologies of
  influence-seeking and circumvention.
- **International IDEA** — political finance handbook and comparative database;
  *Mapping and Analysing Lobbying Registers* (2024), useful for what disclosure
  regimes systematically fail to capture.
- **Transparency International** — *Towards Standards for Integrity in Political
  Finance* (2025), proposing transparency, clean money, level playing field,
  gender equality, state neutrality and accountability as principles; plus their
  political corruption topic guide.
- **FEC enforcement matters (MURs)** — documented real schemes, the nearest
  equivalent to FATF's case typologies. Worth mining for circumvention patterns
  that actually got prosecuted rather than theorised.

### ~~Suggested approach — a registry, not a fixed bibliography~~ ✓ built

Implemented as `patterns/SOURCES.yaml` + `patterns/PATTERNS.yaml`, loaded by
`packed/provenance.py`, surfaced by the `pattern_provenance` MCP tool, and
attached to every `PatternMatch` via a `provenance` property.

What shipped:

- **Keyed registry.** Sources have stable keys; patterns cite keys. Adding a
  work is appending an entry — no edits to existing patterns.
- **Stances.** Every citation is `supports`, `limits` or `contradicts`. This is
  the part a flat source list cannot express, and it is load-bearing here:
  Hall & Wayman supports the committee-seat framing of patterns 4 and 5 and
  contradicts a votes-based timing pattern. A test asserts one work appears on
  both sides, so the capability cannot regress unnoticed.
- **Status derived from citations.** PROPOSED / SUPPORTED / CONTESTED, with a
  test that status matches what actually cites the pattern — otherwise the two
  drift and the registry starts lying.
- **Uncited is visible.** `lobbyist_contribution_corroboration` reports
  PROPOSED with zero citations rather than implying grounding it does not have.
- **Rejected works recorded**, with reasoning: Soundex, and ProPublica's
  defunct Congress API.
- **`validate()`** catches the failure mode every keyed registry has — a
  citation pointing at a renamed or missing source, which raises nothing on its
  own.

Remaining work on this:

- [x] **FEC enforcement matters (MURs) added** (2026-08-15) as `fec_murs`,
      `kind: enforcement`. Queryable at `/v1/legal/search/?type=murs` on OpenFEC
      with the key packed already holds — no new credential. Each record carries
      the FEC's own `subjects` classification, `dispositions[].citations`
      (statute), and penalties, which makes it the case-typology source the
      registry was missing.

      Tallied over 600 unique MURs to get the real distribution rather than an
      impression. Top subjects: Reporting (339), Contributions-Prohibited (155),
      Contributions-Excessive (106), Contributions-Corporations (97), Soft Money
      (72), Personal use (51), In the name of another (49), Foreign Nationals
      (41), Expenditures-Coordinated (28), Fraudulent misrepresentation (11).

- [x] **Sources mined for patterns not yet thought of** (2026-08-15). Six
      candidates recorded in `PATTERNS.yaml` under `proposed:`, each assessed
      against what packed's data can actually support rather than what would be
      nice. In rough order of value:

  1. **`revolving_door`** — SUPPORTED, and the significant one. OECD names the
     revolving door as a principal integrity risk; LDA's `covered_position`
     discloses it. **This revives dual_role, which was closed as unbuildable.**
     Measured over 3,980 lobbyist-activity rows spread across the 2024 corpus:
     the field is populated for **30.8% of unique lobbyists**, of whose values
     67% name a member, 25% name a committee, 13% both.

     The earlier "~8% populated" figure was a mislabel — 8% is 30.8% × 25%, the
     *committee*-naming share, which is what a committee-level pattern needed.
     The **member** route (~21% of all lobbyists) was never evaluated, and it is
     the wide one: a named member resolves to committee seats through the
     congress-legislators index patterns 4 and 5 already build. Corrected in
     `packed/patterns.py` and above.

  2. **`conduit_contribution_cluster`** — SUPPORTED. Same-employer,
     same-amount, same-window contributors: the reimbursement-scheme shape.
     Schedule A alone. Grounded in a standing enforcement category (49 MURs,
     359 citations of 52 USC 30122) and a conciliated case with the exact shape
     (MUR 8363, Calspan, $25,000, 2025). **Lawful bundling looks identical** —
     this can only ever be a lead, which the entry says plainly.

  3. **`common_vendor_overlap`** — SUPPORTED. An IE committee and the campaign
     it supports paying the same vendor. Schedule B payee intersection, both
     sides already retrieved. Coordination is a legal conclusion disclosure
     cannot reach; the output is the overlap, not the conclusion.

  4. **`scam_pac_ratio`** — SUPPORTED. Raises substantially, disburses little to
     candidates. Computable from totals packed already pulls. Needs a receipts
     floor and a full cycle or a young committee trips it.

  5. **`foreign_national_contributions`** — CONTESTED, and instructive. Strong
     enforcement grounding (41 MURs; 30121(a)(2) is the third most cited statute
     at 441) but the same source argues against the test: citizens abroad and
     permanent residents contribute lawfully from foreign addresses, while the
     prosecuted schemes route through domestic straw donors and LLCs with US
     addresses. The test inverts — it catches the lawful and misses the
     prosecuted. Cited twice from one source at opposite stances, which is what
     the stance field was added for.

  6. **`foreign_principal_lobbying`** — SUPPORTED. LDA `foreign_entities`,
     confirmed live and populated on 3.0% of a 200-filing 2024 sample, naming
     parents directly (Huawei behind Futurewei; Kolon Group). Sparse, and the
     narrower of the two registers — FARA is the other and packed lacks it, so
     this is as much a recorded data gap as a pattern.

  Deliberately **not** carried forward: Reporting is the largest enforcement
  category (339) but is overwhelmingly administrative late/non-filing with no
  investigative signal; Disclaimer (62) and Soft Money (72) need ad-level and
  state-party data packed does not have.

- [x] **`revolving_door` built and live-verified** (2026-08-15). Parser in
      `packed/covered_position.py`, pattern in `packed/patterns.py`, exposed as
      `pattern_revolving_door`. `dual_role` is now closed rather than pending.

      Parser measured against 448 distinct 2024 `covered_position` values before
      any pattern code was written: **41.3% yield at least one current member or
      committee**, with committee-phrase precision at 85%. Two changes during
      that measurement mattered more than the rest — splitting on clause
      boundaries, without which "Health Policy Advisor, Senate Finance
      Committee" scored equally against Senate Finance and Senate HELP and went
      ambiguous; and refusing `Comm` as an abbreviation, which collides with
      "Dept of Comm" and "FHA Commissioner". An abbreviation table carries the
      shorthand no substring match reaches (`E&C`, `Ag`, `Approps`, `HELP`).

      Live on Akin Gump 2024: 200 filings, 58 distinct lobbyists, 28 disclosing
      a covered position, 7 resolving to a current tie across 24 committees —
      Senate Judiciary and Senate Veterans' Affairs at the top. The gap between
      28 and 7 is almost entirely former members (Alexander, Breaux, Brownback,
      Burr), which the result reports by name rather than dropping.

      Design rule, and the answer to the earlier "guesswork" objection: the
      parser proposes, the roster disposes. Nothing resolves unless it matches
      exactly one current entity; a phrase naming no chamber is reported
      ambiguous rather than assigned.

- [x] **`employer_contribution_clusters` built and live-verified** (2026-08-15),
      renamed from `conduit_contribution_cluster` before building: "conduit"
      asserts the mechanism the data cannot establish.

      **Verified against the case that grounds it.** MUR 8363 conciliated with
      Calspan Corporation over contributions reimbursed with corporate funds.
      The pattern's top cluster for that employer is four donors to McCollum for
      Congress on 2022-06-03 — Meier, Sauer, Swanson and Rivers — comprising
      every individual the matter names. It also surfaces Meier and Sauer giving
      an identical $1,000 to Wicker for Senate on the same day.

      **The first attempt found nothing, and both causes were assumptions
      rather than measurements.** Worth recording because they were not obvious:

      - Requiring 3+ donors erased the case entirely. The scheme ran **two at a
        time**. `min_donors` now defaults to 2.
      - Pass-through committees supplied **708 of 975 rows** for that employer,
        almost all $10–$25 recurring ActBlue donations. They name the conduit as
        recipient rather than the campaign, so they both drown the signal and
        cannot be clustered meaningfully. Excluded by default.

      Amount uniformity is the one discriminator available and is flagged
      separately: a reimbursement is a fixed sum per person, colleagues giving
      independently rarely match to the dollar. Suggestive, not decisive — the
      description and warnings both state that lawful bundling is
      indistinguishable and the output is a lead.

      Required adding `contributor_employer` and Schedule A keyset pagination
      (`last_index` + `last_contribution_receipt_date`, which must be sent
      together or the API 422s) to the OpenFEC client.

- [x] **`common_vendor_overlap` built and live-verified** (2026-08-15).

      **The specification was wrong about where the data lives, and measuring
      first is what caught it.** The candidate said "Schedule B on both sides".
      An independent-expenditure committee reports media buys on **Schedule E**
      under its own payee field and carries almost nothing on B — UNITE TO WIN
      had *one* Schedule B row; A STRONGER MICHIGAN had ten. A Schedule-B-only
      intersection would have returned essentially nothing and looked like a
      dead pattern. Campaign side reads B; outside side reads E and B together.

      Live on Haley Stevens (S6MI00426, 2026): 157 campaign payees, 10 outside
      spenders found, 5 examined, 2 with overlap. The signal is **Mission
      Control** — $1,389,589 from United Democracy Project against $9,250 from
      the campaign. The rest of the overlap is commodity noise (United Airlines,
      Uber, Hotels.com, LexisNexis), which is why each vendor carries its share
      of each side's spending.

      **Found an onoma defect.** `same_org("AT&T", "MILLER'S SUPPLIES AT WORK")`
      returns True: "AT&T" folds to the single token "at", a common English
      word, which is then found inside the longer name. `require_strong=True` is
      not the fix — it also rejects `LEXISNEXIS` against itself, since a
      one-token org can never be "strong". Guarded here by requiring a shared
      distinctive token of length >= 4. **This will bite sift too.**

      Share percentages are computed over retrieved spending, not a committee's
      full ledger, because pagination is capped. Field names say `sampled` so
      the denominator cannot be misread.

- [x] **onoma single-short-token defect fixed upstream** (mefos-lab/onoma,
      branch `function-words`). `GENERIC_ORG_TOKENS` was missing prepositions,
      so "AT&T" reduced to the distinctive token "at"; and because comparison
      scores overlap against the shorter name, a one-token name scored 1.0
      against anything containing that word. Fixed there, along with the
      related surprise that `require_strong` rejected a one-word organisation
      compared against itself.

- [x] **`_same_vendor`'s token-length guard removed** (2026-08-15), now that
      onoma treats prepositions as generic. It had become actively wrong rather
      than merely redundant — requiring a shared token of >= 4 characters
      rejected `BP` against `BP AMERICA` and `3M` against `3M COMPANY`. Both
      are now regression-tested here, alongside the AT&T case that started it.
      Dependency declared as `onoma>=0.1.1`.

- [ ] **The onoma dependency does not resolve.** Declared as a plain
      requirement in both packed and sift, but onoma is not on any index:
      `pip install "onoma>=0.1.1"` fails with "No matching distribution found"
      in a clean environment (verified). It works locally only because onoma is
      installed editable from a sibling checkout, so the README's
      `pip install -e .` cannot work for anyone else. Two fixes: publish onoma,
      or depend on it by URL (`onoma @ git+https://github.com/mefos-lab/onoma@<tag>`,
      which needs a tag that does not yet exist). Publishing is deferred by
      choice; until one of them happens, neither repo is installable.
- [x] **`candidate_support_ratio` built and live-verified** (2026-08-15),
      renamed from `scam_pac_ratio`.

      **The grounding was a misattribution, and checking it is what caught
      that.** The registry cited the FEC's "Fraudulent misrepresentation"
      enforcement subject as evidence the conduct was pursued. The statute
      behind that label is 52 USC 30124 — impersonating a candidate or party
      while soliciting — which has nothing to do with a committee's spending
      mix. The subject label had been read as though the colloquial phrase
      "scam PAC" were a legal category. `fec_murs` is now cited as a **limit**
      on this pattern rather than support for it, so the error stays recorded.
      A note in `SOURCES.yaml` warns to check the statute behind any MUR
      subject before treating the label as evidence.

      **The FEC already computes the ratio.** `operating_expenditures_percent`
      and `contributions_ie_and_party_expenditures_made_percent` are existing
      fields, so they are surfaced rather than recalculated and a reader can
      reconcile against the agency. What packed adds is the receipts floor and
      the cycle-by-cycle view.

      Live: Campaign for a Conservative Majority (a MUR respondent) 2020 —
      $473,371 receipts, 12.85% to candidates, 87% operating, flagged. Club for
      Growth runs 78–97% to candidates across four cycles and is not flagged.
      The floor correctly excluded three periods for the first committee, where
      receipts were four figures and the ratio meaningless.

- [x] **`follow` skill brought back in step with the tools** (2026-08-15).
      It described five patterns while nine existed, so `revolving_door`,
      `employer_contribution_clusters`, `common_vendor_overlap` and
      `candidate_support_ratio` were unreachable through the documented entry
      point. Added a company/employer trace as a fourth entity type, put
      `candidate_support_ratio` first in the PAC trace (it decides whether the
      rest is worth reading), and taught the skill to surface `provenance` —
      the registry existed but the composition layer never used it.

      **Two tests now hold this closed**: every `pattern_*` tool must be named
      in the skill, and every tool the skill names must exist. The drift
      happened because nothing checked, which is the same failure as the
      `asdict` provenance drop — correct code, no test on the seam.

      Sharpened the LDA caveat rather than deleting it. "LDA never records
      which committee a client lobbies" is still true; `revolving_door` names
      committees a firm's *staff came from*, which is a different claim, and
      the skill now says to keep them in separate sentences.

- [x] **Connection graph built** (2026-08-15) — `packed/graph.py`,
      `packed/graph_html.py`, exposed as `graph_connections`.

      **Why a connection graph and not a money-flow diagram.** Commingling means
      no amount survives an intermediary hop, so a weighted Sankey would invent
      a number. Connectivity does survive, which is what makes "these two are
      linked by three separate routes" a fact worth drawing. Edges declare their
      kind — ATTRIBUTABLE, ROUTE or LEAD — and the dataclass **raises** if a
      ROUTE or LEAD edge is given an amount. That guard is the design, not a
      nicety.

      Node identity is explicit: `fec:C00799031` is exact, `vendor:mission-control`
      is an onoma name match that can merge or miss entities. Rendered
      differently, because a path is only worth what its weakest node is.

      **A real problem the live run exposed.** Stevens<->UDP returns six routes,
      and four are Uber, Hotels.com and United Airlines — structurally identical
      to the real one, evidentially worthless. Every committee buys from the same
      travel and shipping vendors. The graph cannot judge this itself, so the
      vendor's share of each side's spending travels onto the node and the
      renderer flags any route whose intermediary took under 0.1%. Mission
      Control ($1.39M, 0.92%) is correctly not flagged.

      Adapters are per-pattern and a pattern without one is skipped rather than
      fatal, so adding a detection pattern never breaks graph building.

      HTML output is one self-contained file — no network access, so it still
      opens in five years. Payee names are escaped against closing the script
      element early, which is a real risk since they are free text from public
      filings.

      **Rebuilt on sift's pattern after the first attempt was rejected as
      unreadable.** The first version was a hand-rolled force loop rendering
      every node and label at once — a hairball. sift had already solved this
      and it was not consulted, which was the actual mistake. Adopted from it:
      D3 vendored locally (`packed/visualizations/`), a tabbed report rather
      than a single canvas, and an overview stating findings in prose before
      any graph appears. `forceCollide` is what stops nodes and labels
      overlapping; only the better-connected third are labelled at rest.

      Tabs are Overview, Network, Routes, Committee exposure, Clusters,
      Revolving door, Support ratio and Limits. A tab with no data is hidden
      rather than shown empty — an empty tab reads as "nothing found" when the
      truth is "that pattern was not run". The overview narrative is generated
      from the data, so it never promises findings it cannot list.

- [ ] Remaining mined candidates are all judged not worth building as
      specified: `timing_correlation` and `foreign_national_contributions` are
      CONTESTED, `dual_role` is closed in favour of `revolving_door`, and
      `foreign_principal_lobbying` is grounded but sparse (3% of filings) and
      would mostly document a data gap — FARA is the register that matters and
      packed does not have it.
- [ ] Retrofit remains partial: `lobbyist_contribution_corroboration` is
      genuinely ungrounded rather than merely unresearched. It rests on the two
      filing regimes being independent, which is a property of the regimes, not
      a claim the influence literature speaks to.
