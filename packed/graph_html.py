"""Self-contained interactive rendering of a connection graph.

Follows sift's approach, because the sibling tool already solved this and
diverging would give the two a different feel for no reason: a vendored
D3 build rather than a hand-rolled force loop, a tabbed report rather
than a single canvas, and an overview with the findings stated in prose
before any graph is drawn. A force-directed hairball is not an analysis;
it is raw material for one.

What is packed's own, because the domain differs from sift's:

**Edge style encodes the kind of claim, never the size of a number.**
sift draws ownership, where a claim survives every link and a deep graph
is meaningful. Political money is commingled at the first intermediary,
so no amount survives the hop. A thick line through that hop would
assert a figure nobody can defend, so amounts appear only on edges where
a filing names both parties and the sum.

**Node identity is visible.** An identifier node is exact; a name-matched
one is onoma's guess and can merge two entities or miss one written
differently. It carries a dashed ring, because a route is worth what its
weakest node is worth.

**Nothing is summed along a path**, anywhere, in the code or the
interface. There is deliberately no total.

The output makes no network requests: it is an artefact someone keeps,
and it has to still open in five years from a directory with no
internet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .graph import ATTRIBUTABLE, LEAD, ROUTE, ConnectionGraph

_HERE = Path(__file__).resolve().parent
_ASSETS = _HERE / "visualizations"
_TEMPLATE = _ASSETS / "connection-viz.html"
_D3 = _ASSETS / "d3.v7.min.js"


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _committee_rows(matches: Iterable[Any]) -> list[dict[str, Any]]:
    """Funder-by-committee exposure, from the two seat-tally patterns."""
    rows: list[dict[str, Any]] = []
    for m in matches:
        if m.pattern_name not in (
            "industry_concentration", "lobbying_money_to_committee_seats",
        ):
            continue
        funder = (
            m.stats.get("committee_name")
            or m.stats.get("registrant_name")
            or m.stats.get("committee_id")
            or "unknown"
        )
        for f in m.findings:
            rows.append({
                "funder": funder,
                "committee": f.get("committee_name") or f.get("committee_id"),
                "chamber": f.get("chamber"),
                "amount": float(f.get("total_amount") or 0),
                "recipients": f.get("recipient_count") or 0,
                "chairs": f.get("chairs_or_ranking_members") or [],
            })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def _cluster_rows(matches: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in matches:
        if m.pattern_name != "employer_contribution_clusters":
            continue
        employer = m.stats.get("employer") or "unknown"
        for f in m.findings:
            rows.append({
                "employer": employer,
                "recipient": f.get("recipient"),
                "window": f.get("window_start"),
                "identical": bool(f.get("amounts_identical")),
                "donors": [
                    {"name": d.get("contributor"), "amount": d.get("amount"),
                     "dates": d.get("dates") or []}
                    for d in f.get("donors", [])
                ],
            })
    rows.sort(key=lambda r: len(r["donors"]), reverse=True)
    return rows


def _revolving_rows(matches: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in matches:
        if m.pattern_name != "revolving_door":
            continue
        for f in m.findings:
            people = [
                {
                    "name": p.get("lobbyist"),
                    "route": p.get("route"),
                    "served": p.get("route") == "served the committee",
                    "via": p.get("via_member"),
                    "position": (p.get("disclosed_position") or "")[:120],
                }
                for p in f.get("lobbyists", [])
            ]
            rows.append({
                "committee": f.get("committee_name") or f.get("committee_id"),
                "chamber": f.get("chamber"),
                "people": people,
                "served": any(p["served"] for p in people),
            })
    rows.sort(key=lambda r: (r["served"], len(r["people"])), reverse=True)
    return rows


def _backer_rows(matches: Iterable[Any]) -> list[dict[str, Any]]:
    """Who funds each committee, and how concentrated that funding is."""
    out: list[dict[str, Any]] = []
    for m in matches:
        if m.pattern_name != "committee_backers":
            continue
        st = m.stats
        out.append({
            "committee": st.get("committee_name") or st.get("committee_id"),
            "designation": st.get("designation"),
            "itemised": st.get("itemised_total"),
            "dominant": bool(st.get("single_backer_dominant")),
            "top_share": st.get("top_backer_share"),
            "institutional_share": st.get("institutional_share"),
            "shown": min(12, len(m.findings)),
            "total_backers": st.get("distinct_backers"),
            "backers": [
                {"name": f.get("contributor"), "amount": f.get("amount"),
                 "share": f.get("share_of_itemised"), "kind": f.get("kind")}
                for f in m.findings[:12]
            ],
        })
    out.sort(key=lambda r: r["itemised"] or 0, reverse=True)
    return out


def _ratio_rows(matches: Iterable[Any]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    below = 0
    for m in matches:
        if m.pattern_name != "candidate_support_ratio":
            continue
        below += int(m.stats.get("periods_below_receipts_floor") or 0)
        name = m.stats.get("committee_name") or m.stats.get("committee_id")
        for f in m.findings:
            share = f.get("candidate_and_party_share_reported")
            if share is None:
                share = f.get("share_of_disbursements_to_candidates")
            rows.append({
                "committee": name,
                "cycle": f.get("cycle"),
                "receipts": f.get("receipts"),
                "share": share,
                "low": bool(f.get("low_support")),
            })
    return rows, below


def _findings(graph: ConnectionGraph, views: dict[str, Any]) -> list[dict[str, str]]:
    """The overview's prose. Stated as observations, never conclusions.

    Written here rather than in the template because it depends on what
    the data actually contains — a page that says "what stands out" and
    then lists nothing is worse than one that says nothing.
    """
    out: list[dict[str, str]] = []

    strongest = [
        r for r in views["revolving"] if r["served"] and len(r["people"]) > 1
    ]
    if strongest:
        r = strongest[0]
        out.append({
            "title": f"{len(r['people'])} of the firm's people came from {r['committee']}",
            "body": (
                "They disclose having served that committee directly, which is a "
                "stronger tie than having staffed a member who happens to sit on "
                "it today. Lawful, and common — the point is where the inside "
                "experience is concentrated."
            ),
        })

    identical = [c for c in views["clusters"] if c["identical"]]
    if identical:
        c = identical[0]
        out.append({
            "title": (
                f"{len(c['donors'])} people at {c['employer']} gave "
                f"identical amounts to {c['recipient']} on {c['window']}"
            ),
            "body": (
                "Equal sums on one day is what a fixed reimbursement per person "
                "looks like. It is also what a workplace fundraiser looks like, "
                "and no filing separates them. A lead to check, not a finding."
            ),
        })

    low = [r for r in views["ratios"] if r["low"]]
    if low:
        r = low[0]
        out.append({
            "title": (
                f"{r['committee']} sent {r['share']:.1f}% of its spending to "
                f"candidates in {r['cycle']}"
            ),
            "body": (
                "No law sets a required ratio, and an independent-expenditure or "
                "issue-advocacy group is not meant to give to candidates at all. "
                "This is where the money went, not a verdict on it."
            ),
        })

    if views["committees"]:
        top = views["committees"][0]
        out.append({
            "title": (
                f"{top['funder']}'s money lands hardest on {top['committee']}"
            ),
            "body": (
                f"${top['amount']:,.0f} across {top['recipients']} members who sit "
                "on it. Giving to the committee with jurisdiction over you is "
                "lawful and routine; concentration is the thing worth reading."
            ),
        })

    dominant = [b for b in views["backers"] if b["dominant"]]
    if dominant:
        b = dominant[0]
        out.append({
            "title": (
                f"{b['top_share']:.1f}% of {b['committee']}'s itemised money "
                f"came from one backer"
            ),
            "body": (
                "A committee drawing nearly all its funding from a single "
                "source is better described as that source's vehicle than as "
                "an independent actor. Lawful, and a factual reading of the "
                "filings — but it changes who the spender really is."
            ),
        })

    resolved = graph.to_dict()["counts"]["nodes_resolved_by_name"]
    if resolved:
        out.append({
            "title": f"{resolved} entities here were matched by name, not identifier",
            "body": (
                "Name matching can merge two entities that share a name and miss "
                "one written differently. Those nodes carry a dashed ring, and a "
                "route through one is worth less than a route through a filed "
                "identifier."
            ),
        })
    return out


def render(
    graph: ConnectionGraph,
    matches: Iterable[Any] = (),
    heading: str = "packed — connection graph",
    subhead: str = "",
    warnings: list[str] | None = None,
    suggest: tuple[str, str] | None = None,
) -> str:
    """One self-contained interactive HTML page."""
    matches = [m for m in matches if m is not None and getattr(m, "status", "") != "ERROR"]

    ratios, ratios_below = _ratio_rows(matches)
    views = {
        "committees": _committee_rows(matches),
        "clusters": _cluster_rows(matches),
        "revolving": _revolving_rows(matches),
        "ratios": ratios,
        "backers": _backer_rows(matches),
        "ratios_below_floor": ratios_below,
    }
    views["findings"] = _findings(graph, views)

    payload: dict[str, Any] = graph.to_dict()
    payload["views"] = views
    payload["warnings"] = warnings or []
    payload["suggest"] = list(suggest) if suggest else []

    template = _TEMPLATE.read_text(encoding="utf-8")
    return (
        template
        .replace("__TITLE__", _escape(heading))
        .replace("__HEADING__", _escape(heading))
        .replace("__SUBHEAD__", _escape(subhead))
        .replace("__COMMITTEES_EMPTY__", "no" if views["committees"] else "yes")
        .replace("__CLUSTERS_EMPTY__", "no" if views["clusters"] else "yes")
        .replace("__REVOLVING_EMPTY__", "no" if views["revolving"] else "yes")
        .replace("__RATIOS_EMPTY__", "no" if views["ratios"] else "yes")
        .replace("__BACKERS_EMPTY__", "no" if views["backers"] else "yes")
        .replace("__D3__", _D3.read_text(encoding="utf-8"))
        # A payee name containing a closing tag would end the script
        # element early. These are free text from public filings.
        .replace("__DATA__", json.dumps(payload).replace("</", "<\\/"))
    )
