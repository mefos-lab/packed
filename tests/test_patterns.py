"""Tests for cross-source detection patterns.

Uses httpx mock transport to avoid hitting real APIs in tests.
"""

import pytest
import httpx

from packed.lda_client import LDAClient
from packed.openfec_client import OpenFECClient
from packed.patterns import (
    detect_lobbyist_contribution_corroboration,
    detect_leadership_pac_transfers,
    detect_jfc_obscuring,
    _committee_names_match, _contributor_name, _two_year_period, _find_fec_match,
)
from tests.test_clients import MockTransport


def _lda_filing(contributor_name="JOHN DOE", payee_name="TEST COMMITTEE",
                 amount="500.00", date="2025-03-15", honoree_name="Test Candidate"):
    return {
        "filing_uuid": "11111111-1111-1111-1111-111111111111",
        "registrant": {"name": "TEST REGISTRANT", "contact_name": contributor_name},
        "lobbyist": None,
        "contribution_items": [{
            "contribution_type": "feca",
            "contributor_name": "SELF",
            "payee_name": payee_name,
            "honoree_name": honoree_name,
            "amount": amount,
            "date": date,
        }],
    }


def _fec_record(committee_name="TEST COMMITTEE", amount=500.0, date="2025-03-20"):
    return {
        "committee_id": "C00000001",
        "committee": {"name": committee_name},
        "contribution_receipt_amount": amount,
        "contribution_receipt_date": date,
        "pdf_url": "https://example.com/x.pdf",
    }


def _make_clients(lda_routes, fec_routes):
    lda = LDAClient(api_key="test_key")
    lda._client = httpx.AsyncClient(
        base_url="https://lda.gov/api/v1", transport=MockTransport(lda_routes),
    )
    fec = OpenFECClient(api_key="test_key")
    fec._client = httpx.AsyncClient(
        base_url="https://api.open.fec.gov/v1", transport=MockTransport(fec_routes),
    )
    return lda, fec


# =============================================================================
# Helper function tests
# =============================================================================

class TestCommitteeNamesMatch:
    def test_exact_match(self):
        assert _committee_names_match("TEST PAC", "TEST PAC") is True

    def test_case_and_punctuation_insensitive(self):
        assert _committee_names_match("Test, PAC!", "test pac") is True

    def test_partial_overlap_above_threshold(self):
        assert _committee_names_match("FRENCH HILL FOR ARKANSAS", "FRENCH HILL FOR CONGRESS") is True

    def test_no_overlap(self):
        assert _committee_names_match("ALPHA COMMITTEE", "OMEGA FUND") is False

    def test_none_inputs(self):
        assert _committee_names_match(None, "TEST") is False
        assert _committee_names_match("TEST", None) is False

    def test_abbreviation_vs_expanded_name(self):
        # Real-world case: LD-203 payee vs FEC committee name for the same PAC
        assert _committee_names_match(
            "ARKANSAS LEADERSHIP PAC",
            "ARKANSAS FOR LEADERSHIP POLITICAL ACTION COMMITTEE (ARKPAC)",
        ) is True

    def test_generic_word_only_overlap_does_not_match(self):
        # Sharing only "COMMITTEE"/"PAC"-style words proves nothing
        assert _committee_names_match("VICTORY COMMITTEE", "LEADERSHIP COMMITTEE FOR THE PAC") is False


class TestContributorName:
    def test_uses_lobbyist_when_present(self):
        filing = {"lobbyist": {"first_name": "JANE", "last_name": "SMITH"},
                   "registrant": {"contact_name": "OTHER PERSON"}}
        assert _contributor_name(filing) == "JANE SMITH"

    def test_falls_back_to_registrant_contact(self):
        filing = {"lobbyist": None, "registrant": {"contact_name": "HEATHER VALENTINE"}}
        assert _contributor_name(filing) == "HEATHER VALENTINE"

    def test_no_data_returns_none(self):
        assert _contributor_name({}) is None


class TestTwoYearPeriod:
    def test_odd_year_rounds_up(self):
        assert _two_year_period("2025-03-15") == 2026

    def test_even_year_stays(self):
        assert _two_year_period("2026-03-15") == 2026

    def test_invalid_date_returns_none(self):
        assert _two_year_period("not-a-date") is None
        assert _two_year_period(None) is None


class TestFindFecMatch:
    def test_finds_matching_record(self):
        records = [_fec_record()]
        match = _find_fec_match(records, "TEST COMMITTEE", 500.0, "2025-03-15")
        assert match is not None

    def test_amount_outside_tolerance_no_match(self):
        records = [_fec_record(amount=600.0)]
        match = _find_fec_match(records, "TEST COMMITTEE", 500.0, "2025-03-15")
        assert match is None

    def test_date_outside_window_no_match(self):
        records = [_fec_record(date="2025-08-01")]
        match = _find_fec_match(records, "TEST COMMITTEE", 500.0, "2025-03-15")
        assert match is None

    def test_committee_name_mismatch_no_match(self):
        records = [_fec_record(committee_name="UNRELATED PAC")]
        match = _find_fec_match(records, "TEST COMMITTEE", 500.0, "2025-03-15")
        assert match is None

    def test_empty_records_no_match(self):
        assert _find_fec_match([], "TEST COMMITTEE", 500.0, "2025-03-15") is None


# =============================================================================
# detect_lobbyist_contribution_corroboration tests
# =============================================================================

class TestDetectLobbyistContributionCorroboration:
    @pytest.mark.asyncio
    async def test_corroborated_match(self):
        lda_routes = {"/contributions/": {"json": {"results": [_lda_filing()]}}}
        fec_routes = {"/schedules/schedule_a/": {"json": {"results": [_fec_record()]}}}
        lda, fec = _make_clients(lda_routes, fec_routes)

        result = await detect_lobbyist_contribution_corroboration(lda, fec, registrant_name="test")

        assert result.stats["total_contribution_items"] == 1
        assert result.stats["corroborated"] == 1
        assert result.stats["unconfirmed"] == 0
        assert result.findings[0]["corroborated"] is True
        assert result.findings[0]["fec_match"]["committee_name"] == "TEST COMMITTEE"

    @pytest.mark.asyncio
    async def test_unconfirmed_when_no_fec_match(self):
        lda_routes = {"/contributions/": {"json": {"results": [_lda_filing()]}}}
        fec_routes = {"/schedules/schedule_a/": {"json": {"results": []}}}
        lda, fec = _make_clients(lda_routes, fec_routes)

        result = await detect_lobbyist_contribution_corroboration(lda, fec, registrant_name="test")

        assert result.stats["corroborated"] == 0
        assert result.stats["unconfirmed"] == 1
        assert result.findings[0]["corroborated"] is False
        assert result.findings[0]["fec_match"] is None

    @pytest.mark.asyncio
    async def test_skips_items_without_payee(self):
        filing = _lda_filing()
        filing["contribution_items"][0]["payee_name"] = None
        lda_routes = {"/contributions/": {"json": {"results": [filing]}}}
        fec_routes = {"/schedules/schedule_a/": {"json": {"results": []}}}
        lda, fec = _make_clients(lda_routes, fec_routes)

        result = await detect_lobbyist_contribution_corroboration(lda, fec, registrant_name="test")

        assert result.stats["total_contribution_items"] == 0

    @pytest.mark.asyncio
    async def test_skips_filing_without_contributor(self):
        filing = _lda_filing()
        filing["registrant"] = {"contact_name": None}
        filing["lobbyist"] = None
        lda_routes = {"/contributions/": {"json": {"results": [filing]}}}
        fec_routes = {"/schedules/schedule_a/": {"json": {"results": []}}}
        lda, fec = _make_clients(lda_routes, fec_routes)

        result = await detect_lobbyist_contribution_corroboration(lda, fec, registrant_name="test")

        assert result.stats["total_contribution_items"] == 0

    @pytest.mark.asyncio
    async def test_lda_fetch_failure_returns_error_status(self):
        lda_routes = {"/contributions/": {"status": 500, "json": {"detail": "error"}}}
        fec_routes = {}
        lda, fec = _make_clients(lda_routes, fec_routes)

        result = await detect_lobbyist_contribution_corroboration(lda, fec, registrant_name="test")

        assert result.status == "ERROR"
        assert result.findings == []
        assert len(result.warnings) == 1


# =============================================================================
# detect_leadership_pac_transfers tests
# =============================================================================

_DESIGNATION_DISPLAY = {"D": "Leadership PAC", "P": "Principal campaign committee"}


def _fec_committee(committee_id="C0LEAD01", name="TEST LEADERSHIP PAC", designation="D"):
    return {
        "committee_id": committee_id, "name": name, "designation": designation,
        "designation_full": _DESIGNATION_DISPLAY.get(designation, designation),
    }


def _sched_a_contribution(name="DONOR ONE", amount=5000.0, date="2025-01-01"):
    return {"contributor_name": name, "contribution_receipt_amount": amount, "contribution_receipt_date": date}


def _sched_b_transfer(recipient_id="C0CAND01", recipient_name="CANDIDATE ONE FOR CONGRESS", amount=2000.0):
    return {
        "recipient_committee_id": recipient_id,
        "recipient_committee": {"name": recipient_name},
        "recipient_name": recipient_name,
        "disbursement_amount": amount,
    }


def _sched_b_vendor_payment(amount=500.0):
    return {"recipient_committee_id": None, "recipient_name": "OFFICE SUPPLY CO", "disbursement_amount": amount}


def _make_fec_client(fec_routes):
    fec = OpenFECClient(api_key="test_key")
    fec._client = httpx.AsyncClient(
        base_url="https://api.open.fec.gov/v1", transport=MockTransport(fec_routes),
    )
    return fec


class TestDetectLeadershipPacTransfers:
    @pytest.mark.asyncio
    async def test_resolves_committee_by_name(self):
        fec_routes = {
            "/committees/": {"json": {"results": [_fec_committee()]}},
            "/committee/C0LEAD01/": {"json": {"results": [_fec_committee()]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": []}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(fec, committee_name="test leadership pac")
        assert result.stats["committee_id"] == "C0LEAD01"
        assert result.stats["committee_name"] == "TEST LEADERSHIP PAC"

    @pytest.mark.asyncio
    async def test_requires_committee_id_or_name(self):
        fec = _make_fec_client({})
        result = await detect_leadership_pac_transfers(fec)
        assert result.status == "ERROR"

    @pytest.mark.asyncio
    async def test_no_committee_found_by_name(self):
        fec_routes = {"/committees/": {"json": {"results": []}}}
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(fec, committee_name="nonexistent")
        assert result.status == "ERROR"

    @pytest.mark.asyncio
    async def test_filters_out_vendor_payments(self):
        fec_routes = {
            "/committee/C0LEAD01/": {"json": {"results": [_fec_committee()]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": [_sched_b_transfer(), _sched_b_vendor_payment()]}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(fec, committee_id="C0LEAD01")
        assert len(result.findings) == 1
        assert result.findings[0]["recipient_committee_id"] == "C0CAND01"

    @pytest.mark.asyncio
    async def test_aggregates_multiple_transfers_to_same_recipient(self):
        fec_routes = {
            "/committee/C0LEAD01/": {"json": {"results": [_fec_committee()]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": [
                _sched_b_transfer(amount=1000.0),
                _sched_b_transfer(amount=1500.0),
            ]}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(fec, committee_id="C0LEAD01")
        assert len(result.findings) == 1
        assert result.findings[0]["total_amount"] == 2500.0
        assert result.findings[0]["transaction_count"] == 2

    @pytest.mark.asyncio
    async def test_min_transfer_amount_filter(self):
        fec_routes = {
            "/committee/C0LEAD01/": {"json": {"results": [_fec_committee()]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": [
                _sched_b_transfer(recipient_id="C0SMALL", amount=100.0),
                _sched_b_transfer(recipient_id="C0BIG", amount=5000.0),
            ]}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(
            fec, committee_id="C0LEAD01", min_transfer_amount=1000.0,
        )
        assert len(result.findings) == 1
        assert result.findings[0]["recipient_committee_id"] == "C0BIG"

    @pytest.mark.asyncio
    async def test_top_contributors_populated(self):
        fec_routes = {
            "/committee/C0LEAD01/": {"json": {"results": [_fec_committee()]}},
            "/schedules/schedule_a/": {"json": {"results": [
                _sched_a_contribution(name="DONOR ONE", amount=5000.0),
                _sched_a_contribution(name="DONOR TWO", amount=1000.0),
            ]}},
            "/schedules/schedule_b/": {"json": {"results": []}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(fec, committee_id="C0LEAD01")
        assert result.stats["top_contributors"][0]["contributor_name"] == "DONOR ONE"

    @pytest.mark.asyncio
    async def test_warns_when_not_a_leadership_pac(self):
        fec_routes = {
            "/committee/C0OTHER01/": {"json": {"results": [_fec_committee(committee_id="C0OTHER01", designation="P")]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": []}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_leadership_pac_transfers(fec, committee_id="C0OTHER01")
        assert len(result.warnings) == 1


# =============================================================================
# detect_jfc_obscuring tests
#
# Shares _trace_committee_money_flow with leadership_pac_transfers, so
# the vendor-filtering/aggregation/min-amount edge cases are already
# covered above. These tests confirm the JFC-specific wiring: it
# resolves by designation "J" (not "D"), and reports the right
# pattern_name/title.
# =============================================================================

class TestDetectJfcObscuring:
    @pytest.mark.asyncio
    async def test_resolves_by_jfc_designation(self):
        fec_routes = {
            "/committees/": {"json": {"results": [_fec_committee(
                committee_id="C0JFC01", name="TEST VICTORY FUND", designation="J",
            )]}},
            "/committee/C0JFC01/": {"json": {"results": [_fec_committee(
                committee_id="C0JFC01", name="TEST VICTORY FUND", designation="J",
            )]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": []}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_jfc_obscuring(fec, committee_name="test victory fund")
        assert result.stats["committee_id"] == "C0JFC01"
        assert result.pattern_name == "jfc_obscuring"
        assert result.title == "Joint Fundraising Committee Fund Routing"
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_traces_splits_to_participant_committees(self):
        fec_routes = {
            "/committee/C0JFC01/": {"json": {"results": [_fec_committee(
                committee_id="C0JFC01", name="TEST VICTORY FUND", designation="J",
            )]}},
            "/schedules/schedule_a/": {"json": {"results": [
                _sched_a_contribution(name="BIG DONOR", amount=10000.0),
            ]}},
            "/schedules/schedule_b/": {"json": {"results": [
                _sched_b_transfer(recipient_id="C0PARTICIPANT1", amount=3300.0),
                _sched_b_transfer(recipient_id="C0PARTICIPANT2", amount=3300.0),
                _sched_b_vendor_payment(),
            ]}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_jfc_obscuring(fec, committee_id="C0JFC01")
        assert result.stats["distinct_recipient_committees"] == 2
        assert {f["recipient_committee_id"] for f in result.findings} == {"C0PARTICIPANT1", "C0PARTICIPANT2"}

    @pytest.mark.asyncio
    async def test_warns_when_not_actually_a_jfc(self):
        fec_routes = {
            "/committee/C0LEAD01/": {"json": {"results": [_fec_committee(designation="D")]}},
            "/schedules/schedule_a/": {"json": {"results": []}},
            "/schedules/schedule_b/": {"json": {"results": []}},
        }
        fec = _make_fec_client(fec_routes)
        result = await detect_jfc_obscuring(fec, committee_id="C0LEAD01")
        assert len(result.warnings) == 1
        assert "Joint Fundraising Committee" in result.warnings[0]


# =============================================================================
# detect_lobbying_money_to_committee_seats tests
# =============================================================================

from packed.patterns import detect_lobbying_money_to_committee_seats
from packed.congress_legislators_client import CongressLegislatorsClient
from tests.test_congress_legislators import (
    YamlMockTransport, COMMITTEES_YAML, MEMBERSHIP_YAML, LEGISLATORS_YAML,
)


def _ld203_filing(items):
    return {
        "filing_uuid": "33333333-3333-3333-3333-333333333333",
        "registrant": {"name": "TEST FIRM"},
        "contribution_items": items,
    }


def _item(honoree, amount="1000.00"):
    return {"payee_name": "SOME COMMITTEE", "honoree_name": honoree, "amount": amount}


def _make_lda_and_congress(lda_routes):
    lda = LDAClient(api_key="test_key")
    lda._client = httpx.AsyncClient(
        base_url="https://lda.gov/api/v1", transport=MockTransport(lda_routes),
    )
    cong = CongressLegislatorsClient()
    cong._client = httpx.AsyncClient(
        base_url="https://raw.githubusercontent.com/unitedstates/congress-legislators/main",
        transport=YamlMockTransport({
            "committee-membership-current.yaml": MEMBERSHIP_YAML,
            "committees-current.yaml": COMMITTEES_YAML,
            "legislators-current.yaml": LEGISLATORS_YAML,
        }),
    )
    return lda, cong


class TestDetectLobbyingMoneyToCommitteeSeats:
    @pytest.mark.asyncio
    async def test_aggregates_by_committee(self):
        lda_routes = {"/contributions/": {"json": {"results": [
            _ld203_filing([_item("Test Chairman", "5000.00")]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(lda, cong, registrant_name="test firm")
        assert r.status == "ACTIVE"
        ssaf = next(f for f in r.findings if f["committee_id"] == "SSAF")
        assert ssaf["total_amount"] == 5000.0
        assert "Test Chairman (Chairman)" in ssaf["chairs_or_ranking_members"]

    @pytest.mark.asyncio
    async def test_title_prefix_is_stripped_when_resolving(self):
        """LD-203 honoree names carry titles like 'Sen.' / 'Rep.'."""
        lda_routes = {"/contributions/": {"json": {"results": [
            _ld203_filing([_item("Sen. Test Chairman", "2500.00")]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(lda, cong, registrant_name="test firm")
        assert r.stats["resolved_honorees"] == 1

    @pytest.mark.asyncio
    async def test_unresolvable_honoree_tracked_not_dropped(self):
        """Party committees (DCCC etc.) aren't people — must be surfaced."""
        lda_routes = {"/contributions/": {"json": {"results": [
            _ld203_filing([_item("DCCC", "10000.00")]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(lda, cong, registrant_name="test firm")
        assert r.stats["unresolved_amount"] == 10000.0
        assert "DCCC" in r.stats["unresolved_honorees"]
        assert r.findings == []

    @pytest.mark.asyncio
    async def test_subcommittees_excluded_by_default(self):
        lda_routes = {"/contributions/": {"json": {"results": [
            _ld203_filing([_item("Test Member", "1000.00")]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(lda, cong, registrant_name="test firm")
        assert all(not f["is_subcommittee"] for f in r.findings)

    @pytest.mark.asyncio
    async def test_subcommittees_included_when_requested(self):
        lda_routes = {"/contributions/": {"json": {"results": [
            _ld203_filing([_item("Test Member", "1000.00")]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(
            lda, cong, registrant_name="test firm", include_subcommittees=True,
        )
        assert any(f["is_subcommittee"] for f in r.findings)

    @pytest.mark.asyncio
    async def test_one_dollar_counted_per_committee_seat(self):
        """A recipient on N committees credits the amount to each — the
        documented reason committee totals exceed the contribution total."""
        lda_routes = {"/contributions/": {"json": {"results": [
            _ld203_filing([_item("Test Member", "1000.00")]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(
            lda, cong, registrant_name="test firm", include_subcommittees=True,
        )
        assert r.stats["total_amount"] == 1000.0
        assert sum(f["total_amount"] for f in r.findings) == 2000.0  # SSAF + SSAF13

    @pytest.mark.asyncio
    async def test_always_warns_about_current_only_rosters(self):
        lda_routes = {"/contributions/": {"json": {"results": []}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(lda, cong, registrant_name="test firm")
        assert any("current-only" in w for w in r.warnings)

    @pytest.mark.asyncio
    async def test_lda_failure_returns_error(self):
        lda_routes = {"/contributions/": {"status": 500, "json": {"detail": "err"}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_lobbying_money_to_committee_seats(lda, cong, registrant_name="test firm")
        assert r.status == "ERROR"


# =============================================================================
# detect_industry_concentration tests
# =============================================================================

from packed.patterns import detect_industry_concentration


def _sched_b_to_candidate_cmte(recipient_id="C0CAND01", cand_ids=("H2TEST001",),
                                name="CANDIDATE ONE FOR CONGRESS", amount=5000.0):
    return {
        "recipient_committee_id": recipient_id,
        "recipient_committee": {"name": name, "candidate_ids": list(cand_ids)},
        "recipient_name": name,
        "disbursement_amount": amount,
    }


def _sched_b_to_intermediary(recipient_id="C0LEAD99", name="SOME LEADERSHIP PAC", amount=7000.0):
    """A committee with no candidate of its own — cannot be followed."""
    return {
        "recipient_committee_id": recipient_id,
        "recipient_committee": {"name": name, "candidate_ids": []},
        "recipient_name": name,
        "disbursement_amount": amount,
    }


def _make_fec_and_congress(fec_routes):
    fec = OpenFECClient(api_key="test_key")
    fec._client = httpx.AsyncClient(
        base_url="https://api.open.fec.gov/v1", transport=MockTransport(fec_routes),
    )
    cong = CongressLegislatorsClient()
    cong._client = httpx.AsyncClient(
        base_url="https://raw.githubusercontent.com/unitedstates/congress-legislators/main",
        transport=YamlMockTransport({
            "committee-membership-current.yaml": MEMBERSHIP_YAML,
            "committees-current.yaml": COMMITTEES_YAML,
            "legislators-current.yaml": LEGISLATORS_YAML,
        }),
    )
    return fec, cong


_PAC = {"committee_id": "C0PAC001", "name": "TEST INDUSTRY PAC",
        "designation_full": "Unauthorized", "committee_type_full": "PAC"}


class TestDetectIndustryConcentration:
    @pytest.mark.asyncio
    async def test_attributes_via_candidate_id_not_name(self):
        """The join is identifier-based end to end."""
        fec_routes = {
            "/committee/C0PAC001/": {"json": {"results": [_PAC]}},
            "/schedules/schedule_b/": {"json": {"results": [_sched_b_to_candidate_cmte()]}},
        }
        fec, cong = _make_fec_and_congress(fec_routes)
        r = await detect_industry_concentration(fec, cong, committee_id="C0PAC001")
        assert r.status == "ACTIVE"
        assert r.stats["attributed_to_sitting_members"] == 5000.0
        ssaf = next(f for f in r.findings if f["committee_id"] == "SSAF")
        assert "Test Chairman" in ssaf["recipients"]

    @pytest.mark.asyncio
    async def test_intermediary_reported_not_dropped(self):
        """Money to a committee with no candidate must surface, not vanish."""
        fec_routes = {
            "/committee/C0PAC001/": {"json": {"results": [_PAC]}},
            "/schedules/schedule_b/": {"json": {"results": [_sched_b_to_intermediary()]}},
        }
        fec, cong = _make_fec_and_congress(fec_routes)
        r = await detect_industry_concentration(fec, cong, committee_id="C0PAC001")
        assert r.stats["attributed_to_sitting_members"] == 0.0
        assert r.stats["unattributed_amount"] == 7000.0
        assert r.stats["unattributed_recipients"][0]["recipient"] == "SOME LEADERSHIP PAC"
        assert r.findings == []

    @pytest.mark.asyncio
    async def test_vendor_spending_excluded_from_committee_total(self):
        fec_routes = {
            "/committee/C0PAC001/": {"json": {"results": [_PAC]}},
            "/schedules/schedule_b/": {"json": {"results": [
                _sched_b_to_candidate_cmte(amount=1000.0),
                _sched_b_vendor_payment(amount=400.0),
            ]}},
        }
        fec, cong = _make_fec_and_congress(fec_routes)
        r = await detect_industry_concentration(fec, cong, committee_id="C0PAC001")
        assert r.stats["total_disbursed"] == 1400.0
        assert r.stats["to_other_committees"] == 1000.0

    @pytest.mark.asyncio
    async def test_unseated_candidate_is_unattributed(self):
        """A candidate ID with no sitting legislator must not be attributed."""
        fec_routes = {
            "/committee/C0PAC001/": {"json": {"results": [_PAC]}},
            "/schedules/schedule_b/": {"json": {"results": [
                _sched_b_to_candidate_cmte(cand_ids=("H9NOBODY",), name="LOST RACE CMTE", amount=2000.0),
            ]}},
        }
        fec, cong = _make_fec_and_congress(fec_routes)
        r = await detect_industry_concentration(fec, cong, committee_id="C0PAC001")
        assert r.stats["attributed_to_sitting_members"] == 0.0
        assert r.stats["unattributed_amount"] == 2000.0

    @pytest.mark.asyncio
    async def test_min_amount_filter(self):
        fec_routes = {
            "/committee/C0PAC001/": {"json": {"results": [_PAC]}},
            "/schedules/schedule_b/": {"json": {"results": [
                _sched_b_to_candidate_cmte(amount=100.0),
                _sched_b_to_candidate_cmte(amount=9000.0),
            ]}},
        }
        fec, cong = _make_fec_and_congress(fec_routes)
        r = await detect_industry_concentration(fec, cong, committee_id="C0PAC001", min_amount=1000.0)
        assert r.stats["total_disbursed"] == 9000.0

    @pytest.mark.asyncio
    async def test_requires_committee_id_or_name(self):
        fec, cong = _make_fec_and_congress({})
        r = await detect_industry_concentration(fec, cong)
        assert r.status == "ERROR"

    @pytest.mark.asyncio
    async def test_always_warns_about_intermediaries_and_current_rosters(self):
        fec_routes = {
            "/committee/C0PAC001/": {"json": {"results": [_PAC]}},
            "/schedules/schedule_b/": {"json": {"results": []}},
        }
        fec, cong = _make_fec_and_congress(fec_routes)
        r = await detect_industry_concentration(fec, cong, committee_id="C0PAC001")
        assert any("current-only" in w for w in r.warnings)
        assert any("intermediary" in w for w in r.warnings)


# =============================================================================
# detect_revolving_door tests
# =============================================================================

from packed.patterns import detect_revolving_door


def _lda_filing_with_lobbyists(lobbyists):
    """An LD-2 shaped filing. covered_position sits on the row wrapping
    the lobbyist, not on the lobbyist record itself."""
    return {
        "filing_uuid": "44444444-4444-4444-4444-444444444444",
        "registrant": {"name": "TEST FIRM"},
        "client": {"name": "TEST CLIENT"},
        "lobbying_activities": [{
            "general_issue_code": "TAX",
            "lobbyists": [
                {"lobbyist": {"id": lid, "first_name": first, "last_name": last},
                 "covered_position": position, "new": False}
                for lid, first, last, position in lobbyists
            ],
        }],
    }


class TestDetectRevolvingDoor:
    @pytest.mark.asyncio
    async def test_member_route_credits_the_members_committees(self):
        """A lobbyist who staffed a sitting member is credited to the
        seats that member holds."""
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([
                (1, "JANE", "DOE", "Chief of Staff, Sen. Test Chairman"),
            ]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert r.status == "ACTIVE"
        ssaf = next(f for f in r.findings if f["committee_id"] == "SSAF")
        assert ssaf["lobbyist_count"] == 1
        assert ssaf["lobbyists"][0]["route"] == "staffed a sitting member"
        assert ssaf["lobbyists"][0]["via_member"] == "Test Chairman"

    @pytest.mark.asyncio
    async def test_committee_route_is_labelled_distinctly(self):
        """Serving the committee is a different, stronger claim than
        staffing someone who sits on it, so the routes are not merged."""
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([
                (2, "JOHN", "ROE", "Professional Staff, Senate Agriculture Committee"),
            ]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        ssaf = next(f for f in r.findings if f["committee_id"] == "SSAF")
        assert ssaf["lobbyists"][0]["route"] == "served the committee"
        assert ssaf["lobbyists"][0]["via_member"] is None

    @pytest.mark.asyncio
    async def test_direct_service_wins_when_both_routes_reach_one_committee(self):
        """Reaching a committee twice is one tie, reported on the
        stronger route rather than double-counted."""
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([
                (3, "ANNA", "POE",
                 "Chief of Staff, Sen. Test Chairman; Counsel, Senate Agriculture Committee"),
            ]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        ssaf = next(f for f in r.findings if f["committee_id"] == "SSAF")
        assert ssaf["lobbyist_count"] == 1
        assert ssaf["lobbyists"][0]["route"] == "served the committee"

    @pytest.mark.asyncio
    async def test_a_former_member_is_reported_unresolved_not_guessed(self):
        """Only current rosters are consulted, so a departed member does
        not resolve. Reporting the name is what keeps the gap visible."""
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([
                (4, "SAM", "COE", "Legislative Director, Rep. Someone Retired"),
            ]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert r.findings == []
        assert "Someone Retired" in r.stats["unresolved_member_names"]
        assert r.stats["with_covered_position"] == 1
        assert r.stats["with_resolved_tie"] == 0

    @pytest.mark.asyncio
    async def test_lobbyists_without_a_disclosure_are_counted_but_not_tied(self):
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([
                (5, "NO", "POSITION", None),
                (6, "HAS", "POSITION", "Chief of Staff, Sen. Test Chairman"),
            ]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert r.stats["distinct_lobbyists"] == 2
        assert r.stats["with_covered_position"] == 1

    @pytest.mark.asyncio
    async def test_a_lobbyist_repeated_across_filings_is_counted_once(self):
        """The same person appears on every filing they work on."""
        filing = _lda_filing_with_lobbyists([
            (7, "REPEAT", "PERSON", "Chief of Staff, Sen. Test Chairman"),
        ])
        lda_routes = {"/filings/": {"json": {"results": [filing, filing, filing]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert r.stats["distinct_lobbyists"] == 1
        assert r.stats["lobbyist_rows"] == 3
        ssaf = next(f for f in r.findings if f["committee_id"] == "SSAF")
        assert ssaf["lobbyist_count"] == 1

    @pytest.mark.asyncio
    async def test_a_position_disclosed_on_only_one_filing_is_kept(self):
        """Filers leave the field blank on some filings for a lobbyist
        who disclosed it on others. Taking the last row seen would drop
        the disclosure."""
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([(8, "PART", "TIME", "Chief of Staff, Sen. Test Chairman")]),
            _lda_filing_with_lobbyists([(8, "PART", "TIME", None)]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert r.stats["with_covered_position"] == 1
        assert r.findings

    @pytest.mark.asyncio
    async def test_requires_a_registrant_or_client(self):
        lda, cong = _make_lda_and_congress({})
        r = await detect_revolving_door(lda, cong)
        assert r.status == "ERROR"

    @pytest.mark.asyncio
    async def test_subcommittees_are_excluded_by_default(self):
        lda_routes = {"/filings/": {"json": {"results": [
            _lda_filing_with_lobbyists([
                (9, "SUB", "PERSON", "Staff, Risk Management Subcommittee"),
            ]),
        ]}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        default = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert default.findings == []

        lda2, cong2 = _make_lda_and_congress(lda_routes)
        withsubs = await detect_revolving_door(
            lda2, cong2, registrant_name="test firm", include_subcommittees=True,
        )
        assert [f["committee_id"] for f in withsubs.findings] == ["SSAF13"]
        assert withsubs.findings[0]["is_subcommittee"] is True

    @pytest.mark.asyncio
    async def test_always_warns_about_coverage_limits(self):
        """The floor-not-census caveats have to travel with the result;
        a reader seeing three committees must not read it as all of them."""
        lda_routes = {"/filings/": {"json": {"results": []}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert any("absence is not evidence" in w for w in r.warnings)
        assert any("left office" in w for w in r.warnings)

    @pytest.mark.asyncio
    async def test_carries_provenance_now_that_it_is_built(self):
        lda_routes = {"/filings/": {"json": {"results": []}}}
        lda, cong = _make_lda_and_congress(lda_routes)
        r = await detect_revolving_door(lda, cong, registrant_name="test firm")
        assert r.provenance is not None
        assert r.provenance["status"] == "SUPPORTED"


# =============================================================================
# detect_employer_contribution_clusters tests
# =============================================================================

from packed.patterns import detect_employer_contribution_clusters


def _sched_a(name, amount, date, committee_name="TEST CAMPAIGN", committee_id="C0CAMP01"):
    return {
        "contributor_name": name,
        "contributor_employer": "TESTCO",
        "contribution_receipt_amount": amount,
        "contribution_receipt_date": f"{date}T00:00:00",
        "committee_id": committee_id,
        "committee": {"name": committee_name},
    }


def _make_fec(rows):
    fec = OpenFECClient(api_key="test_key")
    fec._client = httpx.AsyncClient(
        base_url="https://api.open.fec.gov/v1",
        transport=MockTransport({"/schedules/schedule_a/": {"json": {
            "results": rows, "pagination": {"last_indexes": {}},
        }}}),
    )
    return fec


class TestDetectEmployerContributionClusters:
    @pytest.mark.asyncio
    async def test_two_donors_same_day_is_a_cluster(self):
        """The default is two, not three. Requiring three erased the
        case this pattern is grounded in — MUR 8363 ran two at a time."""
        fec = _make_fec([
            _sched_a("MEIER, DAVID", 1000.0, "2023-02-13"),
            _sched_a("SAUER, PETER", 1000.0, "2023-02-13"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.status == "ACTIVE"
        assert len(r.findings) == 1
        assert r.findings[0]["donor_count"] == 2
        assert r.findings[0]["amounts_identical"] is True

    @pytest.mark.asyncio
    async def test_identical_amounts_are_flagged_apart_from_varied_ones(self):
        """Amount uniformity is the only discriminator available, so it
        must not be buried in the donor list."""
        fec = _make_fec([
            _sched_a("A ONE", 1000.0, "2023-02-13"),
            _sched_a("B TWO", 2500.0, "2023-02-13"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.findings[0]["amounts_identical"] is False
        assert r.stats["clusters_with_identical_amounts"] == 0

    @pytest.mark.asyncio
    async def test_one_donor_alone_is_not_a_cluster(self):
        fec = _make_fec([_sched_a("SOLO PERSON", 2000.0, "2023-02-13")])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.findings == []

    @pytest.mark.asyncio
    async def test_contributions_outside_the_window_do_not_cluster(self):
        fec = _make_fec([
            _sched_a("A ONE", 1000.0, "2023-02-13"),
            _sched_a("B TWO", 1000.0, "2023-03-20"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.findings == []

    @pytest.mark.asyncio
    async def test_different_recipients_do_not_cluster_together(self):
        fec = _make_fec([
            _sched_a("A ONE", 1000.0, "2023-02-13", "CAMPAIGN ONE", "C0AAA"),
            _sched_a("B TWO", 1000.0, "2023-02-13", "CAMPAIGN TWO", "C0BBB"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.findings == []

    @pytest.mark.asyncio
    async def test_pass_through_committees_are_excluded_by_default(self):
        """Three quarters of one real employer's rows were ActBlue
        recurring donations, which drowned the signal entirely."""
        fec = _make_fec([
            _sched_a("A ONE", 1000.0, "2023-02-13", "ACTBLUE", "C0ACT"),
            _sched_a("B TWO", 1000.0, "2023-02-13", "ACTBLUE", "C0ACT"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.findings == []
        assert r.stats["pass_through_rows_excluded"] == 2

        fec2 = _make_fec([
            _sched_a("A ONE", 1000.0, "2023-02-13", "ACTBLUE", "C0ACT"),
            _sched_a("B TWO", 1000.0, "2023-02-13", "ACTBLUE", "C0ACT"),
        ])
        r2 = await detect_employer_contribution_clusters(
            fec2, employer="TESTCO", include_pass_through=True,
        )
        assert len(r2.findings) == 1

    @pytest.mark.asyncio
    async def test_small_donations_are_below_the_floor(self):
        fec = _make_fec([
            _sched_a("A ONE", 10.0, "2023-02-13"),
            _sched_a("B TWO", 10.0, "2023-02-13"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.findings == []
        assert r.stats["below_floor_rows_excluded"] == 2

    @pytest.mark.asyncio
    async def test_a_cluster_is_reported_once_not_at_every_offset(self):
        """A sliding window re-finds the same event from each starting
        contribution, so one three-donor event would otherwise also be
        reported as two separate two-donor events."""
        fec = _make_fec([
            _sched_a("A ONE", 2300.0, "2007-05-08"),
            _sched_a("B TWO", 2300.0, "2007-05-08"),
            _sched_a("C THREE", 2300.0, "2007-05-08"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert len(r.findings) == 1
        assert r.findings[0]["donor_count"] == 3

    @pytest.mark.asyncio
    async def test_recipient_concentration_counts_everything_not_just_clusters(self):
        """The concentration view answers a different question and must
        not inherit the cluster filters — only the pass-through rule."""
        fec = _make_fec([
            _sched_a("A ONE", 10.0, "2023-02-13"),
            _sched_a("B TWO", 5000.0, "2021-01-05"),
        ])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        total = next(c for c in r.stats["recipient_concentration"]
                     if c["recipient_committee_id"] == "C0CAMP01")
        assert total["total_amount"] == 5010.0
        assert total["donor_count"] == 2

    @pytest.mark.asyncio
    async def test_always_warns_that_bundling_looks_the_same(self):
        """The whole result is a lead. A reader must not be able to see
        the findings without seeing that."""
        fec = _make_fec([])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert any("bundling" in w for w in r.warnings)
        assert any("floor" in w for w in r.warnings)

    @pytest.mark.asyncio
    async def test_carries_provenance(self):
        fec = _make_fec([])
        r = await detect_employer_contribution_clusters(fec, employer="TESTCO")
        assert r.provenance["status"] == "SUPPORTED"
        assert any(c["source"] == "fec_murs" for c in r.provenance["citations"])
