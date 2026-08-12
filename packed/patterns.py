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
