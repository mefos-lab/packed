"""A connection graph over the detection patterns.

Every pattern already returns identified endpoints — a committee ID, a
bioguide, a payee name — but each returns them in its own shape, so
nothing can be asked across two patterns at once. This turns all of them
into one node-and-edge vocabulary.

**Why a connection graph and not a money-flow diagram.** Money entering
an intermediary committee is commingled: a leadership PAC that receives
$5,000 from one donor holds it in a single account, and when it later
gives $10,000 to a candidate no part of that sum is traceable to the
original donor. A weighted flow diagram would draw a line straight
through that hop and invent a number nobody can defend.

Connectivity survives what amounts do not. That two entities are linked
by three separate disclosed routes is a fact, and needs no dollar figure
attached to the far end. So every edge declares which kind of claim it
is, and the three are never blended:

``ATTRIBUTABLE``
    A disclosed amount between two named parties. One filing says this
    happened, and the amount is real.

``ROUTE``
    Connectivity only. The link is real, no amount can be carried along
    it. Anything past a commingled hop is this.

``LEAD``
    A shape worth checking, not a finding. A contribution cluster is the
    example: it is equally the shape of a reimbursement scheme and of a
    lawful workplace fundraising drive, and nothing in the data
    separates them.

Summing along a path is therefore never correct, and the renderer does
not offer it. Paths are counted and listed, not totalled.

**Node identity** is deliberately explicit. An identifier-based node
(``fec:C00799031``) is exact; a name-based one (``org:mission-control``)
is a resolution guess made by onoma and can be wrong in both directions.
The prefix records which, so a reader can see how much weight a link
bears.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import onoma

ATTRIBUTABLE = "attributable"
ROUTE = "route"
LEAD = "lead"

EDGE_KINDS = (ATTRIBUTABLE, ROUTE, LEAD)

# What each edge kind licenses a reader to say. Carried into the graph
# output so a renderer cannot restate it differently.
EDGE_KIND_MEANING = {
    ATTRIBUTABLE: (
        "A disclosed amount between two named parties. The filing says "
        "this happened and the figure is real."
    ),
    ROUTE: (
        "A real connection carrying no amount. Money past this point is "
        "commingled with everything else the intermediary raised, so no "
        "sum can be attributed along it."
    ),
    LEAD: (
        "A shape worth checking, not a finding. Lawful activity produces "
        "the same picture, and nothing in the data separates the two."
    ),
}

# Node kinds, and whether the identifier is exact or resolved by name.
EXACT_PREFIXES = ("fec", "bioguide", "cmte", "lda")
RESOLVED_PREFIXES = ("org", "person", "employer", "vendor")


def _slug(text: str) -> str:
    folded = onoma.fold(text or "")
    return "-".join(folded.split())[:80] or "unknown"


def committee_node_id(fec_id: str) -> str:
    return f"fec:{fec_id}"


def congressional_committee_node_id(thomas_id: str) -> str:
    return f"cmte:{thomas_id}"


def member_node_id(bioguide: str) -> str:
    return f"bioguide:{bioguide}"


def person_node_id(name: str) -> str:
    return f"person:{_slug(onoma.strip_titles(name) or name)}"


def org_node_id(name: str, prefix: str = "org") -> str:
    return f"{prefix}:{_slug(onoma.strip_entity_types(name) or name)}"


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    kind: str
    detail: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def identity(self) -> str:
        """Whether this node is an exact identifier or a name match."""
        prefix = self.id.split(":", 1)[0]
        if prefix in EXACT_PREFIXES:
            return "exact"
        return "resolved-by-name"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "kind": self.kind,
            "identity": self.identity, "detail": self.detail,
        }


@dataclass
class Edge:
    source: str
    target: str
    kind: str
    relation: str
    pattern: str
    amount: float | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EDGE_KINDS:
            raise ValueError(f"unknown edge kind {self.kind!r}")
        if self.kind != ATTRIBUTABLE and self.amount:
            # A ROUTE or LEAD edge carrying an amount is the exact error
            # this vocabulary exists to prevent.
            raise ValueError(
                f"{self.kind} edge cannot carry an amount; "
                f"only {ATTRIBUTABLE} edges may."
            )

    @property
    def key(self) -> tuple:
        return (self.source, self.target, self.relation, self.pattern)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "target": self.target, "kind": self.kind,
            "relation": self.relation, "pattern": self.pattern,
            "amount": self.amount, "detail": self.detail,
            "means": EDGE_KIND_MEANING[self.kind],
        }


@dataclass
class Path:
    """One route between two entities."""

    nodes: list[str]
    edges: list[Edge]

    @property
    def hops(self) -> int:
        return len(self.edges)

    @property
    def weakest_kind(self) -> str:
        """A path is only as strong as its weakest edge."""
        for kind in (LEAD, ROUTE, ATTRIBUTABLE):
            if any(e.kind == kind for e in self.edges):
                return kind
        return ATTRIBUTABLE

    def to_dict(self, graph: ConnectionGraph) -> dict[str, Any]:
        return {
            "hops": self.hops,
            "weakest_link": self.weakest_kind,
            "means": EDGE_KIND_MEANING[self.weakest_kind],
            "nodes": [graph.nodes[n].to_dict() for n in self.nodes if n in graph.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


class ConnectionGraph:
    """Nodes and typed edges, merged across any number of patterns."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._edge_keys: set[tuple] = set()
        self.sources: list[str] = []

    def add_node(self, node: Node) -> str:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
        elif node.detail:
            # Later patterns enrich a node rather than replacing it.
            merged = dict(existing.detail)
            merged.update(node.detail)
            self.nodes[node.id] = Node(existing.id, existing.label, existing.kind, merged)
        return node.id

    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self.nodes or edge.target not in self.nodes:
            raise KeyError("both endpoints must be added before the edge")
        if edge.key in self._edge_keys:
            return
        self._edge_keys.add(edge.key)
        self.edges.append(edge)

    def neighbours(self, node_id: str) -> list[tuple[str, Edge]]:
        out = []
        for e in self.edges:
            if e.source == node_id:
                out.append((e.target, e))
            elif e.target == node_id:
                out.append((e.source, e))
        return out

    def paths_between(
        self, start: str, end: str, max_hops: int = 4, limit: int = 25,
    ) -> list[Path]:
        """Every simple path between two nodes, shortest first.

        Breadth-first so short paths surface before long ones. Paths
        revisiting a node are skipped: a route through the same entity
        twice is an artefact of the search, not a second connection.
        """
        if start not in self.nodes or end not in self.nodes or start == end:
            return []

        found: list[Path] = []
        queue: deque[tuple[str, list[str], list[Edge]]] = deque([(start, [start], [])])
        while queue and len(found) < limit:
            current, seen, taken = queue.popleft()
            if len(taken) >= max_hops:
                continue
            for neighbour, edge in self.neighbours(current):
                if neighbour in seen:
                    continue
                if neighbour == end:
                    found.append(Path(seen + [neighbour], taken + [edge]))
                    if len(found) >= limit:
                        break
                else:
                    queue.append((neighbour, seen + [neighbour], taken + [edge]))
        return found

    @staticmethod
    def independent(paths: Iterable[Path]) -> list[Path]:
        """Paths sharing no intermediate node with a shorter one.

        Two routes through the same intermediary are one relationship
        described twice. Counting them separately overstates how many
        ways two entities are connected, which is the whole claim this
        graph makes.
        """
        kept: list[Path] = []
        used: set[str] = set()
        for path in sorted(paths, key=lambda p: p.hops):
            middle = set(path.nodes[1:-1])
            if middle & used:
                continue
            kept.append(path)
            used |= middle
        return kept

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "patterns_included": sorted(self.sources),
            "edge_kinds": EDGE_KIND_MEANING,
            "counts": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "attributable_edges": sum(1 for e in self.edges if e.kind == ATTRIBUTABLE),
                "route_edges": sum(1 for e in self.edges if e.kind == ROUTE),
                "lead_edges": sum(1 for e in self.edges if e.kind == LEAD),
                "nodes_resolved_by_name": sum(
                    1 for n in self.nodes.values() if n.identity == "resolved-by-name"
                ),
            },
        }


# ── Pattern adapters ────────────────────────────────────────────────
#
# One per pattern. Each knows only its own finding shape and the shared
# vocabulary, so adding a pattern later means adding a function here and
# nothing else.


def _seat_tally_edges(graph: ConnectionGraph, match, funder_id: str, pattern: str) -> None:
    """Shared by the two patterns aggregating money by committee seat."""
    for finding in match.findings:
        cid = finding.get("committee_id")
        if not cid:
            continue
        graph.add_node(Node(
            congressional_committee_node_id(cid),
            finding.get("committee_name") or cid,
            "congressional_committee",
            {"chamber": finding.get("chamber"),
             "chairs_or_ranking_members": finding.get("chairs_or_ranking_members", [])},
        ))
        graph.add_edge(Edge(
            funder_id, congressional_committee_node_id(cid),
            # Exposure to a committee is the sum of gifts to its members,
            # not a payment to the committee, so it carries no amount as
            # a single disclosed transfer.
            ROUTE, "money lands on this committee's members", pattern,
            detail=(
                f"${finding.get('total_amount', 0):,.0f} across "
                f"{finding.get('recipient_count', 0)} members who sit on it"
            ),
        ))


def add_industry_concentration(graph: ConnectionGraph, match) -> None:
    pac_id = match.stats.get("committee_id")
    if not pac_id:
        return
    node = graph.add_node(Node(
        committee_node_id(pac_id),
        match.stats.get("committee_name") or pac_id,
        "committee",
        {"designation": match.stats.get("designation")},
    ))
    _seat_tally_edges(graph, match, node, "industry_concentration")


def add_lobbying_money_to_committee_seats(graph: ConnectionGraph, match) -> None:
    name = match.stats.get("registrant_name")
    if not name:
        return
    node = graph.add_node(Node(org_node_id(name, "org"), name, "lobbying_firm"))
    _seat_tally_edges(graph, match, node, "lobbying_money_to_committee_seats")


def add_committee_money_flow(graph: ConnectionGraph, match) -> None:
    """Leadership-PAC and joint-fundraising transfers.

    Money in is attributable — a named donor gave a named committee a
    disclosed sum. Money out is attributable too. What is *not*
    attributable is any figure joining the two, which is exactly why
    they are separate edges and never one.
    """
    cid = match.stats.get("committee_id")
    if not cid:
        return
    hub = graph.add_node(Node(
        committee_node_id(cid),
        match.stats.get("committee_name") or cid,
        "committee",
    ))
    for contributor in match.stats.get("top_contributors", []) or []:
        name = contributor.get("contributor_name")
        if not name:
            continue
        donor = graph.add_node(Node(person_node_id(name), name, "contributor"))
        try:
            amount = float(contributor.get("amount") or 0) or None
        except (TypeError, ValueError):
            amount = None
        graph.add_edge(Edge(
            donor, hub, ATTRIBUTABLE, "contributed to", match.pattern_name,
            amount=amount, detail=str(contributor.get("date") or ""),
        ))
    for finding in match.findings:
        rid = finding.get("recipient_committee_id")
        if not rid:
            continue
        recipient = graph.add_node(Node(
            committee_node_id(rid),
            finding.get("recipient_name") or rid,
            "committee",
        ))
        graph.add_edge(Edge(
            hub, recipient, ATTRIBUTABLE, "transferred to", match.pattern_name,
            amount=finding.get("total_amount"),
            detail=f"{finding.get('transaction_count', 0)} transactions",
        ))


def add_revolving_door(graph: ConnectionGraph, match) -> None:
    firm_name = match.stats.get("registrant_name") or match.stats.get("client_name")
    if not firm_name:
        return
    firm = graph.add_node(Node(org_node_id(firm_name, "org"), firm_name, "lobbying_firm"))

    for finding in match.findings:
        cid = finding.get("committee_id")
        if not cid:
            continue
        committee = graph.add_node(Node(
            congressional_committee_node_id(cid),
            finding.get("committee_name") or cid,
            "congressional_committee",
            {"chamber": finding.get("chamber")},
        ))
        for entry in finding.get("lobbyists", []):
            person_name = entry.get("lobbyist")
            if not person_name:
                continue
            person = graph.add_node(Node(
                person_node_id(person_name), person_name, "lobbyist",
                {"disclosed_position": entry.get("disclosed_position")},
            ))
            graph.add_edge(Edge(
                firm, person, ROUTE, "employs", "revolving_door",
            ))
            served = entry.get("route") == "served the committee"
            graph.add_edge(Edge(
                person, committee,
                # Serving the committee is disclosed directly. Staffing a
                # member who happens to sit there today is a tie to a
                # person, inheriting whatever seats they now hold.
                ROUTE,
                "served the committee" if served else "staffed a member now seated here",
                "revolving_door",
                detail=(entry.get("via_member") or ""),
            ))


def add_employer_contribution_clusters(graph: ConnectionGraph, match) -> None:
    employer_name = match.stats.get("employer")
    if not employer_name:
        return
    employer = graph.add_node(Node(
        org_node_id(employer_name, "employer"), employer_name, "employer",
    ))

    for entry in match.stats.get("recipient_concentration", []) or []:
        rid = entry.get("recipient_committee_id")
        if not rid:
            continue
        graph.add_node(Node(
            committee_node_id(rid), entry.get("recipient") or rid, "committee",
        ))

    for finding in match.findings:
        rid = finding.get("recipient_committee_id")
        if not rid:
            continue
        recipient = graph.add_node(Node(
            committee_node_id(rid), finding.get("recipient") or rid, "committee",
        ))
        for donor_entry in finding.get("donors", []):
            donor_name = donor_entry.get("contributor")
            if not donor_name:
                continue
            donor = graph.add_node(Node(
                person_node_id(donor_name), donor_name, "contributor",
            ))
            graph.add_edge(Edge(
                employer, donor, ROUTE, "employs", "employer_contribution_clusters",
            ))
            graph.add_edge(Edge(
                donor, recipient, ATTRIBUTABLE, "contributed to",
                "employer_contribution_clusters",
                amount=donor_entry.get("amount"),
                detail=", ".join(donor_entry.get("dates", [])),
            ))
        graph.add_edge(Edge(
            employer, recipient, LEAD,
            "colleagues gave together", "employer_contribution_clusters",
            detail=(
                f"{finding.get('donor_count')} donors within the window on "
                f"{finding.get('window_start')}"
                + (", identical amounts" if finding.get("amounts_identical") else "")
            ),
        ))


def add_common_vendor_overlap(graph: ConnectionGraph, match) -> None:
    campaign_id = match.stats.get("campaign_committee_id")
    if not campaign_id:
        return
    campaign = graph.add_node(Node(
        committee_node_id(campaign_id),
        match.stats.get("campaign_committee") or campaign_id,
        "committee",
    ))

    for finding in match.findings:
        oid = finding.get("outside_committee_id")
        if not oid:
            continue
        outside = graph.add_node(Node(
            committee_node_id(oid),
            finding.get("outside_committee") or oid,
            "outside_spender",
        ))
        graph.add_edge(Edge(
            outside, campaign, ATTRIBUTABLE,
            "spent independently to support", "common_vendor_overlap",
            amount=finding.get("reported_ie_amount"),
        ))
        for vendor in finding.get("shared_vendors", []):
            name = vendor.get("vendor")
            if not name:
                continue
            node = graph.add_node(Node(
                org_node_id(name, "vendor"), name, "vendor",
                {"share_of_sampled_outside_spending":
                    vendor.get("share_of_sampled_outside_spending")},
            ))
            graph.add_edge(Edge(
                campaign, node, ATTRIBUTABLE, "paid", "common_vendor_overlap",
                amount=vendor.get("campaign_amount"),
            ))
            graph.add_edge(Edge(
                outside, node, ATTRIBUTABLE, "paid", "common_vendor_overlap",
                amount=vendor.get("outside_amount"),
            ))


def annotate_candidate_support_ratio(graph: ConnectionGraph, match) -> None:
    """Not a relationship — an attribute of a committee already present."""
    cid = match.stats.get("committee_id")
    if not cid or not match.findings:
        return
    latest = match.findings[0]
    graph.add_node(Node(
        committee_node_id(cid),
        match.stats.get("committee_name") or cid,
        "committee",
        {
            "cycle": latest.get("cycle"),
            "share_reaching_candidates":
                latest.get("candidate_and_party_share_reported"),
            "receipts": latest.get("receipts"),
        },
    ))


# A large committee has hundreds of small backers. The pattern returns
# all of them, because the tail is real; the graph draws only material
# ones, because 700 donor nodes is a hairball that hides the finding
# rather than showing it. Share of the committee's itemised total is the
# right filter — a fixed dollar floor means different things to a
# $100,000 committee and an $80,000,000 one.
BACKER_GRAPH_MIN_SHARE = 1.0
BACKER_GRAPH_MAX = 20


def add_committee_backers(graph: ConnectionGraph, match) -> None:
    """Who funds a committee — the money-in side.

    This is the edge that makes "a super PAC backed by X" drawable. Both
    hops are disclosed and both carry amounts, but they are separate
    edges and never one: what a backer gave the committee and what the
    committee later spent are different sums, and the second cannot be
    attributed to the first.
    """
    cid = match.stats.get("committee_id")
    if not cid:
        return
    committee = graph.add_node(Node(
        committee_node_id(cid),
        match.stats.get("committee_name") or cid,
        "committee",
        {
            "designation": match.stats.get("designation"),
            "itemised_total": match.stats.get("itemised_total"),
            "top_backer": match.stats.get("top_backer"),
            "top_backer_share": match.stats.get("top_backer_share"),
            "single_backer_dominant": match.stats.get("single_backer_dominant"),
        },
    ))

    material = [
        f for f in match.findings
        if (f.get("share_of_itemised") or 0) >= BACKER_GRAPH_MIN_SHARE
    ][:BACKER_GRAPH_MAX]
    graph.nodes[committee] = Node(
        committee, graph.nodes[committee].label, graph.nodes[committee].kind,
        {**graph.nodes[committee].detail,
         "backers_shown": len(material),
         "backers_total": len(match.findings)},
    )

    for finding in material:
        name = finding.get("contributor")
        if not name:
            continue
        kind = finding.get("kind")
        if finding.get("contributor_committee_id"):
            backer_id = committee_node_id(finding["contributor_committee_id"])
            node_kind = "committee"
        elif kind == "individual":
            backer_id = person_node_id(name)
            node_kind = "contributor"
        else:
            backer_id = org_node_id(name, "org")
            node_kind = "backer"
        backer = graph.add_node(Node(
            backer_id, name, node_kind,
            {"share_of_committee_itemised": finding.get("share_of_itemised")},
        ))
        graph.add_edge(Edge(
            backer, committee, ATTRIBUTABLE, "funded", "committee_backers",
            amount=finding.get("amount"),
            detail=(
                f"{finding.get('share_of_itemised')}% of the committee's "
                f"itemised receipts"
            ),
        ))


ADAPTERS = {
    "industry_concentration": add_industry_concentration,
    "lobbying_money_to_committee_seats": add_lobbying_money_to_committee_seats,
    "leadership_pac_transfers": add_committee_money_flow,
    "jfc_obscuring": add_committee_money_flow,
    "revolving_door": add_revolving_door,
    "employer_contribution_clusters": add_employer_contribution_clusters,
    "common_vendor_overlap": add_common_vendor_overlap,
    "candidate_support_ratio": annotate_candidate_support_ratio,
    "committee_backers": add_committee_backers,
}


def build(matches: Iterable[Any]) -> ConnectionGraph:
    """Merge any set of pattern results into one graph.

    A pattern with no adapter is skipped rather than raising, so adding a
    detection pattern never breaks graph building — it just contributes
    nothing until an adapter exists.
    """
    graph = ConnectionGraph()
    for match in matches:
        if match is None or getattr(match, "status", None) == "ERROR":
            continue
        adapter = ADAPTERS.get(match.pattern_name)
        if adapter is None:
            continue
        adapter(graph, match)
        if match.pattern_name not in graph.sources:
            graph.sources.append(match.pattern_name)
    return graph
