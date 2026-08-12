"""Tests for cross-source detection patterns.

Uses httpx mock transport to avoid hitting real APIs in tests.
"""

import pytest
import httpx

from packed.lda_client import LDAClient
from packed.openfec_client import OpenFECClient
from packed.patterns import (
    detect_lobbyist_contribution_corroboration,
    _names_roughly_match, _contributor_name, _two_year_period, _find_fec_match,
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

class TestNamesRoughlyMatch:
    def test_exact_match(self):
        assert _names_roughly_match("TEST PAC", "TEST PAC") is True

    def test_case_and_punctuation_insensitive(self):
        assert _names_roughly_match("Test, PAC!", "test pac") is True

    def test_partial_overlap_above_threshold(self):
        assert _names_roughly_match("FRENCH HILL FOR ARKANSAS", "FRENCH HILL FOR CONGRESS") is True

    def test_no_overlap(self):
        assert _names_roughly_match("ALPHA COMMITTEE", "OMEGA FUND") is False

    def test_none_inputs(self):
        assert _names_roughly_match(None, "TEST") is False
        assert _names_roughly_match("TEST", None) is False

    def test_abbreviation_vs_expanded_name(self):
        # Real-world case: LD-203 payee vs FEC committee name for the same PAC
        assert _names_roughly_match(
            "ARKANSAS LEADERSHIP PAC",
            "ARKANSAS FOR LEADERSHIP POLITICAL ACTION COMMITTEE (ARKPAC)",
        ) is True

    def test_generic_word_only_overlap_does_not_match(self):
        # Sharing only "COMMITTEE"/"PAC"-style words proves nothing
        assert _names_roughly_match("VICTORY COMMITTEE", "LEADERSHIP COMMITTEE FOR THE PAC") is False


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
