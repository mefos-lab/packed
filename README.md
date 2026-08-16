# Packed

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)]()

An [MCP server](https://modelcontextprotocol.io/) for **cross-referencing PAC contributions, federal lobbying activity, and dark-money spending** — who is paying whom, to influence what, and who's on both sides of that transaction.

> [!NOTE]
> This is a research tool, not a compliance product. All data comes from public federal disclosures (FEC, Lobbying Disclosure Act filings, IRS Form 990s). Always verify findings against primary sources before drawing conclusions.

## What it does

Packed cross-references PAC/committee contributions, federal lobbying registrations and activity, and 501(c)(4) dark-money spending — connecting campaign finance to lobbying in a way no single government database does on its own. The key link is the LD-203 filing, where registered lobbyists disclose their own political contributions.

### What it is looking for

Almost everything this tool surfaces is legal. That is the point, not a
disclaimer.

Legality and abuse are different axes. The most consequential influence
operations are lawful by construction, because the people who benefit from the
rules also write them. Contribution limits are circumvented by structures that
comply with them exactly — a joint fundraising committee that lets one donor
write a single cheque larger than any participant could accept, a leadership PAC
that moves money between candidates, a party committee that receives what cannot
be given directly. None of that is a violation. All of it is disclosed.

So packed does not hunt for crimes. It makes lawful structure legible: who
funds whom, through which route, and whose committee seats the money lands on.
Disclosure regimes exist precisely so this can be seen — but the data is spread
across systems that do not reference each other, in volumes that defeat manual
reading, which means in practice it usually is not seen. That gap is what this
closes.

Findings should be read as structure and concentration, never as accusation.

## Status

Four data sources are integrated and verified live: OpenFEC (candidates, committees, itemized contributions and disbursements, independent and coordinated expenditures, financial totals), LDA (registrants, lobbyists, clients, filings, lobbyist contributions), ProPublica Nonprofit Explorer (501(c)(4) dark-money filings), and congress-legislators (committee membership plus the FEC-ID cross-reference that links a member of Congress to their campaign finance record).

Nine detection patterns are built and live-verified: corroborating LD-203 lobbyist contributions against FEC's independently-filed records, tracing a leadership PAC's money flow, and tracing a joint fundraising committee's money flow (who funds it — including donors giving far more than any single committee's limit — and which committees it splits proceeds to), aggregating a lobbying firm's political giving by the congressional committees its recipients sit on, the same for a PAC's outbound giving — which reports money routed through intermediary committees as unattributed rather than following it — mapping a lobbying operation's revolving-door ties, grouping its people by the committees they disclose having worked for, clustering contributions by shared employer — the shape of a reimbursement scheme, and equally the shape of lawful workplace fundraising, reported as a lead rather than a finding — finding vendors paid by both a campaign and an outside group spending to elect it, and reporting what share of a committee’s spending actually reaches candidates. See `TODO.md`.

All nine feed a **connection graph**: one node-and-edge vocabulary across every pattern, with a
route finder that answers "how is this entity connected to that one, and by how many separate
routes?" Several independent routes between the same pair is the finding; one is ordinary. Edges
declare what kind of claim they are — a disclosed amount, connectivity only past a commingled hop,
or a lead worth checking — and nothing is ever summed along a path, because money entering an
intermediary committee is commingled and no part of what leaves is traceable to a given donor.
`graph_connections` returns the graph and the routes, and can write a self-contained interactive
page that needs no network access to open.

Every pattern carries its own provenance: what the literature says about it, with each citation marked as supporting, limiting or contradicting the pattern, and patterns that are ungrounded reported as such rather than left to look sound.

## Quick start

```bash
git clone https://github.com/mefos-lab/packed.git
cd packed
python3 -m venv .venv && source .venv/bin/activate

# onoma is a mefos-lab library and is not published to PyPI, so it has to
# be installed from git before packed's own dependencies resolve.
pip install "onoma @ git+https://github.com/mefos-lab/onoma"
pip install -e .
```

`packed` depends on [onoma](https://github.com/mefos-lab/onoma) for name
normalization and matching. It is declared as an ordinary requirement rather
than a git URL so that publishing it later needs no change here — but until
that happens, `pip install -e .` on its own cannot find it, hence the extra
line above.

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

## Usage

The `/follow` skill is the entry point — it resolves an entity, runs the
relevant detection patterns, follows money routed through intermediary
committees, and reconciles the results into one picture.

```
/follow <name>                  — auto-detect and trace
/follow <name> --as pac         — treat as a PAC / political committee
/follow <name> --as firm        — treat as a lobbying registrant
/follow <name> --as member      — treat as a member of Congress
/follow <name> --deep           — follow intermediaries one hop further
```

Running a single pattern directly answers only part of the question:
much of a PAC's money reaches members through party committees, victory
funds and leadership PACs rather than directly. The skill exists to
compose those routes and report what share was actually traced.

## Worked examples

Both are transcripts of real runs against the live APIs, abridged. **The figures
are a snapshot of what was on file when the run happened, not current state** —
re-run them rather than citing these numbers.

### A corporate PAC: where the money actually goes

```
/follow "Microsoft Corporation Stakeholders Voluntary PAC" --as pac --cycle 2026
```

```
Entity   MICROSOFT CORPORATION STAKEHOLDERS VOLUNTARY PAC - MSVPAC (C00227546)
         designation: Lobbyist/Registrant PAC

Money traced
  Total disbursed                     $241,790
  To other committees                 $200,000
  Attributed to sitting members        $64,000
  Unattributed                        $136,000

Attribution rate — $64,000 of $200,000 (32%)

Committee exposure (29 committees)
  $12,000   5 members   House Foreign Affairs        <- Gregory W. Meeks (Ranking Member)
  $11,500   4 members   House Financial Services
  $10,000   2 members   Senate Armed Services
  $10,000   5 members   House Energy and Commerce    <- Frank Pallone, Jr. (Ranking Member)

Not traced
  $15,000   Republican National Committee            party — not attributable
  $15,000   Democratic National Committee            party — not attributable
  $10,000   Katherine Clark Victory Fund             designation J — joint fundraising
   $5,000   Responsibility and Freedom Work PAC      designation D — leadership PAC
```

The attribution rate is the point of this output. Only about a third of the
money reached members by a route that can be followed; the rest went to
committees that redistribute it later by processes this data does not capture.
A concentration figure quoted without that share attached would overstate what
is actually known.

Note also what the routes are: giving to both national party committees, and to
a victory fund and a leadership PAC. Each is a lawful instrument. Together they
are the ordinary machinery by which money reaches members without a direct,
attributable contribution.

### A joint fundraising committee: how limits are lawfully exceeded

```
/follow "Collins Victory Committee" --as pac --cycle 2026
```

```
Entity   COLLINS VICTORY COMMITTEE (C00692897)
         designation: Joint fundraising committee

Largest contributions in
  $25,000   KENNEDY, JAMES
  $25,000   KENNEDY, JAMES        (same donor, same day)
  $10,000   DARWISH, SAM

Split out to 4 participant committees — $709,740 total
  $509,977   COLLINS FOR SENATOR
   $83,265   PINE TREE RESULTS PAC
   $65,907   DIRIGO PAC
   $50,590   NRSC
```

This is the mechanism the pattern exists to surface. No individual may give a
Senate campaign $50,000. A joint fundraising committee may accept it, because
the sum is treated as separate contributions to each participant, each within
its own limit. The cheques are lawful, disclosed, and filed correctly — and the
aggregate relationship between one donor and one senator is invisible unless the
split is reassembled, which is what this does.

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
