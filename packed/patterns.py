"""Cross-source detection patterns.

Unlike Sift's pattern system (a generic condition engine evaluated
against a unified traversal graph — see sift/pattern_matcher.py),
packed has no cross-source graph/traversal layer yet. Each pattern
here queries the relevant clients directly and applies domain-specific
matching logic. A full generic rule engine like Sift's still isn't
warranted — pattern 1 has genuinely different structure from patterns
2/3. But patterns 2 and 3 (leadership PAC / JFC) turned out to share
the exact same "resolve a committee, trace money in via Schedule A,
trace money out via Schedule B" shape, so that shared logic is
extracted into `_trace_committee_money_flow()` rather than duplicated
— the trigger for revisiting "bespoke per pattern" that this docstring
used to flag as a someday-maybe. See CLAUDE.md for the fuller reasoning.

Pattern 1: lobbyist_contribution_corroboration. LD-203 requires
registered lobbyists/registrants to disclose their own federal
political contributions. FEC's Schedule A independently captures
itemized contributions reported by the receiving committee.
Corroboration across both sources — same contributor, same committee,
matching amount/date — is a credibility signal, not a red flag by
itself. A contribution reported to LDA but not found in FEC could mean
it fell under FEC's itemization threshold, a name-matching gap, or is
worth a closer look — absence alone proves nothing.

Known limitations, confirmed against live data (2026-08-12):
- LD-203's "payee_name" field is not always the actual committee name
  — it sometimes holds the contributor's own name instead (a real
  data-quality quirk in the source, not a bug here). Those items will
  correctly show as unconfirmed since there's nothing reliable to
  match against.
- Name matching is approximate (shared non-generic words, not exact
  identity) — a match against e.g. a candidate's joint fundraising
  committee vs. their principal campaign committee is a plausible
  false positive. Treat "corroborated" as "a plausible match found,"
  not "confirmed to be the identical committee."

Pattern 2: leadership_pac_transfers. A leadership PAC lets a member of
Congress (or candidate) raise and give money separately from their own
campaign committee. Tracing both legs of its flow — who funds it
(Schedule A contributions in), and which candidate committees it sends
money to (Schedule B disbursements out, where recipient_committee_id
is set) — surfaces the "candidate-to-candidate via leadership PAC"
routing pattern directly, without requiring speculative conclusions
about intent. Confirmed live (2026-08-12) that FEC committee
designation code "D" = Leadership PAC, and that recipient_committee_id
is reliably populated on Schedule B rows only when the recipient is
itself a registered committee (vendor/operating payments leave it
null) — this is what distinguishes a transfer from ordinary spending.

Pattern 3: jfc_obscuring. Same money-in/money-out shape as pattern 2,
scoped to designation "J" (Joint Fundraising Committee) instead of "D".
A JFC pools multiple committees' separate contribution limits, letting
a single donor write one check larger than any participant could
legally accept directly — the JFC then splits proceeds among
participants. That splitting is exactly what can obscure how much a
donor ultimately supports any one candidate.

Scoping note from live research (2026-08-12): FEC's Schedule A does
expose a real allocation-disclosure mechanism for this — memo_code/
memo_text entries showing how a bundled contribution was split among
participants (confirmed these exist on live JFC data, e.g. Collins
Victory Committee C00692897). But the semantics weren't confirmed
precisely enough to build on with confidence (which memo_code values
mean "this is a JFC split" specifically vs. other memo uses — e.g.
observed code "X" on both apparent redesignations and repeat entries
from a single PAC, without a verified data dictionary to disambiguate
from training knowledge alone). Rather than encode an uncertain
interpretation, this pattern reuses the same verified money-in/
money-out tracing as pattern 2. Revisit if FEC's memo field semantics
get properly confirmed — that would let this pattern show the actual
per-participant split of a single bundled contribution, not just
aggregate flow.

Pattern 4: lobbying_money_to_committee_seats. Aggregates a lobbying
registrant's LD-203 political giving by the congressional committees
its recipients sit on, joining LDA money data to congress-legislators
committee rosters.

**This is deliberately NOT the "dual role" pattern the roadmap
originally specified**, and the reason is a hard data limit rather
than a shortcut. Dual role was defined as "a lobbyist for client X who
also funds a member sitting on a committee X lobbies before" — which
requires knowing which committee a client lobbies. LDA does not record
that. Its `government_entities` field was confirmed live (2026-08-12)
to have 257 possible values, of which **zero are congressional
committees**; the only congressional entries are the chamber-level
"HOUSE OF REPRESENTATIVES" and "SENATE", which virtually every filing
names, making a chamber-level version vacuous.

Two alternatives were evaluated and rejected:
- The `covered_position` field (a lobbyist's prior government job)
  would give a genuine revolving-door signal, but too few of its values
  name a committee to build a committee-level pattern on, and it is
  inconsistent free text ("Sr. Leg. Asst. & Leg. Dir., Rep. Stefanik
  (2/23-1/25)", "CoS, Sen Leahy, 2005-11").

  Corrected 2026-08-15: the "~8% populated" figure once recorded here
  was wrong as stated. Over 3,980 lobbyist-activity rows sampled across
  the 2024 corpus, the field is populated for 30.8% of unique
  lobbyists; ~8% is the share whose text names a *committee*, which is
  what this pattern would have needed. But 67% of populated values name
  a *member*, and a named member resolves to committee seats through
  the congress-legislators index this module already builds. That route
  was never evaluated and is a live pattern candidate — see
  `revolving_door` in patterns/PATTERNS.yaml.
- Mapping LDA general issue codes (TAX, HCR, ENG) to committees of
  jurisdiction would be an editorial construction of ours, not source
  data, so a "match" would reflect our mapping rather than a disclosed
  fact.

What IS fully supported is the recipient side: LD-203's `honoree_name`
field carries clean legislator names ("Sen. Marsha Blackburn"), and
those resolve to committee seats via congress-legislators. So this
pattern answers "whose committee seats does this firm's money land on"
without asserting anything about what the firm lobbies before.

Measured against 141 real LD-203 honoree entries for one firm: 113
(80%) resolved to exactly one sitting legislator, 0 ambiguous. The
remaining 28 are legitimately unresolvable and fall into clear
buckets — party committees and PACs (DCCC, NRSC, the firm's own PAC),
members who have since left office, non-incumbent candidates, a typo
in the source data ("Sen. Adam Schii"), and non-prefix nicknames
("Elizabeth Fletcher" for Lizzie Fletcher). Resolution stats are
returned in the output so a caller can see the denominator rather than
trusting a total blindly.

Two interpretive caveats are surfaced as warnings on every result:
committee rosters are current-only (so an older filing_year is being
matched against today's committees), and a single contribution is
counted once per committee its recipient sits on — meaning committee
totals intentionally sum to more than the contribution total.

Pattern 5: industry_concentration. Aggregates a PAC's outbound giving
by the congressional committees its recipients sit on — the question
being whether a donor's money concentrates on the members who write
the rules governing that donor.

Shares its aggregation with pattern 4 via ``_CommitteeSeatTally``; the
two differ only in how a recipient is resolved. That difference matters
for how much to trust each: pattern 4 matches LD-203 honoree names
against legislator names, which is fuzzy and loses a tail. This one
follows identifiers end to end — FEC Schedule B gives a
``recipient_committee_id``, the recipient committee carries
``candidate_ids``, and those FEC candidate IDs join to
congress-legislators' own ``fec`` field, which reaches a bioguide ID and
its committee seats. No name matching anywhere in that chain.

What it cannot see, and reports rather than hides: money sent to a
committee that has no candidate of its own — a leadership PAC, a party
committee, a joint fundraising committee — reaches a member through a
further hop this pattern does not follow. Those amounts are surfaced as
``unattributed_recipients`` instead of being silently dropped or wrongly
attributed. Patterns 2 and 3 exist to trace exactly those hops, so the
three compose: run this to see direct exposure, then follow the
intermediaries separately.

Ordinary vendor and operating spending is excluded by the same test
pattern 2 uses — a Schedule B row with no ``recipient_committee_id`` is
not a transfer to a committee.

Pattern 6: revolving_door. Groups a lobbying operation's people by the
congressional committees they disclose having previously worked for.

This is what became of the "dual role" pattern that pattern 4 above
records as unbuildable. That assessment was right about the route it
tried and wrong about the field: it asked which committee a client
lobbies *before*, which LDA genuinely does not record, and then
dismissed ``covered_position`` on a population figure that turned out to
describe only the subset naming a committee. Most disclosures name a
*member* instead, and a member is exactly what the congress-legislators
index in this module turns into committee seats.

So the question is asked from the other end — not which committee the
client lobbies, but which committees the client's lobbyists came from.
Both are ties between a firm and a committee; only the second is
disclosed.

Two routes reach a committee and the result labels which was used,
because they are not equally strong. "Served the committee" is the
filer naming the committee itself. "Staffed a sitting member" credits a
lobbyist to every committee that member sits on today, which is a tie to
a person and inherits whatever seats they currently hold.

Parsing lives in ``packed/covered_position.py`` and is built to propose
rather than decide: it extracts generously, every candidate is resolved
against congress-legislators, and anything not matching exactly one
current entity is reported unresolved instead of guessed. A phrase
naming no chamber ("Commerce Committee") names two real committees and
is reported ambiguous rather than resolved by picking one.

What it cannot see, reported as warnings on every result: most lobbyists
disclose no covered position at all, so a firm's real count is higher
than any result here; and references to members who have left office do
not resolve against a current-only roster, which is the single largest
category of what gets dropped.

Pattern 7: employer_contribution_clusters. People sharing an employer
who give to one recipient inside a short window — the shape of a
reimbursement scheme, in which a company funds contributions made in
employees' names.

It is equally the shape of a lawful workplace fundraising drive, and
Schedule A holds nothing that separates them. So the output is a lead,
and the description and warnings say so rather than leaving a reader to
infer it. The one available discriminator is amount uniformity: a
reimbursement is a fixed sum handed to each person, while colleagues
giving independently rarely match to the dollar. Clusters where every
donor gave an identical amount are flagged; that is suggestive, not
decisive.

Named for the shape rather than the mechanism. It began as
"conduit_contribution_cluster" and was renamed before being built,
because "conduit" asserts exactly the thing the data cannot establish.

Two parameters exist because a first attempt found nothing at all, and
both were assumptions rather than measurements:

- ``min_donors`` defaults to 2. Requiring three erased the case this
  pattern is grounded in — the scheme in MUR 8363 ran two donors at a
  time.
- Pass-through committees are excluded. A contribution routed through
  one names the conduit as recipient rather than the campaign, and on
  the employer checked they supplied roughly three quarters of the rows
  as small recurring donations, which drown the signal.

Verified against that matter: the FEC conciliated with Calspan
Corporation over contributions reimbursed with corporate funds, and the
top cluster this returns for that employer is four donors to one
campaign on a single day, comprising every individual the matter names.

Pattern 8: common_vendor_overlap. Vendors paid by both a candidate's
campaign and an outside group spending independently to elect them.

The schedule split is the part that had to be measured rather than
assumed, and it is why "intersect the disbursements" would not have
worked. An independent-expenditure committee reports its media buys on
Schedule E, under a payee field of its own, and carries almost nothing
on Schedule B — one such committee showed a single Schedule B row
against millions in reported expenditures. So the campaign side reads
Schedule B and the outside side reads E and B together.

Coordination is a legal conclusion resting on facts no filing
discloses, and sharing a vendor is lawful where the firm firewalls its
teams. This reports the overlap and what each side paid.

A raw overlap list is dominated by commodity vendors, because every
committee buys from the same airlines, rideshare and shipping
companies. Each shared vendor therefore carries its share of each
side's spending, which is what separates a consultancy taking real
money from both from an airline taking a rounding error. Those shares
are computed over the spending actually retrieved rather than a
committee's full ledger, since pagination is capped — the field names
say "sampled" so the denominator cannot be mistaken.

Name matching is onoma's, with one guard. A vendor name that reduces to
a single short token matches far too much: "AT&T" normalises to the
token "at", which onoma then finds inside "MILLER'S SUPPLIES AT WORK".
Requiring a shared token of real length forces such names to match
exactly instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import onoma

from .lda_client import LDAClient
from .openfec_client import OpenFECClient
from .congress_legislators_client import CongressLegislatorsClient
from .errors import ServiceTracker, api_call
from . import covered_position as _covered_position
from . import provenance as _provenance

AMOUNT_TOLERANCE = 1.00  # dollars
DATE_WINDOW_DAYS = 60
FEC_LOOKUP_PAGE_SIZE = 100  # a single contributor can easily exceed the default 20/page

@dataclass
class PatternMatch:
    pattern_name: str
    title: str
    risk_level: str
    status: str
    description: str
    findings: list[dict[str, Any]]
    stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def provenance(self) -> dict[str, Any] | None:
        """What the literature says about this pattern.

        Attached to the result rather than left to a separate lookup, so
        a finding travels with its grounding — including the absence of
        grounding, which is itself worth reporting.
        """
        p = _provenance.for_pattern(self.pattern_name)
        return p.to_dict() if p else None


def _committee_names_match(a: str | None, b: str | None) -> bool:
    """Do two committee names plausibly refer to the same committee?

    Delegated to onoma, which handles the political entity vocabulary
    (PAC, political action committee, victory fund) and the distinction
    between identifying words and filler — sharing "for" and a surname
    is not evidence.

    Note what this cannot decide: a candidate's joint fundraising
    committee and their principal campaign committee share a surname and
    nothing else distinctive, which is structurally identical to a
    genuine abbreviation match. onoma reports that as a weak match
    rather than pretending to separate them. Callers here corroborate
    with amount and date, which is what makes the weak case usable.
    """
    return onoma.same_org(a or "", b or "")


def _contributor_name(filing: dict[str, Any]) -> str | None:
    """Extract the actual contributor's name from an LD-203 filing.

    If a specific lobbyist filed it, that's the contributor. Otherwise
    (filer_type "organization"), the registrant's listed contact made
    the contribution.
    """
    lobbyist = filing.get("lobbyist")
    if lobbyist:
        parts = [lobbyist.get("first_name"), lobbyist.get("last_name")]
        name = " ".join(p for p in parts if p)
        if name:
            return name
    registrant = filing.get("registrant") or {}
    return registrant.get("contact_name")


def _two_year_period(date_str: str | None) -> int | None:
    """FEC's two_year_transaction_period is the even year of the cycle."""
    if not date_str or len(date_str) < 4:
        return None
    try:
        year = int(date_str[:4])
    except ValueError:
        return None
    return year if year % 2 == 0 else year + 1


def _find_fec_match(
    fec_results: list[dict[str, Any]],
    payee_name: str,
    amount: float,
    date: str,
) -> dict[str, Any] | None:
    from datetime import datetime

    try:
        target_date = datetime.fromisoformat(date[:10])
    except (ValueError, TypeError):
        target_date = None

    for rec in fec_results:
        committee = rec.get("committee") or {}
        committee_name = committee.get("name") or rec.get("committee_name")
        if not _committee_names_match(payee_name, committee_name):
            continue

        rec_amount = rec.get("contribution_receipt_amount")
        if rec_amount is None or abs(rec_amount - amount) > AMOUNT_TOLERANCE:
            continue

        if target_date is not None:
            rec_date = rec.get("contribution_receipt_date")
            try:
                rec_dt = datetime.fromisoformat((rec_date or "")[:10])
                if abs((rec_dt - target_date).days) > DATE_WINDOW_DAYS:
                    continue
            except (ValueError, TypeError):
                pass

        return rec

    return None


async def detect_lobbyist_contribution_corroboration(
    lda_client: LDAClient,
    fec_client: OpenFECClient,
    lobbyist_name: str | None = None,
    registrant_name: str | None = None,
    filing_year: int | None = None,
) -> PatternMatch:
    """Cross-reference LD-203 lobbyist contributions against FEC
    Schedule A itemized contributions for the same person.
    """
    tracker = ServiceTracker()
    findings: list[dict[str, Any]] = []

    lda_result = await api_call(
        tracker, "LDA", "/contributions/",
        lambda: lda_client.search_contributions(
            lobbyist_name=lobbyist_name,
            registrant_name=registrant_name,
            filing_year=filing_year,
            page_size=25,
        ),
    )

    if lda_result is None:
        return PatternMatch(
            pattern_name="lobbyist_contribution_corroboration",
            title="Lobbyist Contribution Cross-Source Corroboration",
            risk_level="INFO",
            status="ERROR",
            description="Could not fetch LD-203 data.",
            findings=[],
            warnings=tracker.warnings,
        )

    # Cache FEC lookups per (contributor, cycle) — multiple contribution
    # items often share the same contributor and cycle.
    fec_cache: dict[tuple[str, int | None], list[dict[str, Any]]] = {}

    for filing in lda_result.get("results", []):
        contributor = _contributor_name(filing)
        if not contributor:
            continue

        for item in filing.get("contribution_items", []):
            payee = item.get("payee_name")
            amount_str = item.get("amount")
            date = item.get("date")
            if not payee or amount_str is None:
                continue
            try:
                amount = float(amount_str)
            except (TypeError, ValueError):
                continue

            cycle = _two_year_period(date)
            cache_key = (contributor, cycle)
            if cache_key not in fec_cache:
                fec_result = await api_call(
                    tracker, "OpenFEC", "/schedules/schedule_a/",
                    lambda c=contributor, cy=cycle: fec_client.search_contributions(
                        contributor_name=c,
                        two_year_transaction_period=cy,
                        per_page=FEC_LOOKUP_PAGE_SIZE,
                    ),
                )
                fec_cache[cache_key] = (fec_result or {}).get("results", [])

            match = _find_fec_match(fec_cache[cache_key], payee, amount, date or "")

            findings.append({
                "contributor": contributor,
                "lda_filing_uuid": filing.get("filing_uuid"),
                "lda_registrant": (filing.get("registrant") or {}).get("name"),
                "lda_payee": payee,
                "lda_honoree": item.get("honoree_name"),
                "lda_amount": amount,
                "lda_date": date,
                "corroborated": match is not None,
                "fec_match": {
                    "committee_id": match.get("committee_id"),
                    "committee_name": (match.get("committee") or {}).get("name"),
                    "amount": match.get("contribution_receipt_amount"),
                    "date": match.get("contribution_receipt_date"),
                    "pdf_url": match.get("pdf_url"),
                } if match else None,
            })

    corroborated = sum(1 for f in findings if f["corroborated"])

    return PatternMatch(
        pattern_name="lobbyist_contribution_corroboration",
        title="Lobbyist Contribution Cross-Source Corroboration",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Cross-references LD-203 lobbyist political contributions "
            "against FEC Schedule A itemized receipts. Corroboration is "
            "a credibility signal, not a red flag — an unconfirmed "
            "contribution may simply fall under FEC's itemization "
            "threshold or reflect a name-matching gap."
        ),
        findings=findings,
        stats={
            "total_contribution_items": len(findings),
            "corroborated": corroborated,
            "unconfirmed": len(findings) - corroborated,
        },
        warnings=tracker.warnings,
    )


LEADERSHIP_PAC_DESIGNATION = "D"
JFC_DESIGNATION = "J"


async def _trace_committee_money_flow(
    fec_client: OpenFECClient,
    *,
    pattern_name: str,
    title: str,
    description: str,
    expected_designation: str,
    designation_label: str,
    committee_id: str | None,
    committee_name: str | None,
    two_year_transaction_period: int | None,
    min_transfer_amount: float,
) -> PatternMatch:
    """Shared logic for patterns 2 and 3: resolve a committee (by ID, or
    by name scoped to the expected designation), then trace money in
    (top Schedule A contributors) and money out (Schedule B
    disbursements that went to another registered committee, not
    ordinary vendor spending). Leadership PACs and joint fundraising
    committees share this exact shape — extracted here once the second
    pattern needed it, per the module docstring's stated trigger for
    revisiting the no-generic-engine decision. Still not a generic
    condition engine — pattern 1 has genuinely different structure and
    isn't part of this.
    """
    tracker = ServiceTracker()

    if committee_id is None:
        if not committee_name:
            return PatternMatch(
                pattern_name=pattern_name, title=title, risk_level="INFO",
                status="ERROR", description="committee_id or committee_name is required.",
                findings=[],
            )
        search_result = await api_call(
            tracker, "OpenFEC", "/committees/",
            lambda: fec_client.search_committees(
                q=committee_name, designation=expected_designation,
            ),
        )
        results = (search_result or {}).get("results", [])
        if not results:
            return PatternMatch(
                pattern_name=pattern_name, title=title, risk_level="INFO",
                status="ERROR",
                description=f"No {designation_label} found matching {committee_name!r}.",
                findings=[], warnings=tracker.warnings,
            )
        committee_id = results[0]["committee_id"]

    committee_detail = await api_call(
        tracker, "OpenFEC", "/committee/{id}/",
        lambda: fec_client.get_committee(committee_id),
    )
    committee_record = ((committee_detail or {}).get("results") or [{}])[0]
    committee_display_name = committee_record.get("name")
    extra_warnings: list[str] = []
    if committee_record.get("designation") != expected_designation:
        extra_warnings.append(
            f"{committee_id} has designation "
            f"{committee_record.get('designation_full', committee_record.get('designation'))!r}, "
            f"not {designation_label} — results may not reflect a "
            f"{designation_label.lower()}'s flow."
        )

    contributions = await api_call(
        tracker, "OpenFEC", "/schedules/schedule_a/",
        lambda: fec_client.search_contributions(
            committee_id=committee_id,
            two_year_transaction_period=two_year_transaction_period,
            per_page=FEC_LOOKUP_PAGE_SIZE,
        ),
    )
    contributors_in = (contributions or {}).get("results", [])
    top_contributors = sorted(
        contributors_in,
        key=lambda c: c.get("contribution_receipt_amount") or 0,
        reverse=True,
    )[:10]

    disbursements = await api_call(
        tracker, "OpenFEC", "/schedules/schedule_b/",
        lambda: fec_client.search_disbursements(
            committee_id=committee_id,
            two_year_transaction_period=two_year_transaction_period,
            per_page=FEC_LOOKUP_PAGE_SIZE,
        ),
    )
    all_disbursements = (disbursements or {}).get("results", [])
    transfers = [
        d for d in all_disbursements
        if d.get("recipient_committee_id")
        and (d.get("disbursement_amount") or 0) >= min_transfer_amount
    ]

    recipient_totals: dict[str, dict[str, Any]] = {}
    for d in transfers:
        rid = d["recipient_committee_id"]
        entry = recipient_totals.setdefault(rid, {
            "recipient_committee_id": rid,
            "recipient_name": (d.get("recipient_committee") or {}).get("name")
                or d.get("recipient_name"),
            "total_amount": 0.0,
            "transaction_count": 0,
        })
        entry["total_amount"] += d.get("disbursement_amount") or 0
        entry["transaction_count"] += 1

    findings = sorted(
        recipient_totals.values(), key=lambda r: r["total_amount"], reverse=True,
    )

    return PatternMatch(
        pattern_name=pattern_name,
        title=title,
        risk_level="INFO",
        status="ACTIVE",
        description=description,
        findings=findings,
        stats={
            "committee_id": committee_id,
            "committee_name": committee_display_name,
            "top_contributors": [
                {
                    "contributor_name": c.get("contributor_name"),
                    "amount": c.get("contribution_receipt_amount"),
                    "date": c.get("contribution_receipt_date"),
                }
                for c in top_contributors
            ],
            "total_transferred": sum(r["total_amount"] for r in findings),
            "distinct_recipient_committees": len(findings),
        },
        warnings=extra_warnings + tracker.warnings,
    )


async def detect_leadership_pac_transfers(
    fec_client: OpenFECClient,
    committee_id: str | None = None,
    committee_name: str | None = None,
    two_year_transaction_period: int | None = None,
    min_transfer_amount: float = 0.0,
) -> PatternMatch:
    """Trace a leadership PAC's money flow: who funds it, and which
    committees it transfers money to. See module docstring, Pattern 2.
    """
    return await _trace_committee_money_flow(
        fec_client,
        pattern_name="leadership_pac_transfers",
        title="Leadership PAC Fund Routing",
        description=(
            "Traces a leadership PAC's money flow: top contributors "
            "funding it, and which committees it transfers money to. "
            "A transfer to a candidate committee isn't inherently "
            "improper — leadership PACs exist for exactly this purpose "
            "— but the pattern surfaces who's funding the PAC and who "
            "it's funding in turn."
        ),
        expected_designation=LEADERSHIP_PAC_DESIGNATION,
        designation_label="Leadership PAC",
        committee_id=committee_id,
        committee_name=committee_name,
        two_year_transaction_period=two_year_transaction_period,
        min_transfer_amount=min_transfer_amount,
    )


async def detect_jfc_obscuring(
    fec_client: OpenFECClient,
    committee_id: str | None = None,
    committee_name: str | None = None,
    two_year_transaction_period: int | None = None,
    min_transfer_amount: float = 0.0,
) -> PatternMatch:
    """Trace a joint fundraising committee's money flow: who funds it,
    and which participant committees it splits proceeds to. See module
    docstring, Pattern 3.
    """
    return await _trace_committee_money_flow(
        fec_client,
        pattern_name="jfc_obscuring",
        title="Joint Fundraising Committee Fund Routing",
        description=(
            "Traces a joint fundraising committee's money flow: top "
            "contributors funding it, and which participant committees "
            "it splits proceeds to. A JFC lets a donor write one large "
            "check that gets divided across multiple committees, each "
            "within its own legal limit — which is exactly what can "
            "obscure how much a donor is ultimately supporting any one "
            "candidate. Splitting isn't itself improper; the pattern "
            "surfaces the flow so the real per-candidate scale is visible."
        ),
        expected_designation=JFC_DESIGNATION,
        designation_label="Joint Fundraising Committee",
        committee_id=committee_id,
        committee_name=committee_name,
        two_year_transaction_period=two_year_transaction_period,
        min_transfer_amount=min_transfer_amount,
    )


class _CommitteeSeatTally:
    """Accumulates money by the congressional committees its recipients sit on.

    Shared by the patterns that answer "whose committee seats does this
    funder's money land on". They differ only in how a recipient is
    resolved — one matches LD-203 honoree names, the other follows FEC
    committee -> candidate IDs — but the aggregation is identical, so it
    lives here rather than being written twice.

    A single contribution is credited once per committee the recipient
    sits on. Committee totals therefore sum to more than the money in,
    which is intended: the question is exposure per committee, not a
    partition of the dollars.
    """

    def __init__(self, include_subcommittees: bool = False):
        self._include_subcommittees = include_subcommittees
        self._totals: dict[str, dict[str, Any]] = {}

    def add(self, seats: list[dict[str, Any]], display_name: str, amount: float) -> None:
        for seat in seats:
            if seat.get("is_subcommittee") and not self._include_subcommittees:
                continue
            cid = seat["committee_id"]
            entry = self._totals.setdefault(cid, {
                "committee_id": cid,
                "committee_name": seat.get("name"),
                "chamber": seat.get("type"),
                "is_subcommittee": seat.get("is_subcommittee", False),
                "total_amount": 0.0,
                "recipient_count": 0,
                "recipients": [],
                "chairs_or_ranking_members": [],
            })
            entry["total_amount"] += amount
            if display_name not in entry["recipients"]:
                entry["recipients"].append(display_name)
                entry["recipient_count"] += 1
            title = seat.get("title")
            if title:
                labelled = f"{display_name} ({title})"
                if labelled not in entry["chairs_or_ranking_members"]:
                    entry["chairs_or_ranking_members"].append(labelled)

    def findings(self) -> list[dict[str, Any]]:
        return sorted(
            self._totals.values(), key=lambda c: c["total_amount"], reverse=True,
        )


async def _prime_congress_cache(client: CongressLegislatorsClient) -> bool:
    """Fetch the congress-legislators files once so subsequent lookups
    are pure in-memory reads."""
    await client.get_legislators()
    await client.get_committee_membership()
    await client.get_committees()
    return True


async def detect_lobbying_money_to_committee_seats(
    lda_client: LDAClient,
    congress_client: CongressLegislatorsClient,
    registrant_name: str,
    filing_year: int | None = None,
    include_subcommittees: bool = False,
) -> PatternMatch:
    """Aggregate a lobbying registrant's LD-203 political giving by the
    congressional committees its recipients sit on.

    See the module docstring (Pattern 4) for why this is scoped the way
    it is rather than as the originally-planned "dual role" pattern.
    """
    tracker = ServiceTracker()

    filings = await api_call(
        tracker, "LDA", "/contributions/",
        lambda: lda_client.search_contributions(
            registrant_name=registrant_name,
            filing_year=filing_year,
            page_size=25,
        ),
    )
    if filings is None:
        return PatternMatch(
            pattern_name="lobbying_money_to_committee_seats",
            title="Lobbying Money by Recipient Committee Seat",
            risk_level="INFO",
            status="ERROR",
            description="Could not fetch LD-203 data.",
            findings=[],
            warnings=tracker.warnings,
        )

    # Collect (honoree, amount) from every contribution item.
    items: list[tuple[str, float]] = []
    for filing in filings.get("results", []):
        for item in filing.get("contribution_items", []) or []:
            honoree = item.get("honoree_name")
            if not honoree:
                continue
            try:
                amount = float(item.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            items.append((honoree, amount))

    # Resolve each distinct honoree once, then fan the money out across
    # every committee seat that legislator holds.
    resolution: dict[str, dict[str, Any] | None] = {}
    unresolved: dict[str, float] = {}
    tally = _CommitteeSeatTally(include_subcommittees)
    resolved_amount = 0.0

    # Prime the congress-legislators cache through the rate-limited path
    # once, up front. Every lookup below is then served from memory, so
    # they must NOT go through api_call() — doing that would charge the
    # per-service rate limit for in-process dict reads and turn a
    # sub-second pattern into a multi-minute one (measured: it did).
    primed = await api_call(
        tracker, "congress-legislators", "(prime file cache)",
        lambda: _prime_congress_cache(congress_client),
    )
    if primed is None:
        return PatternMatch(
            pattern_name="lobbying_money_to_committee_seats",
            title="Lobbying Money by Recipient Committee Seat",
            risk_level="INFO",
            status="ERROR",
            description="Could not fetch congress-legislators data.",
            findings=[],
            warnings=tracker.warnings,
        )

    seat_cache: dict[str, list[dict[str, Any]]] = {}

    for honoree, amount in items:
        if honoree not in resolution:
            matches = await congress_client.search_legislators_by_name(honoree)
            # Only accept an unambiguous match — see module docstring.
            resolution[honoree] = matches[0] if len(matches) == 1 else None

        legislator = resolution[honoree]
        if legislator is None:
            unresolved[honoree] = unresolved.get(honoree, 0.0) + amount
            continue

        resolved_amount += amount
        bioguide = legislator.get("id", {}).get("bioguide")
        if bioguide not in seat_cache:
            seat_cache[bioguide] = await congress_client.get_committees_for_legislator(bioguide)
        seats = seat_cache[bioguide]

        name = legislator.get("name", {}).get("official_full") or honoree
        tally.add(seats, name, amount)

    findings = tally.findings()

    total_amount = sum(a for _, a in items)
    return PatternMatch(
        pattern_name="lobbying_money_to_committee_seats",
        title="Lobbying Money by Recipient Committee Seat",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Aggregates a lobbying registrant's LD-203 political "
            "contributions by the congressional committees its "
            "recipients sit on. Giving to a committee's members is not "
            "improper — but concentration relative to a firm's lobbying "
            "portfolio is the thing worth looking at. Note that the same "
            "dollar is counted once per committee the recipient sits on, "
            "so committee totals intentionally sum to more than the "
            "contribution total."
        ),
        findings=findings,
        stats={
            "registrant_name": registrant_name,
            "filing_year": filing_year,
            "contribution_items": len(items),
            "total_amount": round(total_amount, 2),
            "resolved_amount": round(resolved_amount, 2),
            "unresolved_amount": round(total_amount - resolved_amount, 2),
            "distinct_honorees": len(resolution),
            "resolved_honorees": sum(1 for v in resolution.values() if v),
            "unresolved_honorees": sorted(unresolved),
            "distinct_committees": len(findings),
        },
        warnings=(
            [
                "Committee assignments are current-only; contributions from an "
                "earlier filing_year are matched against today's committee "
                "rosters, and recipients who have since left office will not "
                "resolve at all.",
                "Honorees that are party committees or PACs (DCCC, NRSC, a "
                "firm's own PAC) are legitimately unresolvable — they are not "
                "individual legislators.",
            ]
            + tracker.warnings
        ),
    )


async def detect_industry_concentration(
    fec_client: OpenFECClient,
    congress_client: CongressLegislatorsClient,
    committee_id: str | None = None,
    committee_name: str | None = None,
    two_year_transaction_period: int | None = None,
    include_subcommittees: bool = False,
    min_amount: float = 0.0,
) -> PatternMatch:
    """Aggregate a PAC's outbound giving by the congressional committees
    its recipients sit on.

    See the module docstring (Pattern 5) for how this differs from
    pattern 4 and what it can and cannot see.
    """
    tracker = ServiceTracker()

    if committee_id is None:
        if not committee_name:
            return PatternMatch(
                pattern_name="industry_concentration",
                title="PAC Giving by Recipient Committee Seat",
                risk_level="INFO", status="ERROR",
                description="committee_id or committee_name is required.",
                findings=[],
            )
        found = await api_call(
            tracker, "OpenFEC", "/committees/",
            lambda: fec_client.search_committees(q=committee_name),
        )
        results = (found or {}).get("results", [])
        if not results:
            return PatternMatch(
                pattern_name="industry_concentration",
                title="PAC Giving by Recipient Committee Seat",
                risk_level="INFO", status="ERROR",
                description=f"No committee found matching {committee_name!r}.",
                findings=[], warnings=tracker.warnings,
            )
        committee_id = results[0]["committee_id"]

    detail = await api_call(
        tracker, "OpenFEC", "/committee/{id}/",
        lambda: fec_client.get_committee(committee_id),
    )
    record = ((detail or {}).get("results") or [{}])[0]

    disbursements = await api_call(
        tracker, "OpenFEC", "/schedules/schedule_b/",
        lambda: fec_client.search_disbursements(
            committee_id=committee_id,
            two_year_transaction_period=two_year_transaction_period,
            per_page=FEC_LOOKUP_PAGE_SIZE,
        ),
    )
    if disbursements is None:
        return PatternMatch(
            pattern_name="industry_concentration",
            title="PAC Giving by Recipient Committee Seat",
            risk_level="INFO", status="ERROR",
            description="Could not fetch FEC disbursement data.",
            findings=[], warnings=tracker.warnings,
        )

    primed = await api_call(
        tracker, "congress-legislators", "(prime file cache)",
        lambda: _prime_congress_cache(congress_client),
    )
    if primed is None:
        return PatternMatch(
            pattern_name="industry_concentration",
            title="PAC Giving by Recipient Committee Seat",
            risk_level="INFO", status="ERROR",
            description="Could not fetch congress-legislators data.",
            findings=[], warnings=tracker.warnings,
        )

    tally = _CommitteeSeatTally(include_subcommittees)
    seat_cache: dict[str, list[dict[str, Any]]] = {}
    legislator_cache: dict[str, dict[str, Any] | None] = {}

    total_out = 0.0
    attributed = 0.0
    to_committees = 0.0
    unattributed: dict[str, float] = {}

    for row in disbursements.get("results", []):
        amount = row.get("disbursement_amount") or 0
        if amount < min_amount:
            continue
        total_out += amount

        recipient_committee_id = row.get("recipient_committee_id")
        if not recipient_committee_id:
            continue  # vendor/operating spending, not a transfer to a committee
        to_committees += amount

        recipient = row.get("recipient_committee") or {}
        recipient_name = recipient.get("name") or row.get("recipient_name") or recipient_committee_id
        candidate_ids = recipient.get("candidate_ids") or []
        if not candidate_ids:
            # A committee with no candidate of its own — a leadership PAC,
            # party committee or another intermediary. Money can still reach a
            # member through it, but not by a link this pattern can follow.
            unattributed[recipient_name] = unattributed.get(recipient_name, 0.0) + amount
            continue

        matched_any = False
        for fec_candidate_id in candidate_ids:
            if fec_candidate_id not in legislator_cache:
                legislator_cache[fec_candidate_id] = (
                    await congress_client.find_legislator_by_fec_id(fec_candidate_id)
                )
            legislator = legislator_cache[fec_candidate_id]
            if legislator is None:
                continue  # not a sitting member: lost, retired, or never seated
            matched_any = True
            bioguide = legislator.get("id", {}).get("bioguide")
            if bioguide not in seat_cache:
                seat_cache[bioguide] = await congress_client.get_committees_for_legislator(bioguide)
            display = legislator.get("name", {}).get("official_full") or recipient_name
            tally.add(seat_cache[bioguide], display, amount)

        if matched_any:
            attributed += amount
        else:
            unattributed[recipient_name] = unattributed.get(recipient_name, 0.0) + amount

    findings = tally.findings()
    return PatternMatch(
        pattern_name="industry_concentration",
        title="PAC Giving by Recipient Committee Seat",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Aggregates a PAC's outbound giving by the congressional "
            "committees its recipients sit on. Giving to members with "
            "jurisdiction over a donor's industry is lawful and routine — "
            "the signal is concentration, and whether it lands on the "
            "committees that write the rules governing that donor."
        ),
        findings=findings,
        stats={
            "committee_id": committee_id,
            "committee_name": record.get("name"),
            "committee_type": record.get("committee_type_full"),
            "designation": record.get("designation_full"),
            "total_disbursed": round(total_out, 2),
            "to_other_committees": round(to_committees, 2),
            "attributed_to_sitting_members": round(attributed, 2),
            "unattributed_amount": round(to_committees - attributed, 2),
            "unattributed_recipients": sorted(
                ({"recipient": k, "amount": round(v, 2)} for k, v in unattributed.items()),
                key=lambda r: r["amount"], reverse=True,
            )[:10],
            "distinct_committees": len(findings),
        },
        warnings=[
            "Committee assignments are current-only; giving from an earlier "
            "cycle is matched against today's rosters, and recipients no longer "
            "in office will not resolve.",
            "Money routed through an intermediary committee (a leadership PAC, "
            "a party committee, a joint fundraising committee) is reported as "
            "unattributed rather than followed — the recipient has no candidate "
            "of its own to resolve. Trace those separately with the leadership "
            "PAC and joint-fundraising patterns.",
        ] + tracker.warnings,
    )


# One filing page is 25 records; a large registrant files hundreds a year
# and the lobbyist roster repeats heavily across them, so a few pages
# reach most of the distinct people at a fraction of the requests.
REVOLVING_DOOR_MAX_PAGES = 8


async def detect_revolving_door(
    lda_client: LDAClient,
    congress_client: CongressLegislatorsClient,
    registrant_name: str | None = None,
    client_name: str | None = None,
    filing_year: int | None = None,
    include_subcommittees: bool = False,
) -> PatternMatch:
    """Lobbyists with a disclosed prior tie to a current member or committee.

    This is what became of the roadmap's "dual role" pattern after the
    route it assumed turned out not to exist. Dual role wanted the
    committee a client lobbies *before*, which LDA does not record. This
    asks the question from the other end — which committees the client's
    own lobbyists previously *worked for* — and that LDA does record, in
    the `covered_position` disclosure.

    Two routes reach a committee, and the result labels which was used
    because they are not equally strong:

    - **served the committee**: the filer named the committee itself.
    - **staffed a sitting member**: the filer named a member, who is
      credited to every committee they currently sit on. This is a tie to
      a person, not to a committee's work, and it inherits whatever the
      member's seats happen to be today.

    Everything is resolved against congress-legislators and reported
    unresolved when it does not match exactly one current entity. See
    `packed/covered_position.py` for why the parser is built to propose
    rather than decide.
    """
    tracker = ServiceTracker()

    if not registrant_name and not client_name:
        return PatternMatch(
            pattern_name="revolving_door",
            title="Revolving-Door Ties to Current Committees",
            risk_level="INFO",
            status="ERROR",
            description="Provide a registrant_name or a client_name.",
            findings=[],
            warnings=tracker.warnings,
        )

    # Collect distinct lobbyists across filing pages. The same person
    # appears on every filing they work, so dedupe on the LDA lobbyist id.
    disclosed: dict[Any, dict[str, Any]] = {}
    total_lobbyist_rows = 0
    filings_seen = 0
    pages_fetched = 0

    for page in range(1, REVOLVING_DOOR_MAX_PAGES + 1):
        result = await api_call(
            tracker, "LDA", "/filings/",
            lambda p=page: lda_client.search_filings(
                registrant_name=registrant_name,
                client_name=client_name,
                filing_year=filing_year,
                page=p,
                page_size=25,
            ),
        )
        if result is None:
            break
        pages_fetched += 1
        results = result.get("results", []) or []
        if not results:
            break

        for filing in results:
            filings_seen += 1
            for activity in filing.get("lobbying_activities", []) or []:
                for row in activity.get("lobbyists", []) or []:
                    total_lobbyist_rows += 1
                    person = row.get("lobbyist") or {}
                    lobbyist_id = person.get("id")
                    if lobbyist_id is None:
                        continue
                    position = row.get("covered_position")
                    entry = disclosed.setdefault(lobbyist_id, {
                        "name": " ".join(
                            p for p in (person.get("first_name"),
                                        person.get("last_name")) if p
                        ).title() or str(lobbyist_id),
                        "covered_position": None,
                    })
                    # A lobbyist's covered position is disclosed on some
                    # filings and left blank on others; keep the first
                    # non-empty value rather than the last row seen.
                    if position and not entry["covered_position"]:
                        entry["covered_position"] = position.strip()

        if not result.get("next"):
            break

    if not disclosed and tracker.warnings:
        return PatternMatch(
            pattern_name="revolving_door",
            title="Revolving-Door Ties to Current Committees",
            risk_level="INFO",
            status="ERROR",
            description="Could not fetch LDA filings.",
            findings=[],
            warnings=tracker.warnings,
        )

    primed = await api_call(
        tracker, "congress-legislators", "(prime file cache)",
        lambda: _prime_congress_cache(congress_client),
    )
    if primed is None:
        return PatternMatch(
            pattern_name="revolving_door",
            title="Revolving-Door Ties to Current Committees",
            risk_level="INFO",
            status="ERROR",
            description="Could not fetch congress-legislators data.",
            findings=[],
            warnings=tracker.warnings,
        )

    committees = await congress_client.all_committees(
        include_subcommittees=include_subcommittees,
    )

    by_committee: dict[str, dict[str, Any]] = {}
    member_ties: dict[str, list[str]] = {}
    unresolved_members: dict[str, int] = {}
    unresolved_committees: dict[str, int] = {}
    ambiguous: dict[str, int] = {}

    legislator_cache: dict[str, list[dict[str, Any]]] = {}
    seat_cache: dict[str, list[dict[str, Any]]] = {}

    with_disclosure = 0
    with_tie = 0

    def credit(committee: dict[str, Any], lobbyist: str, route: str,
               via: str | None, position: str) -> None:
        cid = committee.get("committee_id")
        if not cid:
            return
        entry = by_committee.setdefault(cid, {
            "committee_id": cid,
            "committee_name": committee.get("name"),
            "chamber": committee.get("type"),
            "is_subcommittee": committee.get("is_subcommittee", False),
            "lobbyist_count": 0,
            "lobbyists": [],
        })
        for existing in entry["lobbyists"]:
            # A lobbyist reaching one committee by both routes is
            # reported once, on the stronger of the two.
            if existing["lobbyist"] == lobbyist:
                if route == "served the committee":
                    existing.update(route=route, via_member=via)
                return
        entry["lobbyists"].append({
            "lobbyist": lobbyist,
            "route": route,
            "via_member": via,
            "disclosed_position": position,
        })
        entry["lobbyist_count"] += 1

    for record in disclosed.values():
        position = record["covered_position"]
        if not position:
            continue
        with_disclosure += 1
        parsed = _covered_position.parse(position)
        tied = False

        for name in parsed.member_names:
            if name not in legislator_cache:
                legislator_cache[name] = await congress_client.search_legislators_by_name(name)
            matches = legislator_cache[name]
            if len(matches) != 1:
                bucket = ambiguous if len(matches) > 1 else unresolved_members
                bucket[name] = bucket.get(name, 0) + 1
                continue

            legislator = matches[0]
            bioguide = legislator.get("id", {}).get("bioguide")
            official = legislator.get("name", {}).get("official_full") or name
            member_ties.setdefault(official, [])
            if record["name"] not in member_ties[official]:
                member_ties[official].append(record["name"])
            tied = True

            if bioguide not in seat_cache:
                seat_cache[bioguide] = await congress_client.get_committees_for_legislator(bioguide)
            for seat in seat_cache[bioguide]:
                if seat.get("is_subcommittee") and not include_subcommittees:
                    continue
                credit(seat, record["name"], "staffed a sitting member", official, position)

        for phrase in parsed.committee_phrases:
            matches = _covered_position.match_committees(phrase, committees)
            if len(matches) != 1:
                bucket = ambiguous if len(matches) > 1 else unresolved_committees
                bucket[phrase] = bucket.get(phrase, 0) + 1
                continue
            tied = True
            credit(matches[0], record["name"], "served the committee", None, position)

        if tied:
            with_tie += 1

    findings = sorted(
        by_committee.values(),
        key=lambda c: (c["lobbyist_count"], c["committee_name"] or ""),
        reverse=True,
    )

    return PatternMatch(
        pattern_name="revolving_door",
        title="Revolving-Door Ties to Current Committees",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Groups a lobbying operation's people by the congressional "
            "committees they disclose having worked for, either directly "
            "or by staffing a member who sits on one. Moving from "
            "government to lobbying is lawful and extremely common; what "
            "the disclosure supports is showing where a firm's inside "
            "experience is concentrated, not an allegation about any of "
            "it. Note a lobbyist is counted once per committee reached, "
            "so committee counts sum to more than the headcount."
        ),
        findings=findings,
        stats={
            "registrant_name": registrant_name,
            "client_name": client_name,
            "filing_year": filing_year,
            "filings_examined": filings_seen,
            "pages_fetched": pages_fetched,
            "lobbyist_rows": total_lobbyist_rows,
            "distinct_lobbyists": len(disclosed),
            "with_covered_position": with_disclosure,
            "with_resolved_tie": with_tie,
            "distinct_committees": len(findings),
            "members_staffed": sorted(
                ({"member": k, "lobbyists": v} for k, v in member_ties.items()),
                key=lambda m: len(m["lobbyists"]), reverse=True,
            ),
            "unresolved_member_names": sorted(unresolved_members),
            "unresolved_committee_phrases": sorted(unresolved_committees),
            "ambiguous_references": sorted(ambiguous),
        },
        warnings=[
            "Only lobbyists who disclose a covered position can be "
            "assessed at all, and most do not. A lobbyist absent from "
            "these findings may have held a government post and not "
            "disclosed one here — absence is not evidence of no prior "
            "service.",
            "References to members who have left office do not resolve, "
            "because only current rosters are consulted. This is the "
            "largest single category of unresolved names, so ties to "
            "former members are systematically missing rather than rare.",
            "Committee seats are current-only: a lobbyist credited to a "
            "committee via a member is credited to the seats that member "
            "holds today, which need not be the seats they held while "
            "that lobbyist worked for them.",
        ] + tracker.warnings,
    )


# Committees that receive earmarked money and pass it on. A contribution
# routed through one names the conduit as recipient, not the campaign, so
# clustering on the recipient would group unrelated donations that merely
# share a platform.
PASS_THROUGH_COMMITTEES = frozenset({
    "ACTBLUE", "ACTBLUE CIVICS", "WINRED", "WINRED PAC",
})

# Small recurring online giving dominates Schedule A by row count and
# produces dense same-amount coincidences ($10 on the same day) that carry
# no signal. The floor is set to exclude that traffic rather than to mark
# a threshold of concern.
EMPLOYER_CLUSTER_MIN_AMOUNT = 200.0
EMPLOYER_CLUSTER_WINDOW_DAYS = 3
EMPLOYER_CLUSTER_MIN_DONORS = 2
EMPLOYER_CLUSTER_MAX_PAGES = 12


def _cluster_key(recipient: str, donors: tuple[str, ...]) -> tuple:
    return (recipient, donors)


def _maximal_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop clusters wholly contained in a larger one.

    A sliding window starting at each contribution re-finds the same
    event at every offset, so one four-donor cluster also appears as a
    three- and a two-donor cluster. Reporting all of them would triple
    count a single event.
    """
    kept: list[dict[str, Any]] = []
    for candidate in sorted(clusters, key=lambda c: len(c["donors"]), reverse=True):
        names = {d["contributor"] for d in candidate["donors"]}
        if any(
            other["recipient_committee_id"] == candidate["recipient_committee_id"]
            and names <= {d["contributor"] for d in other["donors"]}
            for other in kept
        ):
            continue
        kept.append(candidate)
    return kept


async def detect_employer_contribution_clusters(
    fec_client: OpenFECClient,
    employer: str,
    two_year_transaction_period: int | None = None,
    window_days: int = EMPLOYER_CLUSTER_WINDOW_DAYS,
    min_donors: int = EMPLOYER_CLUSTER_MIN_DONORS,
    min_amount: float = EMPLOYER_CLUSTER_MIN_AMOUNT,
    include_pass_through: bool = False,
) -> PatternMatch:
    """People sharing an employer who give to one recipient together.

    See the module docstring (Pattern 7) for what this shape does and
    does not support. In short: it is the shape of a reimbursement
    scheme and equally the shape of a lawful workplace fundraising
    drive, and nothing in Schedule A distinguishes them. The result is a
    lead.
    """
    tracker = ServiceTracker()

    rows: list[dict[str, Any]] = []
    last_index = None
    last_date = None
    for _ in range(EMPLOYER_CLUSTER_MAX_PAGES):
        page = await api_call(
            tracker, "OpenFEC", "/schedules/schedule_a/",
            lambda li=last_index, ld=last_date: fec_client.search_contributions(
                contributor_employer=employer,
                two_year_transaction_period=two_year_transaction_period,
                per_page=100,
                last_index=li,
                last_contribution_receipt_date=ld,
            ),
        )
        if page is None:
            break
        results = page.get("results") or []
        if not results:
            break
        rows.extend(results)
        indexes = (page.get("pagination") or {}).get("last_indexes") or {}
        last_index = indexes.get("last_index")
        last_date = indexes.get("last_contribution_receipt_date")
        if not last_index:
            break

    if not rows and tracker.warnings:
        return PatternMatch(
            pattern_name="employer_contribution_clusters",
            title="Contribution Clusters by Employer",
            risk_level="INFO",
            status="ERROR",
            description="Could not fetch Schedule A contributions.",
            findings=[],
            warnings=tracker.warnings,
        )

    # Normalise to (date, contributor, amount, recipient) and drop the
    # traffic the floor and the pass-through rule exclude.
    from datetime import date as _date

    parsed: list[tuple[_date, str, float, str, str]] = []
    pass_through_rows = 0
    below_floor_rows = 0
    recipient_totals: dict[str, dict[str, Any]] = {}

    for row in rows:
        raw_date = (row.get("contribution_receipt_date") or "")[:10]
        contributor = row.get("contributor_name")
        committee = row.get("committee") or {}
        recipient_name = (committee.get("name") or "").upper()
        recipient_id = row.get("committee_id")
        try:
            amount = float(row.get("contribution_receipt_amount") or 0)
        except (TypeError, ValueError):
            continue
        if not (raw_date and contributor and recipient_id and recipient_name):
            continue
        try:
            when = _date.fromisoformat(raw_date)
        except ValueError:
            continue

        if recipient_name in PASS_THROUGH_COMMITTEES and not include_pass_through:
            pass_through_rows += 1
            continue

        entry = recipient_totals.setdefault(recipient_id, {
            "recipient_committee_id": recipient_id,
            "recipient": committee.get("name"),
            "total_amount": 0.0,
            "donors": set(),
        })
        entry["total_amount"] += amount
        entry["donors"].add(contributor)

        if amount < min_amount:
            below_floor_rows += 1
            continue
        parsed.append((when, contributor, amount, recipient_id, committee.get("name") or recipient_id))

    parsed.sort(key=lambda r: r[0])

    by_recipient: dict[str, list[tuple[_date, str, float, str]]] = {}
    for when, contributor, amount, recipient_id, recipient_name in parsed:
        by_recipient.setdefault(recipient_id, []).append(
            (when, contributor, amount, recipient_name)
        )

    raw_clusters: list[dict[str, Any]] = []
    for recipient_id, items in by_recipient.items():
        for start in range(len(items)):
            window_start = items[start][0]
            grouped: dict[str, list[tuple[_date, float]]] = {}
            for when, contributor, amount, recipient_name in items[start:]:
                if (when - window_start).days > window_days:
                    break
                grouped.setdefault(contributor, []).append((when, amount))
            if len(grouped) < min_donors:
                continue
            donors = [
                {
                    "contributor": name,
                    "amount": round(sum(a for _, a in gifts), 2),
                    "dates": sorted({d.isoformat() for d, _ in gifts}),
                }
                for name, gifts in sorted(grouped.items())
            ]
            amounts = {d["amount"] for d in donors}
            raw_clusters.append({
                "recipient_committee_id": recipient_id,
                "recipient": items[start][3],
                "window_start": window_start.isoformat(),
                "donor_count": len(donors),
                "total_amount": round(sum(d["amount"] for d in donors), 2),
                # Identical amounts are what separates this shape from
                # ordinary colleagues giving in the same week. A
                # reimbursement is a fixed sum handed to each conduit.
                "amounts_identical": len(amounts) == 1,
                "donors": donors,
            })

    findings = sorted(
        _maximal_clusters(raw_clusters),
        key=lambda c: (c["donor_count"], c["total_amount"]),
        reverse=True,
    )

    concentration = sorted(
        (
            {
                "recipient_committee_id": v["recipient_committee_id"],
                "recipient": v["recipient"],
                "total_amount": round(v["total_amount"], 2),
                "donor_count": len(v["donors"]),
            }
            for v in recipient_totals.values()
        ),
        key=lambda r: r["total_amount"], reverse=True,
    )

    return PatternMatch(
        pattern_name="employer_contribution_clusters",
        title="Contribution Clusters by Employer",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Groups contributions from people sharing an employer who "
            "gave to the same recipient within a short window. This is "
            "the shape of a reimbursement scheme, in which a company "
            "funds contributions made in employees' names — and equally "
            "the shape of a lawful workplace fundraising drive. Nothing "
            "in Schedule A separates the two, so a cluster is a lead to "
            "check, never a finding. Clusters where every donor gave an "
            "identical amount are flagged, since a reimbursement is "
            "typically a fixed sum per person while colleagues giving "
            "independently rarely match to the dollar."
        ),
        findings=findings,
        stats={
            "employer": employer,
            "two_year_transaction_period": two_year_transaction_period,
            "contributions_examined": len(rows),
            "eligible_after_filters": len(parsed),
            "pass_through_rows_excluded": pass_through_rows,
            "below_floor_rows_excluded": below_floor_rows,
            "window_days": window_days,
            "min_donors": min_donors,
            "min_amount": min_amount,
            "clusters": len(findings),
            "clusters_with_identical_amounts": sum(
                1 for f in findings if f["amounts_identical"]
            ),
            "recipient_concentration": concentration[:15],
        },
        warnings=[
            "A cluster is not evidence of reimbursement. Lawful bundling "
            "— a PAC drive, a fundraiser at the office, colleagues "
            "attending the same event — produces the same shape, and is "
            "far more common than the unlawful version.",
            "Employer is self-reported free text on each contribution "
            "and is matched as written. Spelling variants, subsidiaries "
            "and blank fields all cause under-collection, so any total "
            "here is a floor.",
            "Contributions routed through a pass-through committee name "
            "that conduit as the recipient rather than the campaign, so "
            "they are excluded by default; the money still reached a "
            "candidate this pattern cannot see.",
        ] + tracker.warnings,
    )


VENDOR_OVERLAP_MIN_AMOUNT = 1000.0
VENDOR_OVERLAP_MAX_PAGES = 6
VENDOR_OVERLAP_MAX_IE_COMMITTEES = 5


def _same_vendor(a: str, b: str) -> bool:
    """Do two payee names refer to one vendor?

    Delegates entirely to onoma. This briefly carried a rule requiring a
    shared token of at least four characters, to stop "AT&T" matching
    "MILLER'S SUPPLIES AT WORK" — onoma reduced that name to the single
    token "at" and treated a preposition as identifying. Fixed upstream,
    and the workaround had to go rather than stay: it also rejected "BP"
    against "BP AMERICA", which is a match anyone would want.
    """
    return bool(a) and bool(b) and onoma.same_org(a, b)


async def _collect_payees(
    fec_client: OpenFECClient,
    tracker: ServiceTracker,
    committee_id: str,
    cycle: int | None,
    schedule: str,
) -> dict[str, float]:
    """Total paid to each payee by one committee, on one schedule.

    Both schedules are needed for an independent-expenditure committee:
    its operating costs are on B, but the media buys — the money that
    makes it worth looking at — are on E, under a separate payee field.
    A campaign has no E of its own.
    """
    totals: dict[str, float] = {}
    last_index = None
    last_date = None

    for _ in range(VENDOR_OVERLAP_MAX_PAGES):
        if schedule == "B":
            page = await api_call(
                tracker, "OpenFEC", "/schedules/schedule_b/",
                lambda li=last_index, ld=last_date: fec_client.search_disbursements(
                    committee_id=committee_id,
                    two_year_transaction_period=cycle,
                    per_page=100,
                    last_index=li,
                    last_disbursement_date=ld,
                ),
            )
            name_field, amount_field = "recipient_name", "disbursement_amount"
            date_key = "last_disbursement_date"
        else:
            page = await api_call(
                tracker, "OpenFEC", "/schedules/schedule_e/",
                lambda li=last_index, ld=last_date: fec_client.search_independent_expenditures(
                    committee_id=committee_id,
                    two_year_transaction_period=cycle,
                    per_page=100,
                    last_index=li,
                    last_expenditure_date=ld,
                ),
            )
            name_field, amount_field = "payee_name", "expenditure_amount"
            date_key = "last_expenditure_date"

        if page is None:
            break
        results = page.get("results") or []
        if not results:
            break
        for row in results:
            name = (row.get(name_field) or "").strip()
            if not name:
                continue
            try:
                totals[name] = totals.get(name, 0.0) + float(row.get(amount_field) or 0)
            except (TypeError, ValueError):
                continue
        indexes = (page.get("pagination") or {}).get("last_indexes") or {}
        last_index = indexes.get("last_index")
        last_date = indexes.get(date_key)
        if not last_index:
            break

    return totals


async def detect_common_vendor_overlap(
    fec_client: OpenFECClient,
    candidate_id: str,
    two_year_transaction_period: int | None = None,
    support_oppose_indicator: str = "S",
    min_amount: float = VENDOR_OVERLAP_MIN_AMOUNT,
    max_ie_committees: int = VENDOR_OVERLAP_MAX_IE_COMMITTEES,
) -> PatternMatch:
    """Vendors paid by both a candidate's campaign and an outside group
    spending to elect them.

    See the module docstring (Pattern 8) for what a shared vendor does
    and does not show. Coordination is a legal conclusion resting on
    facts disclosure cannot reach, and sharing a vendor is lawful where
    the firm maintains a firewall. This reports the overlap.
    """
    tracker = ServiceTracker()

    committees = await api_call(
        tracker, "OpenFEC", f"/candidate/{candidate_id}/committees/",
        lambda: fec_client.get_candidate_committees(candidate_id),
    )
    if committees is None:
        return PatternMatch(
            pattern_name="common_vendor_overlap",
            title="Vendors Shared With Outside Spenders",
            risk_level="INFO",
            status="ERROR",
            description="Could not resolve the candidate's committees.",
            findings=[],
            warnings=tracker.warnings,
        )

    campaigns = [
        c for c in (committees.get("results") or [])
        if (c.get("designation") or "") in ("P", "A")
    ]
    if not campaigns:
        return PatternMatch(
            pattern_name="common_vendor_overlap",
            title="Vendors Shared With Outside Spenders",
            risk_level="INFO",
            status="ACTIVE",
            description="No authorized campaign committee found for this candidate.",
            findings=[],
            stats={"candidate_id": candidate_id},
            warnings=tracker.warnings,
        )

    campaign = campaigns[0]
    campaign_id = campaign.get("committee_id")

    # Who is spending independently for (or against) this candidate.
    spenders = await api_call(
        tracker, "OpenFEC", "/schedules/schedule_e/",
        lambda: fec_client.search_independent_expenditures(
            candidate_id=candidate_id,
            support_oppose_indicator=support_oppose_indicator,
            two_year_transaction_period=two_year_transaction_period,
            per_page=100,
        ),
    )
    ie_totals: dict[str, dict[str, Any]] = {}
    for row in ((spenders or {}).get("results") or []):
        cid = row.get("committee_id")
        if not cid or cid == campaign_id:
            continue
        entry = ie_totals.setdefault(cid, {
            "committee_id": cid,
            "name": (row.get("committee") or {}).get("name") or cid,
            "reported_ie_amount": 0.0,
        })
        try:
            entry["reported_ie_amount"] += float(row.get("expenditure_amount") or 0)
        except (TypeError, ValueError):
            pass

    ranked = sorted(
        ie_totals.values(), key=lambda c: c["reported_ie_amount"], reverse=True,
    )[:max_ie_committees]

    campaign_payees = await _collect_payees(
        fec_client, tracker, campaign_id, two_year_transaction_period, "B",
    )
    campaign_total = sum(campaign_payees.values())

    findings: list[dict[str, Any]] = []
    for spender in ranked:
        payees = await _collect_payees(
            fec_client, tracker, spender["committee_id"], two_year_transaction_period, "E",
        )
        for name, amount in (await _collect_payees(
            fec_client, tracker, spender["committee_id"], two_year_transaction_period, "B",
        )).items():
            payees[name] = payees.get(name, 0.0) + amount
        spender_total = sum(payees.values())

        shared: list[dict[str, Any]] = []
        for camp_name, camp_amount in campaign_payees.items():
            for ie_name, ie_amount in payees.items():
                if camp_amount < min_amount and ie_amount < min_amount:
                    continue
                if not _same_vendor(camp_name, ie_name):
                    continue
                shared.append({
                    "vendor": ie_name if len(ie_name) >= len(camp_name) else camp_name,
                    "campaign_payee_name": camp_name,
                    "outside_payee_name": ie_name,
                    "campaign_amount": round(camp_amount, 2),
                    "outside_amount": round(ie_amount, 2),
                    # Share is what separates a shared consultant from a
                    # shared airline: a commodity vendor is a rounding
                    # error on both sides. The denominator is the
                    # spending actually retrieved, not the committee's
                    # true total, so the field name says "sampled" —
                    # pagination is capped and a large committee is not
                    # read to the end.
                    "share_of_sampled_outside_spending": (
                        round(100 * ie_amount / spender_total, 2) if spender_total else None
                    ),
                    "share_of_sampled_campaign_spending": (
                        round(100 * camp_amount / campaign_total, 2) if campaign_total else None
                    ),
                })

        if not shared:
            continue
        shared.sort(key=lambda v: v["outside_amount"], reverse=True)
        findings.append({
            "outside_committee_id": spender["committee_id"],
            "outside_committee": spender["name"],
            "reported_ie_amount": round(spender["reported_ie_amount"], 2),
            "sampled_outside_spending": round(spender_total, 2),
            "outside_payees_sampled": len(payees),
            "shared_vendor_count": len(shared),
            "shared_vendors": shared,
        })

    findings.sort(key=lambda f: f["shared_vendor_count"], reverse=True)

    return PatternMatch(
        pattern_name="common_vendor_overlap",
        title="Vendors Shared With Outside Spenders",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Finds vendors paid by both a candidate's own campaign and "
            "an outside group spending independently to elect them. "
            "Sharing a vendor is lawful — consultancies serve many "
            "clients and may firewall their teams — and coordination is "
            "a legal conclusion resting on facts no filing discloses. "
            "What this reports is the overlap and what each side paid. "
            "Read the share columns rather than the raw list: every "
            "committee buys travel and shipping from the same handful of "
            "companies, so a commodity vendor means nothing, while a "
            "consultancy taking a large share of both sides is the thing "
            "worth asking about."
        ),
        findings=findings,
        stats={
            "candidate_id": candidate_id,
            "campaign_committee_id": campaign_id,
            "campaign_committee": campaign.get("name"),
            "two_year_transaction_period": two_year_transaction_period,
            "support_oppose_indicator": support_oppose_indicator,
            "campaign_payees": len(campaign_payees),
            "sampled_campaign_spending": round(campaign_total, 2),
            "outside_committees_found": len(ie_totals),
            "outside_committees_examined": len(ranked),
            "outside_committees_with_overlap": len(findings),
            "min_amount": min_amount,
        },
        warnings=[
            "A shared vendor is not coordination. Coordination turns on "
            "whether information passed between the campaign and the "
            "spender, which no filing discloses. Treat an overlap as a "
            "question, not an answer.",
            "Commodity vendors — airlines, rideshare, shipping, hotels, "
            "payment processors — appear in almost every pair and carry "
            "no signal. The share columns are there to separate them "
            "from a consultancy taking real money from both sides.",
            "Payee names are free text and matched by name, so a vendor "
            "billing under two unrelated names will be missed and a "
            "count here is a floor.",
            "Only the largest outside spenders are examined, so a small "
            "committee sharing a vendor can fall outside the result.",
            "Share percentages are computed over the spending actually "
            "retrieved, which is capped by pagination. For a large "
            "committee that is a sample rather than its full ledger, so "
            "read a share as relative weight within what was read, not "
            "as a fraction of everything the committee spent.",
        ] + tracker.warnings,
    )
