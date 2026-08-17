"""Tests for the connection graph.

The graph makes one claim — that two entities are connected by N
separate routes — and almost everything that can go wrong here is a way
of overstating that claim. So most of these assert on what the graph
refuses to do.
"""

import re

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

    def _app_script(self, html):
        """The page has two scripts: vendored D3, then the application."""
        blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
        assert len(blocks) == 2, f"expected d3 + app, got {len(blocks)}"
        return blocks[1]

    def test_renders_one_complete_document(self):
        html = graph_html.render(self._graph(), heading="Test")
        assert html.startswith("<!doctype html>")
        assert html.count("<script>") == html.count("</script>") == 2

    def test_d3_is_vendored_into_the_page(self):
        """sift vendors D3 rather than loading it from a CDN, and this
        follows that: the output has to open years from now, offline."""
        html = graph_html.render(self._graph(), heading="Test")
        assert "d3js.org" in html and "forceCollide" in html

    def test_nothing_is_fetched_at_load(self):
        """What breaks an offline copy is a loading mechanism, not a URL
        in a comment. D3 also ships a fetch helper it never calls unless
        asked, so the network assertions split: markup is checked for
        loaders, and only the application script for calls."""
        html = graph_html.render(self._graph(), heading="Test")
        markup = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
        for loader in ("<script src", '<link rel="stylesheet"', "@import",
                       "<iframe", "<img src", "url(http"):
            assert loader not in markup, loader
        app = self._app_script(html)
        for call in ("fetch(", "XMLHttpRequest", "import(", "WebSocket"):
            assert call not in app, call

    def test_a_payee_name_cannot_close_the_script_element(self):
        """Payee names are free text from public filings, and one
        containing a closing tag would end the script early and blank
        the page."""
        html = graph_html.render(self._graph(), heading="Test")
        app = self._app_script(html)
        assert "A VENDOR" in app
        assert "</script>" not in app
        assert "<\\/script>" in app

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
        assert "commingled" in graph_html.render(self._graph(), heading="T")

    def test_a_tab_with_no_data_is_hidden_rather_than_empty(self):
        """An empty tab reads as 'nothing found' when the truth is 'that
        pattern was never run'."""
        html = graph_html.render(self._graph(), heading="T")
        assert 'data-tab="clusters" role="tab" data-empty="yes"' in html

    def test_view_tabs_populate_from_pattern_results(self):
        match = _match(
            "revolving_door",
            [{"committee_id": "SSFI", "committee_name": "Senate Finance", "chamber": "senate",
              "lobbyists": [{"lobbyist": "A Person", "route": "served the committee",
                             "via_member": None, "disclosed_position": "Counsel"}]}],
            {"registrant_name": "A Firm"},
        )
        html = graph_html.render(g.build([match]), matches=[match], heading="T")
        assert 'data-tab="revolving" role="tab" data-empty="no"' in html
        assert "Senate Finance" in html


class TestOverviewNarrative:
    """The overview states findings in prose before any graph is drawn.
    A force-directed hairball is raw material, not an analysis."""

    def test_an_identical_amount_cluster_is_called_out_as_a_lead(self):
        match = _match(
            "employer_contribution_clusters",
            [{"recipient_committee_id": "C1", "recipient": "A CAMPAIGN",
              "window_start": "2023-02-13", "donor_count": 2, "amounts_identical": True,
              "donors": [{"contributor": "A", "amount": 1000.0, "dates": ["2023-02-13"]},
                         {"contributor": "B", "amount": 1000.0, "dates": ["2023-02-13"]}]}],
            {"employer": "TESTCO", "recipient_concentration": []},
        )
        html = graph_html.render(g.build([match]), matches=[match], heading="T")
        assert "identical amounts to A CAMPAIGN" in html
        assert "lead to check, not a finding" in html

    def test_a_low_support_ratio_is_stated_without_a_verdict(self):
        match = _match(
            "candidate_support_ratio",
            [{"cycle": 2020, "receipts": 473371.0, "low_support": True,
              "candidate_and_party_share_reported": 12.85}],
            {"committee_id": "C1", "committee_name": "A PAC"},
        )
        html = graph_html.render(g.build([match]), matches=[match], heading="T")
        assert "No law sets a required ratio" in html

    def test_name_matched_entities_are_flagged_in_the_narrative(self):
        graph = g.ConnectionGraph()
        graph.add_node(g.Node(g.org_node_id("Some Vendor", "vendor"), "SOME VENDOR", "vendor"))
        html = graph_html.render(graph, heading="T")
        assert "matched by name, not identifier" in html


class TestBackerChain:
    """The shape a reader asks for: "a super PAC backed by X supported Y".

    Two disclosed hops that must never become one number.
    """

    def _chain(self):
        backers = _match(
            "committee_backers",
            [{"contributor": "AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE",
              "amount": 30_000_000.0, "share_of_itemised": 36.12,
              "kind": "organisation", "receipts": 4},
             *[{"contributor": f"TINY BACKER {i}", "amount": 100.0,
                "share_of_itemised": 0.01, "kind": "individual", "receipts": 1}
               for i in range(3)]],
            {"committee_id": "C00799031", "committee_name": "UDP",
             "itemised_total": 83_062_762.0, "top_backer_share": 36.12,
             "single_backer_dominant": False, "distinct_backers": 4},
        )
        overlap = _match(
            "common_vendor_overlap",
            [{"outside_committee_id": "C00799031", "outside_committee": "UDP",
              "reported_ie_amount": 16_471_909.0, "shared_vendors": []}],
            {"campaign_committee_id": "C00903039", "campaign_committee": "STEVENS"},
        )
        return g.build([backers, overlap])

    def test_the_two_hop_chain_is_found(self):
        graph = self._chain()
        aipac = g.org_node_id("AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE", "org")
        paths = graph.paths_between(aipac, "fec:C00903039")
        assert len(paths) == 1
        assert [e.relation for e in paths[0].edges] == [
            "funded", "spent independently to support",
        ]

    def test_each_hop_keeps_its_own_amount(self):
        graph = self._chain()
        aipac = g.org_node_id("AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE", "org")
        amounts = [e.amount for e in graph.paths_between(aipac, "fec:C00903039")[0].edges]
        assert amounts == [30_000_000.0, 16_471_909.0]

    def test_the_chain_offers_no_combined_total(self):
        """Adding the hops would claim AIPAC funded a specific
        expenditure. Receipts are commingled; it did not."""
        path = self._chain().paths_between(
            g.org_node_id("AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE", "org"),
            "fec:C00903039")[0]
        assert not hasattr(path, "total")
        assert "total" not in path.to_dict(self._chain())

    def test_immaterial_backers_are_left_off_the_graph(self):
        """The pattern returns the whole tail because it is real. Drawing
        it would put several hundred donor nodes on the canvas and hide
        the finding rather than show it."""
        graph = self._chain()
        assert not any("tiny-backer" in n for n in graph.nodes)
        assert graph.nodes["fec:C00799031"].detail["backers_total"] == 4
        assert graph.nodes["fec:C00799031"].detail["backers_shown"] == 1
