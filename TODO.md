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

## 3. LDA (lobbying)
- [ ] `packed/lda_client.py` — registrations (LD-1), quarterly activity (LD-2)
- [ ] Lobbyist political contributions (LD-203) — the core lobbying↔contribution link
- [ ] Add `LDA` tools to server.py

## 4. Detection patterns
Candidates from the design doc — build once phases 2–3 have real data to test against:
- [ ] Dual role — lobbyist for client X is also a bundler/major donor for a committee whose member sits on a committee X lobbies before
- [ ] Leadership PAC laundering
- [ ] JFC obscuring
- [ ] Timing correlation (contribution/lobbying spend vs. votes)
- [ ] Industry concentration

## 5. ProPublica Nonprofit Explorer (dark money)
- [ ] `packed/propublica_client.py` — 501(c)(4) Form 990 filings
- [ ] Cross-tool dark-money → Sift-sanctioned-entity detection pattern

## 6. Cross-tool composition
- [ ] Skill that calls both `packed` and `sift` for entity resolution
