"""Tests for the connection graph.

The graph makes one claim — that two entities are connected by N
separate routes — and almost everything that can go wrong here is a way
of overstating that claim. So most of these assert on what the graph
refuses to do.
"""

import pytest

from packed import graph as g
from packed import graph_html
from packed.patterns import PatternMatch


def _match(name, findings, stats=None, status="ACTIVE"):
    return PatternMatch(name, "t", "INFO", status, "d", findings, stats or {})


class TestEdgeVocabulary:
    def test_a_route_edge_cannot_carry_an_amount(self):
        """The entire reason the vocabulary exists. A figure on a route
        edge is money attributed across a commingled hop, which is the
        error the graph is built to prevent."""
        with pytest.raises(ValueError, match="cannot carry an amount"):
            g.Edge("a", "b", g.ROUTE, "employs", "p", amount=5000.0)

    def test_a_lead_edge_cannot_carry_an_amount(self):
        with pytest.raises(ValueError, match="cannot carry an amount"):
            g.Edge("a", "b", g.LEAD, "clustered", "p", amount=1.0)

    def test_an_attributable_edge_may(self):
        assert g.Edge("a", "b", g.ATTRIBUTABLE, "gave", "p", amount=2500.0).amount == 2500.0

    def test_unknown_kinds_are_rejected(self):
        with pytest.raises(ValueError, match="unknown edge kind"):
            g.Edge("a", "b", "probably", "gave", "p")

    def test_every_kind_carries_its_meaning_into_the_output(self):
        """A renderer must not be free to restate what an edge licenses."""
        edge = g.Edge("a", "b", g.ROUTE, "employs", "p")
        assert "commingled" in edge.to_dict()["means"]


class TestNodeIdentity:
    def test_identifier_nodes_are_marked_exact(self):
        node = g.Node(g.committee_node_id("C00799031"), "UDP", "committee")
        assert node.identity == "exact"

    def test_name_matched_nodes_say_so(self):
        """A path through a name-matched node is worth less than one
        through a filed identifier, and a reader cannot tell unless the
        graph says which it is."""
        node = g.Node(g.org_node_id("Mission Control Inc", "vendor"), "MISSION CONTROL INC", "vendor")
        assert node.identity == "resolved-by-name"

    def test_entity_suffixes_do_not_create_two_nodes(self):
        assert g.org_node_id("Mission Control", "vendor") == g.org_node_id("MISSION CONTROL INC", "vendor")

    def test_titles_do_not_create_two_people(self):
        assert g.person_node_id("Sen. Marsha Blackburn") == g.person_node_id("Marsha Blackburn")


class TestGraphAssembly:
    def test_an_edge_needs_both_endpoints_first(self):
        graph = g.ConnectionGraph()
        graph.add_node(g.Node("a", "A", "committee"))
        with pytest.raises(KeyError):
            graph.add_edge(g.Edge("a", "b", g.ATTRIBUTABLE, "gave", "p"))

    def test_the_same_edge_twice_is_recorded_once(self):
        graph = g.ConnectionGraph()
        graph.add_node(g.Node("a", "A", "committee"))
        graph.add_node(g.Node("b", "B", "committee"))
        for _ in range(3):
            graph.add_edge(g.Edge("a", "b", g.ATTRIBUTABLE, "gave", "p", amount=1.0))
        assert len(graph.edges) == 1

    def test_a_later_pattern_enriches_a_node_rather_than_replacing_it(self):
        graph = g.ConnectionGraph()
        graph.add_node(g.Node("fec:C1", "PAC", "committee", {"designation": "D"}))
        graph.add_node(g.Node("fec:C1", "PAC", "committee", {"receipts": 100.0}))
        assert graph.nodes["fec:C1"].detail == {"designation": "D", "receipts": 100.0}


class TestPathFinding:
    def _diamond(self):
        graph = g.ConnectionGraph()
        for nid, label in [("camp", "CAMPAIGN"), ("pac", "SUPER PAC"),
                           ("v1", "CONSULTANCY"), ("v2", "AIRLINE")]:
            graph.add_node(g.Node(nid, label, "committee"))
        graph.add_edge(g.Edge("pac", "camp", g.ATTRIBUTABLE, "spent to support", "p", amount=2_000_000.0))
        graph.add_edge(g.Edge("camp", "v1", g.ATTRIBUTABLE, "paid", "p", amount=9_000.0))
        graph.add_edge(g.Edge("pac", "v1", g.ATTRIBUTABLE, "paid", "p", amount=1_300_000.0))
        graph.add_edge(g.Edge("camp", "v2", g.ATTRIBUTABLE, "paid", "p", amount=2_700.0))
        graph.add_edge(g.Edge("pac", "v2", g.ATTRIBUTABLE, "paid", "p", amount=5_400.0))
        return graph

    def test_finds_every_route_shortest_first(self):
        paths = self._diamond().paths_between("camp", "pac")
        assert len(paths) == 3
        assert [p.hops for p in paths] == [1, 2, 2]

    def test_a_route_never_revisits_a_node(self):
        for path in self._diamond().paths_between("camp", "pac"):
            assert len(path.nodes) == len(set(path.nodes))

    def test_a_path_is_only_as_strong_as_its_weakest_edge(self):
        graph = g.ConnectionGraph()
        for nid in ("a", "b", "c"):
            graph.add_node(g.Node(nid, nid.upper(), "committee"))
        graph.add_edge(g.Edge("a", "b", g.ATTRIBUTABLE, "gave", "p", amount=100.0))
        graph.add_edge(g.Edge("b", "c", g.LEAD, "clustered with", "p"))
        assert graph.paths_between("a", "c")[0].weakest_kind == g.LEAD

    def test_routes_through_one_intermediary_count_once(self):
        """Two edges through the same node are one relationship described
        twice; counting both overstates how many ways two entities are
        connected, which is the graph's entire claim."""
        graph = g.ConnectionGraph()
        for nid in ("a", "hub", "b"):
            graph.add_node(g.Node(nid, nid.upper(), "committee"))
        graph.add_edge(g.Edge("a", "hub", g.ATTRIBUTABLE, "paid", "p", amount=1.0))
        graph.add_edge(g.Edge("a", "hub", g.ATTRIBUTABLE, "gave", "q", amount=2.0))
        graph.add_edge(g.Edge("hub", "b", g.ATTRIBUTABLE, "paid", "p", amount=3.0))
        found = graph.paths_between("a", "b")
        assert len(found) == 2
        assert len(g.ConnectionGraph.independent(found)) == 1

    def test_no_path_between_unconnected_nodes(self):
        graph = g.ConnectionGraph()
        graph.add_node(g.Node("a", "A", "committee"))
        graph.add_node(g.Node("b", "B", "committee"))
        assert graph.paths_between("a", "b") == []

    def test_hop_limit_is_respected(self):
        graph = g.ConnectionGraph()
        chain = ["n0", "n1", "n2", "n3", "n4"]
        for nid in chain:
            graph.add_node(g.Node(nid, nid, "committee"))
        for a, b in zip(chain, chain[1:]):
            graph.add_edge(g.Edge(a, b, g.ROUTE, "linked", "p"))
        assert graph.paths_between("n0", "n4", max_hops=3) == []
        assert len(graph.paths_between("n0", "n4", max_hops=4)) == 1

    def test_unknown_endpoints_return_nothing(self):
        assert self._diamond().paths_between("camp", "nope") == []


class TestAdapters:
    def test_vendor_overlap_builds_the_multi_route_shape(self):
        match = _match(
            "common_vendor_overlap",
            [{
                "outside_committee_id": "C00799031", "outside_committee": "UDP",
                "reported_ie_amount": 2_081_530.0, "shared_vendor_count": 2,
                "shared_vendors": [
                    {"vendor": "MISSION CONTROL INC", "campaign_amount": 9250.0,
                     "outside_amount": 1_389_589.0,
                     "share_of_sampled_outside_spending": 0.92},
                    {"vendor": "HOTELS.COM", "campaign_amount": 9559.0,
                     "outside_amount": 1026.0,
                     "share_of_sampled_outside_spending": 0.0},
                ],
            }],
            {"campaign_committee_id": "C00903039", "campaign_committee": "STEVENS"},
        )
        graph = g.build([match])
        paths = graph.paths_between("fec:C00903039", "fec:C00799031")
        assert len(paths) == 3, "direct IE plus one route per shared vendor"

    def test_a_vendors_share_travels_to_the_node(self):
        """It is what separates a shared consultancy from a shared
        airline, and the graph cannot make that call itself."""
        match = _match(
            "common_vendor_overlap",
            [{"outside_committee_id": "C1", "outside_committee": "PAC",
              "reported_ie_amount": 1.0,
              "shared_vendors": [{"vendor": "HOTELS.COM", "campaign_amount": 1.0,
                                  "outside_amount": 1.0,
                                  "share_of_sampled_outside_spending": 0.0}]}],
            {"campaign_committee_id": "C2", "campaign_committee": "CAMP"},
        )
        node = g.build([match]).nodes[g.org_node_id("HOTELS.COM", "vendor")]
        assert node.detail["share_of_sampled_outside_spending"] == 0.0

    def test_contribution_clusters_are_leads_and_the_gifts_are_not(self):
        """The individual contributions are disclosed facts. The cluster
        drawn over them is a shape lawful bundling also produces."""
        match = _match(
            "employer_contribution_clusters",
            [{"recipient_committee_id": "C00McC", "recipient": "MCCOLLUM",
              "window_start": "2022-06-03", "donor_count": 2, "total_amount": 4800.0,
              "amounts_identical": False,
              "donors": [{"contributor": "SAUER, PETER D", "amount": 2900.0, "dates": ["2022-06-03"]},
                         {"contributor": "MEIER, DAVID M", "amount": 1900.0, "dates": ["2022-06-03"]}]}],
            {"employer": "Calspan", "recipient_concentration": []},
        )
        graph = g.build([match])
        kinds = {(e.relation, e.kind) for e in graph.edges}
        assert ("contributed to", g.ATTRIBUTABLE) in kinds
        assert ("colleagues gave together", g.LEAD) in kinds
        assert ("employs", g.ROUTE) in kinds

    def test_revolving_door_keeps_the_two_routes_distinct(self):
        match = _match(
            "revolving_door",
            [{"committee_id": "SSFI", "committee_name": "Senate Finance", "chamber": "senate",
              "lobbyists": [
                  {"lobbyist": "Rosemary Becchi", "route": "served the committee",
                   "via_member": None, "disclosed_position": "Tax Counsel"},
                  {"lobbyist": "Someone Else", "route": "staffed a sitting member",
                   "via_member": "A Member", "disclosed_position": "LA"},
              ]}],
            {"registrant_name": "Brownstein Hyatt"},
        )
        relations = {e.relation for e in g.build([match]).edges}
        assert "served the committee" in relations
        assert "staffed a member now seated here" in relations

    def test_committee_seat_exposure_carries_no_amount(self):
        """Exposure to a committee is the sum of gifts to its members,
        not a payment to the committee. Drawing it as an amount would
        invent a transfer that never happened."""
        match = _match(
            "industry_concentration",
            [{"committee_id": "SSAF", "committee_name": "Senate Ag", "chamber": "senate",
              "total_amount": 50_000.0, "recipient_count": 4, "chairs_or_ranking_members": []}],
            {"committee_id": "C0PAC", "committee_name": "A PAC"},
        )
        edges = g.build([match]).edges
        assert all(e.amount is None for e in edges)
        assert all(e.kind == g.ROUTE for e in edges)

    def test_patterns_merge_into_one_graph(self):
        vendor = _match("common_vendor_overlap",
                        [{"outside_committee_id": "C1", "outside_committee": "PAC",
                          "reported_ie_amount": 1.0, "shared_vendors": []}],
                        {"campaign_committee_id": "C2", "campaign_committee": "CAMP"})
        ratio = _match("candidate_support_ratio",
                       [{"cycle": 2024, "candidate_and_party_share_reported": 12.85,
                         "receipts": 473371.0}],
                       {"committee_id": "C1", "committee_name": "PAC"})
        graph = g.build([vendor, ratio])
        assert set(graph.sources) == {"common_vendor_overlap", "candidate_support_ratio"}
        assert graph.nodes["fec:C1"].detail["share_reaching_candidates"] == 12.85

    def test_an_errored_pattern_contributes_nothing(self):
        assert g.build([_match("common_vendor_overlap", [], {}, status="ERROR")]).nodes == {}

    def test_a_pattern_without_an_adapter_is_skipped_not_fatal(self):
        """Adding a detection pattern must never break graph building."""
        graph = g.build([_match("some_future_pattern", [{"x": 1}], {"y": 2})])
        assert graph.nodes == {}
        assert graph.sources == []


class TestHtmlRendering:
    def _graph(self):
        graph = g.ConnectionGraph()
        graph.add_node(g.Node("fec:C1", "CAMPAIGN", "committee"))
        graph.add_node(g.Node("vendor:x", "A VENDOR </script>", "vendor"))
        graph.add_edge(g.Edge("fec:C1", "vendor:x", g.ATTRIBUTABLE, "paid", "p", amount=10.0))
        graph.sources.append("common_vendor_overlap")
        return graph

    def test_renders_a_single_self_contained_page(self):
        html = graph_html.render(self._graph(), heading="Test")
        assert html.startswith("<!doctype html>")
        assert html.count("<script>") == 1 and html.count("</script>") == 1

    def test_makes_no_network_requests(self):
        """The output is an artefact someone keeps. It has to still work
        offline in two years."""
        html = graph_html.render(self._graph(), heading="Test")
        for marker in ("<script src", "<link rel=\"stylesheet\"", "@import", "https://"):
            assert marker not in html

    def test_a_payee_name_cannot_close_the_script_element(self):
        """Payee names are attacker-adjacent free text from a public
        filing, and one containing a closing tag would end the script
        early and break the page."""
        html = graph_html.render(self._graph(), heading="Test")
        body = html.split("<script>", 1)[1]
        assert "</script>" in body
        assert body.index("</script>") > body.index("A VENDOR")
        assert "<\\/script>" in body

    def test_the_heading_is_escaped(self):
        html = graph_html.render(self._graph(), heading="<img onerror=x>")
        assert "<img onerror=x>" not in html
        assert "&lt;img onerror=x&gt;" in html

    def test_warnings_travel_into_the_page(self):
        html = graph_html.render(
            self._graph(), heading="T", warnings=["bundling looks identical"],
        )
        assert "bundling looks identical" in html

    def test_the_page_states_why_amounts_stop(self):
        html = graph_html.render(self._graph(), heading="T")
        assert "commingled" in html
