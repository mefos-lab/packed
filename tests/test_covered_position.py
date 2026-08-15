"""Tests for the covered_position parser.

Every string here is a real 2024 LDA disclosure or a lightly trimmed one.
The parser exists to read what filers actually write, so invented
examples would test the wrong grammar.

The parser's contract is that it *proposes*: it is allowed to emit a
candidate that turns out not to resolve, and it is not allowed to emit
something that would resolve to the wrong entity. So the tests below care
much more about false positives than about recall.
"""

import pytest

from packed import covered_position as cp


COMMITTEES = [
    {"committee_id": "HSAP", "name": "House Committee on Appropriations", "type": "house"},
    {"committee_id": "SSAP", "name": "Senate Committee on Appropriations", "type": "senate"},
    {"committee_id": "HSIF", "name": "House Committee on Energy and Commerce", "type": "house"},
    {"committee_id": "SSCM", "name": "Senate Committee on Commerce, Science, and Transportation", "type": "senate"},
    {"committee_id": "SSFI", "name": "Senate Committee on Finance", "type": "senate"},
    {"committee_id": "SSHR", "name": "Senate Committee on Health, Education, Labor, and Pensions", "type": "senate"},
    {"committee_id": "HSSY", "name": "House Committee on Science, Space, and Technology", "type": "house"},
    {"committee_id": "SSAF", "name": "Senate Committee on Agriculture, Nutrition, and Forestry", "type": "senate"},
]


class TestMemberExtraction:
    @pytest.mark.parametrize("text,expected", [
        ("Scheduler/special assistant, Rep. Raul Ruiz", ["Raul Ruiz"]),
        ("Senator Blunt - Chief of Staff", ["Blunt"]),
        ("Congressman Blunt - Chief of Staff", ["Blunt"]),
        ("Sr. Pol. Advsr., Sen. Crapo; Leg. Asst., Rep. Metcalf", ["Crapo", "Metcalf"]),
        ("Legislative Assistant, Representative Fleischmann.", ["Fleischmann"]),
        ("Rep. David Kustoff: Legislative Correspondent", ["David Kustoff"]),
        ("Chief of Staff, Rep. Frederica S. Wilson", ["Frederica S. Wilson"]),
    ])
    def test_extracts_named_members(self, text, expected):
        assert list(cp.parse(text).member_names) == expected

    def test_stops_a_name_before_the_next_job_title(self):
        """Filers run a name straight into the following role with no
        delimiter. Absorbing the role makes the name unresolvable."""
        text = ("Legislative Correspondent and Systems Administrator, "
                "Congressman Elijah E. Cummings Legislative Assistant and "
                "Systems Administrator")
        assert list(cp.parse(text).member_names) == ["Elijah E. Cummings"]

    def test_an_honorific_with_no_name_yields_nothing(self):
        """'Legislative Assistant to US Senator' names no one. Emitting
        a candidate here is how a parser invents a person."""
        assert cp.parse("Legislative Assistant to US Senator").member_names == ()

    def test_non_congressional_positions_yield_nothing(self):
        for text in ("Founder", "Executive Director", "CEQ AD; Commerce Dept Sr Adv; OMB PAD"):
            assert cp.parse(text).member_names == ()

    def test_repeated_mentions_are_reported_once(self):
        text = "Chief of Staff, Rep. Joe Barton; Special Assistant, Rep. Joe Barton"
        assert list(cp.parse(text).member_names) == ["Joe Barton"]


class TestCommitteeExtraction:
    @pytest.mark.parametrize("text,expected", [
        ("Professional Staff, Senate Appropriations Committee",
         ["Senate Appropriations Committee"]),
        ("Senior Counsel, House Committee on the Judiciary.",
         ["House Committee on the Judiciary"]),
    ])
    def test_extracts_committee_phrases(self, text, expected):
        assert list(cp.parse(text).committee_phrases) == expected

    def test_clause_boundaries_stop_a_phrase_bleeding(self):
        """'Health Policy Advisor' belongs to the job, not the committee.
        Letting it into the phrase made Senate Finance score equally
        against Senate HELP and turned a resolvable phrase ambiguous."""
        phrases = cp.parse("Health Policy Advisor, Senate Finance Committee").committee_phrases
        assert phrases == ("Senate Finance Committee",)
        assert [c["committee_id"] for c in cp.match_committees(phrases[0], COMMITTEES)] == ["SSFI"]

    def test_bare_committee_word_is_not_a_candidate(self):
        """A lone 'Cmte' names nothing, so counting it as a candidate
        would understate the resolution rate for no reason."""
        assert cp.parse("Deputy Staff Dir, Cmte").committee_phrases == ()

    def test_commissioner_is_not_a_committee(self):
        """'Comm' collides with Commerce and Commissioner, which is why
        it is not an accepted abbreviation for committee."""
        for text in ("Dept of Comm", "Office of FHA Comm", "Deputy Comm"):
            assert cp.parse(text).committee_phrases == ()

    def test_party_bodies_are_excluded(self):
        """Caucus and party organs read as committees but are not
        committees of either chamber, so no roster can match them."""
        for text in ("Senate Republican Policy Committee",
                     "the House Republican Conference Committee",
                     "Republican Study Cmte"):
            assert cp.parse(text).committee_phrases == ()


class TestCommitteeMatching:
    @pytest.mark.parametrize("phrase,expected", [
        ("Senate Appropriations Committee", "SSAP"),
        ("House Appropriations Cmte", "HSAP"),
        ("House Science Cmte", "HSSY"),
        ("Senate Commerce Cmte", "SSCM"),
    ])
    def test_resolves_a_chambered_phrase(self, phrase, expected):
        matches = cp.match_committees(phrase, COMMITTEES)
        assert [m["committee_id"] for m in matches] == [expected]

    @pytest.mark.parametrize("phrase,expected", [
        ("House E&C Cmte", "HSIF"),
        ("Senate Ag Cmte", "SSAF"),
        ("Senate Approps Cmte", "SSAP"),
        ("Senate HELP Committee", "SSHR"),
    ])
    def test_resolves_abbreviations(self, phrase, expected):
        """Filers abbreviate heavily and no substring match reaches
        these, so the table is what makes them readable at all."""
        matches = cp.match_committees(phrase, COMMITTEES)
        assert [m["committee_id"] for m in matches] == [expected]

    def test_a_phrase_naming_no_chamber_stays_ambiguous(self):
        """'Commerce Committee' really is two real committees. Picking
        one would be invention, so both come back and the caller reports
        it unresolved."""
        matches = cp.match_committees("Commerce Committee", COMMITTEES)
        assert {m["committee_id"] for m in matches} == {"HSIF", "SSCM"}

    def test_chamber_filters_an_otherwise_ambiguous_phrase(self):
        assert [m["committee_id"] for m in
                cp.match_committees("Committee on Appropriations", COMMITTEES)] != ["SSAP"]
        assert [m["committee_id"] for m in
                cp.match_committees("Senate Committee on Appropriations", COMMITTEES)] == ["SSAP"]

    def test_unknown_topic_matches_nothing(self):
        assert cp.match_committees("Senate Antitrust Subcommittee", COMMITTEES) == []


class TestWholeDisclosures:
    def test_a_multi_position_disclosure_yields_both_kinds(self):
        text = ("Deputy Chief of Staff, Rep. Lamar Smith/Professional Staff "
                "member, House Science Cmte; Legislative Director, Rep. Louie "
                "Gohmert")
        parsed = cp.parse(text)
        assert list(parsed.member_names) == ["Lamar Smith", "Louie Gohmert"]
        assert list(parsed.committee_phrases) == ["House Science Cmte"]
        assert [m["committee_id"] for m in
                cp.match_committees(parsed.committee_phrases[0], COMMITTEES)] == ["HSSY"]

    def test_empty_input_is_falsy(self):
        assert not cp.parse(None)
        assert not cp.parse("")
        assert not cp.parse("   ")

    def test_a_disclosure_with_no_congressional_tie_is_falsy(self):
        assert not cp.parse("CEQ AD; Commerce Dept Sr Adv; OMB PAD")
