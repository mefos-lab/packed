---
name: follow
description: Follow political money — trace what a PAC, lobbying firm, or member of Congress funds and is funded by, across FEC contributions, lobbying disclosures, and congressional committee seats.
---

# Follow

Traces political money through the packed data sources and composes the
detection patterns into a single picture.

The reason this skill exists rather than leaving the tools to be driven
directly: **no single pattern answers the question a user actually
asks.** A PAC's direct giving is only part of its exposure, because much
of the money goes to intermediary committees — party committees, victory
funds, leadership PACs — which then pass it on. Run one pattern and the
answer is confidently incomplete. Running the set and reconciling them
is the whole job, and that is what this automates.

## Usage

```
/follow <name>                        — auto-detect what the name is, then trace it
/follow <name> --as pac               — treat as a PAC / political committee
/follow <name> --as firm              — treat as a lobbying registrant
/follow <name> --as member            — treat as a member of Congress
/follow <name> --as company           — treat as an employer, via its people's giving
/follow <name> --cycle 2026           — scope to an election cycle
/follow <name> --deep                 — follow intermediary committees one hop further
/follow <name> --subcommittees        — include subcommittee seats, not just full committees
```

Default (no flag) resolves the name first and picks the right trace.
When a name matches more than one kind of entity, present the choices
rather than guessing.

## Step 1 — Resolve the entity

Never assume what a name refers to. Resolve before tracing.

- `fec_search_committees` — is it a registered political committee? Note
  the `designation` returned: `D` is a leadership PAC, `J` a joint
  fundraising committee, `P` a principal campaign committee. That code
  decides which pattern applies.
- `lda_search_registrants` — is it a lobbying firm?
- `congress_search_legislators` — is it a sitting member?
- A company that is none of the above is still traceable, through what
  its employees give. There is no registry to resolve against: employer
  is free text typed on each contribution, so the name is the key. Try
  the obvious variants before concluding there is nothing there.

If several match, list them with their identifiers and ask which is
meant. Two committees can share a name; picking silently produces a
confident answer about the wrong entity.

A single name can be several of these at once — a company with a
corporate PAC, a lobbying registrant, and employees who give
individually are three separate traces of one organisation. Run each
and report them separately; they are different money.

## Step 2 — Trace, by entity type

### A PAC or political committee

0. `pattern_committee_backers` — who funds it. Run this before anything
   about its spending: a committee's money has a source, and for an
   outside group that source is usually the more informative end.
   `single_backer_dominant` is the flag to read.
1. `pattern_candidate_support_ratio` — run this next, because it decides
   whether the rest of the trace is worth reading. It reports what share
   of the committee's spending reaches candidates and party committees at
   all. A committee spending almost everything on its own operations has
   little downstream money to trace, and that is the finding. A low share
   is lawful and often correct for an independent-expenditure or
   issue-advocacy group, so report it as the factual split it is, never
   as a "scam PAC" — no law sets a required ratio. Cycles below the
   receipts floor are returned unscored; do not read those as zero.
2. `pattern_industry_concentration` — the primary view. Aggregates
   outbound giving by the congressional committees its recipients sit
   on. The join is identifier-based end to end, so what it attributes is
   solid.
3. Read `stats.unattributed_amount` and `stats.unattributed_recipients`
   before reporting anything. This is the number that decides whether
   the headline is meaningful. If unattributed is a large share of
   `to_other_committees`, the direct view is a minority of the story and
   must not be presented as the whole.
4. For each unattributed recipient, check its designation with
   `fec_search_committees` or `fec_get_committee` and follow it:
   - designation `D` (leadership PAC) → `pattern_leadership_pac_transfers`
   - designation `J` (joint fundraising) → `pattern_jfc_obscuring`
   - party committees (RNC, DNC, NRSC, DCCC and the like) → report as
     party-directed. Do not attempt to attribute party spending to
     individual members; the committee allocates it later by its own
     process and the link is not in this data.
5. With `--deep`, follow one further hop from those results — and follow
   it as **routes, not amounts**. See the depth rule below.

### A lobbying firm (registrant)

1. `pattern_lobbying_money_to_committee_seats` — where the firm's LD-203
   political giving lands, by recipient committee seat.
2. `pattern_lobbyist_contribution_corroboration` — checks those LD-203
   contributions against FEC's independently filed record. Corroboration
   across two separately filed sources is a credibility signal; absence
   is not evidence of wrongdoing, since small contributions fall below
   FEC's itemization threshold.
3. `pattern_revolving_door` — which congressional committees the firm's
   own people came from, via the covered positions they disclose. This
   is the committee-level view that the lobbying side otherwise lacks,
   and it reaches it through the lobbyists' prior employment rather than
   through anything about the client. Read the two routes it labels
   separately: **served the committee** is a direct tie, while **staffed
   a sitting member** credits someone to whatever seats that member holds
   today, which need not be the seats they held at the time.
4. `lda_search_filings` for what the firm actually lobbies on. Report
   issue areas and the chambers named — and note the limit below: LDA
   records the chamber, never the committee, so what a firm *lobbies*
   stays chamber-level even when `pattern_revolving_door` names the
   committees its staff *came from*. Those are different claims and must
   not be merged into one sentence.
5. `lda_search_lobbyists` for who works there.

### A member of Congress

1. `congress_search_legislators` → bioguide plus FEC candidate IDs.
2. `congress_get_legislator_committees` — their seats, and any chair or
   ranking-member title. Titles matter more than membership.
3. `fec_get_candidate_committees` → their committees; then
   `fec_search_contributions` for who funds them, and
   `fec_get_candidate_totals` for scale.
4. `fec_search_independent_expenditures` with `candidate_id` — money
   spent supporting or opposing them by committees they do not control.
   Use `support_oppose_indicator` and report the two separately; they
   mean opposite things.
5. `pattern_committee_backers` on **each outside spender** found above.
   This is the hop that usually matters most and the one easiest to
   skip: an outside group running advertisements is spending somebody's
   money, and the advertisement never says whose. It is what turns "a
   super PAC spent $16m supporting them" into "a super PAC backed by X
   spent $16m supporting them" — two disclosed facts, and the second is
   often the story.

   Read `single_backer_dominant`. Where one backer supplies most of the
   funding, describe the committee as that backer's vehicle; where the
   funding is spread, do not. **Never add the two hops together** — what
   a backer gave and what the committee spent are different sums and the
   receipts are commingled.
6. `pattern_common_vendor_overlap` — vendors paid by both the campaign
   and the outside groups spending to elect it. Read the share fields,
   not the raw list: every committee buys from the same airlines and
   shipping companies, and those overlaps mean nothing. A consultancy
   taking real money from both sides is the line worth a question.
   **Never call an overlap coordination** — that turns on whether
   information passed between them, which no filing discloses.

### A company or employer

For an organisation whose people give as individuals, rather than
through a PAC it controls.

1. `pattern_employer_contribution_clusters` — colleagues at one employer
   giving to the same recipient inside a short window. Two readings of
   the same output:
   - **The concentration view** (`stats.recipient_concentration`) — which
     candidates the workforce's money reaches in aggregate. Safe to
     report plainly.
   - **The clusters** — the shape of a reimbursement scheme, where a
     company funds contributions made in employees' names. It is equally
     the shape of a lawful workplace fundraising drive and nothing in the
     data separates them. Report a cluster as a lead to check, never as a
     finding. Clusters flagged `amounts_identical` are the ones worth
     asking about, since a reimbursement tends to be a fixed sum per
     person, but that is suggestive and not proof.
2. Check whether the company also has a corporate PAC
   (`fec_search_committees`) and trace that separately as a PAC. Employee
   giving and PAC giving are different money and must not be summed.
3. `lda_search_registrants` and `lda_search_clients` — whether it lobbies
   directly or retains firms. If it does, the firm trace applies too.

Employer is self-reported free text, so anything here is a floor:
spelling variants, subsidiaries and blank fields all lose contributions
that really belong to the same organisation.

### Dark money (any entity type)

Money that never appears in FEC or LDA filings at all is the largest
blind spot in everything above. 501(c)(4) social welfare organizations
do not disclose donors, but they do file Form 990s showing spending.

- `propublica_search` with `c_code=4` — find 501(c)(4) organizations by
  name, including ones sharing a name or address with the entity being
  traced.
- `propublica_get_organization` — the filing history and financials.

There is no pattern for this yet, so this is manual and the link is
weaker than anything above. **A name resemblance between a PAC and a
501(c)(4) is not a proven relationship.** Report it as a lead worth
checking, never as an established connection, and say what would confirm
it — shared officers, shared address, or a disclosed transfer.

## Depth: why this is not an N-deep money graph

Money entering an intermediary committee is **commingled**. A leadership
PAC receiving $5,000 from one donor holds it in a single account
alongside everything else it raised; when it later gives $10,000 to a
candidate, no part of that $10,000 is traceable to any particular
donor. This is categorically unlike ownership, where a chain of
subsidiaries preserves a real claim through every link and is worth
traversing to depth.

So the rule is not a tuned depth limit — it is a change of claim at the
first commingled hop:

- **Amounts stop at hop one.** Report what an entity gave directly to
  committees, and what it gave to each intermediary. Never compute or
  present a figure "flowing through" an intermediary to a member. There
  is no such number, and inventing one attributes money to a named
  person on arithmetic that does not hold.
- **Routes may go further.** "This PAC funds a leadership PAC, which
  funds these members" is true and useful. State it as connectivity —
  who is linked to whom, by what route — with no dollar figure attached
  to the far end.
- Two route hops is the practical limit for a readable report, not a
  correctness boundary. Beyond that, nearly every large donor connects
  to nearly every member through some path, and the finding stops
  discriminating.

## Step 3 — Reconcile before reporting

The patterns overlap. Reconcile rather than concatenating them.

- **Do not double-count.** A member reached both directly and through a
  leadership PAC is one relationship via two routes. Report the routes;
  do not sum them into a single inflated figure.
- **Keep direct and indirect separate.** They carry different evidential
  weight. A direct contribution is a disclosed fact; an amount inferred
  through two hops is a chain where each link needs its own support.
- **Lead with the attribution rate.** State what share of the money was
  traced to sitting members before stating which committees it reached.
  A concentration figure computed over a minority of the money is
  misleading without it.

## Report format

```
## Follow: [entity name]

**Entity** — [what it resolved to, with identifier and designation]
**Scope** — [cycle; note that committee rosters are always current]

### Money traced
| Route | Amount | Attributed to members |
|---|---|---|
| Direct to candidate committees | $X | yes |
| Via leadership PACs | $X | one hop |
| Via joint fundraising committees | $X | one hop |
| To party committees | $X | not attributable |
| Vendor / operating spending | $X | not applicable |

**Attribution rate** — $X of $Y (Z%) reached identifiable sitting members.

### Committee exposure
[committees by amount; mark chairs and ranking members explicitly —
 a chair's committee relationship is not equivalent to a junior member's]

### Personnel ties
[committees the entity's people previously worked for, if a firm was
 traced. Label each as served-the-committee or staffed-a-member; they
 are not the same strength of tie]

### Routes worth noting
[intermediaries actually followed, and what they resolved to]

### Leads, not findings
[contribution clusters, shared vendors, name-resemblant 501(c)(4)s.
 Everything here is a question to check, and must be stated as one.
 Say what would confirm each]

### Not traced
[unattributed recipients and why — party committees, non-incumbents,
 members no longer in office]
```

## Standard caveats (include in every report)

- Contributing to a member, or to the committee overseeing your
  industry, is lawful and routine. The signal is concentration and
  structure, not the existence of a contribution.
- Committee assignments are **current only**. Giving from an earlier
  cycle is matched against today's rosters, and recipients who have left
  office do not resolve at all.
- A dollar is counted once per committee its recipient sits on, so
  committee totals sum to more than the money in. That is the intended
  reading — exposure per committee, not a partition of the dollars.
- **LDA does not record which committee a client lobbies**, only the
  chamber. Never state or imply that a firm lobbied a specific committee;
  that link is not in the data. `pattern_revolving_door` names committees
  a firm's *staff previously worked for*, which is a disclosed fact and a
  different claim — keep the two in separate sentences.
- Revolving-door coverage is a floor twice over: most lobbyists disclose
  no covered position at all, and references to members who have left
  office do not resolve against current rosters. Absence of a tie is not
  evidence there is none.
- **A backer is not the spender.** "Backed by X" describes where a
  committee's money came from. It does not license saying X spent the
  money, X directed the advertisements, or any part of what the
  committee spent was X's contribution — receipts are commingled and the
  two hops are separate disclosed facts.
- A shared vendor is not coordination, and a low candidate-support ratio
  is not misconduct. Both are lawful arrangements this tool can see;
  neither carries the conclusion its shape suggests.
- A contribution cluster among colleagues is not evidence of
  reimbursement. Lawful bundling produces the identical shape and is far
  more common.
- Money reaching a member through a party committee is not attributable
  to that member from this data.
- Intermediary committees commingle funds. A route from a donor to a
  member through one is a real connection, but no dollar amount can be
  attributed along it. Report the route; never the sum.
- Name matching on the lobbying side is approximate; the FEC-identifier
  side is exact. Say which was used when it matters.

## Notes

- **`graph_connections` composes all of this into one graph** and answers
  "how is this entity connected to that one, and by how many separate
  routes?". Give it any combination of identifiers; it runs the patterns
  that apply, traces the funders of any outside spenders it finds, and
  can write a self-contained interactive HTML page with `export_path`.
  Reach for it when the question is about a relationship between two
  named entities rather than about one entity's activity.
- Several independent routes between one pair is the finding; a single
  route is ordinary. Check every intermediary before treating a route as
  evidence — two committees buying from the same airline are not
  connected in any meaningful sense, and the graph flags those.
- Run `pattern_*` tools before raw source tools. The patterns already
  compose several calls and handle the pagination and filtering.
- Every pattern returns `warnings` — surface them; they carry the
  interpretive limits for that specific result.
- Every result also carries `provenance`: what the literature says about
  that pattern, with each citation marked as supporting, limiting or
  contradicting it. Use it when a reader is deciding how much weight a
  finding bears. Two things there change what you should write:
  a pattern reporting `PROPOSED` with no citations is ungrounded and must
  not be presented as established, and one reporting `CONTESTED` has a
  work arguing against it — read the citation before relying on it.
  `pattern_provenance` gives the same registry directly, including
  patterns considered and rejected, and is the right tool when asked why
  packed does or does not do something.
- Cross-tool: for the corporate ownership behind a donor, use the
  `sift` tools if present. That is where an entity's structure lives;
  `packed` covers what it spends.
