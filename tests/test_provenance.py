"""Tests for the source registry.

The registry is data, so most of what can go wrong is structural: a
citation pointing at a source that was renamed, a stance typo, a pattern
that gained citations but kept a stale status. None of those raise on
their own — they just quietly produce a wrong claim about the evidence.
"""

import pytest

from packed import provenance as p
from packed.patterns import PatternMatch


class TestRegistryIntegrity:
    def test_registry_validates(self):
        """Every citation resolves and every stance is recognised."""
        assert p.validate() == []

    def test_every_built_pattern_has_an_entry(self):
        """A pattern without an entry reports no provenance at all,
        which reads as 'not checked' rather than 'ungrounded'."""
        import packed.patterns as patterns
        built = {
            n.replace("detect_", "")
            for n in dir(patterns)
            if n.startswith("detect_")
        }
        described = {x.pattern_name for x in p.all_patterns()}
        assert built <= described, f"no registry entry for {built - described}"

    def test_sources_carry_a_citation_and_url(self):
        for key, src in p.sources().items():
            assert src.get("citation", "").strip(), f"{key} has no citation"
            assert src.get("url", "").strip(), f"{key} has no url"

    def test_rejected_works_record_reasoning(self):
        """A rejected work is only useful if it says why."""
        for key, r in p.rejected().items():
            assert r.get("reason", "").strip(), f"{key} rejected without a reason"


class TestStatusConsistency:
    def test_status_matches_citations(self):
        """Status is a function of what cites the pattern, so the two
        cannot be allowed to drift apart."""
        for prov in p.all_patterns() + p.proposed_patterns():
            has_support = any(c.stance == "supports" for c in prov.citations)
            if prov.contradicted:
                assert prov.status == "CONTESTED", \
                    f"{prov.pattern_name} is contradicted but marked {prov.status}"
            elif has_support:
                assert prov.status == "SUPPORTED", \
                    f"{prov.pattern_name} has support but is marked {prov.status}"
            else:
                assert prov.status == "PROPOSED", \
                    f"{prov.pattern_name} is uncited but marked {prov.status}"

    def test_a_work_can_support_one_pattern_and_contradict_another(self):
        """The reason stance exists. Hall & Wayman supports the
        committee-seat framing and contradicts a votes-based pattern."""
        seats = p.for_pattern("lobbying_money_to_committee_seats")
        timing = next(x for x in p.proposed_patterns()
                      if x.pattern_name == "timing_correlation")
        supports = {c.source_key for c in seats.citations if c.stance == "supports"}
        against = {c.source_key for c in timing.citations if c.stance == "contradicts"}
        assert supports & against, "expected one work on both sides"

    def test_a_work_can_take_both_stances_on_one_pattern(self):
        """Enforcement files show a scheme is real and prosecuted while
        showing the obvious test for it looks the wrong way. Both
        readings come from one source, so the registry has to let a
        single work cite a single pattern twice at opposing stances."""
        prov = next(x for x in p.proposed_patterns()
                    if x.pattern_name == "foreign_national_contributions")
        by_stance = {}
        for c in prov.citations:
            by_stance.setdefault(c.stance, set()).add(c.source_key)
        assert by_stance.get("supports", set()) & by_stance.get("contradicts", set()), \
            "expected one source on both sides of the same pattern"
        assert prov.status == "CONTESTED"


class TestEnforcementSource:
    """MURs are the case-typology source, the analogue of FATF's
    typologies that ground sift. They ground claims differently from a
    study: the question is not what a scheme correlates with but whether
    a regulator has actually pursued it."""

    def test_registry_carries_an_enforcement_source(self):
        kinds = {s.get("kind") for s in p.sources().values()}
        assert "enforcement" in kinds, f"no enforcement source; kinds are {kinds}"

    def test_enforcement_sources_say_how_to_reach_the_records(self):
        """A typology source is only usable if the case files can be
        pulled — otherwise it is an assertion about cases, not a source."""
        for key, s in p.sources().items():
            if s.get("kind") == "enforcement":
                assert s.get("access", "").strip(), f"{key} has no access note"


class TestPatternMatchIntegration:
    def test_result_carries_provenance(self):
        m = PatternMatch("industry_concentration", "t", "INFO", "ACTIVE", "d", [])
        assert m.provenance["status"] == "SUPPORTED"
        assert m.provenance["citations"]

    def test_uncited_pattern_reports_honestly(self):
        """Silence would let a reader assume grounding that is absent."""
        m = PatternMatch("lobbyist_contribution_corroboration", "t", "INFO", "ACTIVE", "d", [])
        assert m.provenance["status"] == "PROPOSED"
        assert m.provenance["citations"] == []

    def test_unknown_pattern_has_no_provenance(self):
        m = PatternMatch("not_a_real_pattern", "t", "INFO", "ACTIVE", "d", [])
        assert m.provenance is None


class TestValidateCatchesProblems:
    def test_detects_unknown_source(self, monkeypatch):
        bad = ({"sources": {"known": {"citation": "x", "url": "u"}}},
               {"patterns": {"pat": {"status": "SUPPORTED", "citations": [
                   {"source": "missing", "stance": "supports", "because": "y"}]}}})
        monkeypatch.setattr(p, "_load", lambda: bad)
        assert any("unknown source" in x for x in p.validate())

    def test_detects_bad_stance(self, monkeypatch):
        bad = ({"sources": {"k": {"citation": "x", "url": "u"}}},
               {"patterns": {"pat": {"status": "SUPPORTED", "citations": [
                   {"source": "k", "stance": "endorses", "because": "y"}]}}})
        monkeypatch.setattr(p, "_load", lambda: bad)
        assert any("bad stance" in x for x in p.validate())
