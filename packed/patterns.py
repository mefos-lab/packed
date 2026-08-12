"""Cross-source detection patterns.

Unlike Sift's pattern system (a generic condition engine evaluated
against a unified traversal graph — see sift/pattern_matcher.py),
packed has no cross-source graph/traversal layer yet. Each pattern
here is a bespoke function that queries the relevant clients directly
and applies domain-specific matching logic. A generic rule engine
isn't warranted until there are enough patterns sharing structure to
justify the abstraction — see CLAUDE.md for the reasoning.

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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .lda_client import LDAClient
from .openfec_client import OpenFECClient
from .errors import ServiceTracker, api_call

AMOUNT_TOLERANCE = 1.00  # dollars
DATE_WINDOW_DAYS = 60
NAME_OVERLAP_THRESHOLD = 0.6
FEC_LOOKUP_PAGE_SIZE = 100  # a single contributor can easily exceed the default 20/page

# Generic words that shouldn't count as matching evidence on their own —
# "COMMITTEE" or "PAC" alone overlapping proves nothing about identity.
_GENERIC_COMMITTEE_WORDS = {
    "for", "of", "the", "and", "inc", "llc", "committee", "pac",
    "fund", "trust", "victory", "political", "action",
}


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


def _normalize(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _names_roughly_match(a: str | None, b: str | None) -> bool:
    """Loose name match for committee/PAC names that get abbreviated,
    expanded, or reworded across filing systems (e.g. "ARKANSAS
    LEADERSHIP PAC" vs "ARKANSAS FOR LEADERSHIP POLITICAL ACTION
    COMMITTEE (ARKPAC)"). Ratio is computed against the shorter name
    so an abbreviated form isn't unfairly penalized for the longer
    name's extra words, and at least one shared word must be
    non-generic so "COMMITTEE"/"PAC" overlap alone doesn't count.
    """
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    words_a, words_b = set(na.split()), set(nb.split())
    if not words_a or not words_b:
        return False
    shared = words_a & words_b
    if not shared or shared <= _GENERIC_COMMITTEE_WORDS:
        return False
    overlap = len(shared) / min(len(words_a), len(words_b))
    return overlap >= NAME_OVERLAP_THRESHOLD


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
        if not _names_roughly_match(payee_name, committee_name):
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


async def detect_leadership_pac_transfers(
    fec_client: OpenFECClient,
    committee_id: str | None = None,
    committee_name: str | None = None,
    two_year_transaction_period: int | None = None,
    min_transfer_amount: float = 0.0,
) -> PatternMatch:
    """Trace both legs of a leadership PAC's money flow: who funds it
    (top Schedule A contributors), and which candidate/other committees
    it transfers money to (Schedule B disbursements with a
    recipient_committee_id — i.e. not ordinary vendor spending).
    """
    tracker = ServiceTracker()

    if committee_id is None:
        if not committee_name:
            return PatternMatch(
                pattern_name="leadership_pac_transfers",
                title="Leadership PAC Fund Routing",
                risk_level="INFO",
                status="ERROR",
                description="committee_id or committee_name is required.",
                findings=[],
            )
        search_result = await api_call(
            tracker, "OpenFEC", "/committees/",
            lambda: fec_client.search_committees(
                q=committee_name, designation=LEADERSHIP_PAC_DESIGNATION,
            ),
        )
        results = (search_result or {}).get("results", [])
        if not results:
            return PatternMatch(
                pattern_name="leadership_pac_transfers",
                title="Leadership PAC Fund Routing",
                risk_level="INFO",
                status="ERROR",
                description=f"No leadership PAC found matching {committee_name!r}.",
                findings=[],
                warnings=tracker.warnings,
            )
        committee_id = results[0]["committee_id"]

    committee_detail = await api_call(
        tracker, "OpenFEC", "/committee/{id}/",
        lambda: fec_client.get_committee(committee_id),
    )
    committee_record = ((committee_detail or {}).get("results") or [{}])[0]
    committee_display_name = committee_record.get("name")
    extra_warnings: list[str] = []
    if committee_record.get("designation") != LEADERSHIP_PAC_DESIGNATION:
        extra_warnings.append(
            f"{committee_id} has designation "
            f"{committee_record.get('designation_full', committee_record.get('designation'))!r}, "
            f"not Leadership PAC — results may not reflect a leadership PAC's flow."
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
        pattern_name="leadership_pac_transfers",
        title="Leadership PAC Fund Routing",
        risk_level="INFO",
        status="ACTIVE",
        description=(
            "Traces a leadership PAC's money flow: top contributors "
            "funding it, and which committees it transfers money to. "
            "A transfer to a candidate committee isn't inherently "
            "improper — leadership PACs exist for exactly this purpose "
            "— but the pattern surfaces who's funding the PAC and who "
            "it's funding in turn."
        ),
        findings=findings,
        stats={
            "leadership_pac_committee_id": committee_id,
            "leadership_pac_name": committee_display_name,
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
