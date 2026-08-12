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
- [ ] Add disbursements (Schedule B) — where committee money goes out
- [ ] Add independent expenditures
- [ ] Add committee-to-committee transfers (leadership PAC / JFC tracing)

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
- [ ] Dual role — lobbyist for client X is also a bundler/major donor for a committee whose member sits on a committee X lobbies before. Needs committee-assignment data (who sits on which committee) — not covered by any of the 3 current sources.
- [ ] Leadership PAC laundering — needs OpenFEC disbursements (Schedule B) / committee-to-committee transfers, not yet built (see phase 2 remainder above)
- [ ] JFC obscuring — same blocker as leadership PAC laundering (transfer data)
- [ ] Timing correlation (contribution/lobbying spend vs. votes) — needs legislative vote data, which isn't in scope for any of the 3 current sources at all. Would need a 4th source.
- [ ] Industry concentration — needs committee-assignment data, same blocker as "dual role"

## ~~5. ProPublica Nonprofit Explorer (dark money)~~ ✓
- ~~`packed/propublica_client.py` — Form 990 filings, 501(c)(4) c_code filter~~ ✓
- Both client methods verified against the live API 2026-08-12
- [ ] Cross-tool dark-money → Sift-sanctioned-entity detection pattern (still needs phase 4)

## 6. Cross-tool composition
- [ ] Skill that calls both `packed` and `sift` for entity resolution
