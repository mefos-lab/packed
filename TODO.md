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
- [ ] **Leadership PAC laundering** — no longer blocked. `fec_search_disbursements(recipient_committee_id=...)` can now trace committee-to-committee transfers. Ready to build.
- [ ] **JFC obscuring** — no longer blocked, same disbursement data unblocks this too. Ready to build.
- [ ] Timing correlation (contribution/lobbying spend vs. votes) — still blocked: needs legislative vote data, out of scope for all 3 current sources. Would need a 4th source.
- [ ] Industry concentration — still blocked: needs committee-assignment data, same blocker as "dual role"

## ~~5. ProPublica Nonprofit Explorer (dark money)~~ ✓
- ~~`packed/propublica_client.py` — Form 990 filings, 501(c)(4) c_code filter~~ ✓
- Both client methods verified against the live API 2026-08-12
- [ ] Cross-tool dark-money → Sift-sanctioned-entity detection pattern (still needs phase 4)

## 6. Cross-tool composition
- [ ] Skill that calls both `packed` and `sift` for entity resolution

## 7. Provider capability review (not started)
Re-read the full docs for each provider — OpenFEC (api.open.fec.gov/developers/),
LDA (lda.gov/api/openapi/v1/), ProPublica Nonprofit Explorer
(projects.propublica.org/nonprofits/api) — beyond what was needed for the
endpoints already built, to check for other capabilities worth exposing
(e.g. OpenFEC has electioneering communications, 24/48-hour reports, F1
registrations; LDA's constants endpoints; bulk/download data). Also check
whether any of these providers already publish their own MCP server/toolset
that's worth learning from or composing with instead of reimplementing.
