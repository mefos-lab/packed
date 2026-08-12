"""Tests for API clients.

Uses httpx mock transport to avoid hitting real APIs in tests.
"""

import pytest
import httpx
from packed.openfec_client import OpenFECClient
from packed.lda_client import LDAClient
from packed.propublica_client import ProPublicaNPEClient


# =============================================================================
# Mock transport
# =============================================================================

class MockTransport(httpx.AsyncBaseTransport):
    """Returns canned responses based on URL path."""

    def __init__(self, routes: dict[str, dict]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        # Prefer longest (most specific) match
        best_match = None
        best_len = -1
        for pattern, response_data in self.routes.items():
            if pattern in path and len(pattern) > best_len:
                best_match = response_data
                best_len = len(pattern)
        if best_match is not None:
            return httpx.Response(
                status_code=best_match.get("status", 200),
                json=best_match.get("json", {}),
            )
        return httpx.Response(status_code=404, json={"error": "not found"})


# =============================================================================
# OpenFECClient tests
# =============================================================================

class TestOpenFECClient:
    @pytest.fixture
    def mock_routes(self):
        return {
            "/candidates/search/": {
                "json": {"results": [{"candidate_id": "H0TEST01", "name": "TEST CANDIDATE"}]},
            },
            "/candidate/H0TEST01/": {
                "json": {"results": [{"candidate_id": "H0TEST01", "name": "TEST CANDIDATE"}]},
            },
            "/committees/": {
                "json": {"results": [{"committee_id": "C0TEST01", "name": "TEST PAC"}]},
            },
            "/committee/C0TEST01/": {
                "json": {"results": [{"committee_id": "C0TEST01", "name": "TEST PAC"}]},
            },
            "/schedules/schedule_a/": {
                "json": {"results": [{"contributor_name": "TEST DONOR", "contribution_receipt_amount": 100.0}]},
            },
            "/schedules/schedule_b/": {
                "json": {"results": [{
                    "recipient_name": "TEST VENDOR",
                    "recipient_committee_id": "C0TEST02",
                    "disbursement_amount": 250.0,
                }]},
            },
            "/error/": {
                "status": 500,
                "json": {"message": "Server Error"},
            },
        }

    @pytest.fixture
    def client(self, mock_routes):
        transport = MockTransport(mock_routes)
        c = OpenFECClient(api_key="test_key")
        c._client = httpx.AsyncClient(
            base_url="https://api.open.fec.gov/v1",
            transport=transport,
        )
        return c

    @pytest.mark.asyncio
    async def test_search_candidates(self, client):
        result = await client.search_candidates(q="test")
        assert result["results"][0]["name"] == "TEST CANDIDATE"

    @pytest.mark.asyncio
    async def test_search_candidates_with_filters(self, client):
        result = await client.search_candidates(q="test", office="H", cycle=2026, state="CA", party="DEM")
        assert "results" in result

    @pytest.mark.asyncio
    async def test_get_candidate(self, client):
        result = await client.get_candidate("H0TEST01")
        assert result["results"][0]["candidate_id"] == "H0TEST01"

    @pytest.mark.asyncio
    async def test_search_committees(self, client):
        result = await client.search_committees(q="test pac")
        assert result["results"][0]["name"] == "TEST PAC"

    @pytest.mark.asyncio
    async def test_get_committee(self, client):
        result = await client.get_committee("C0TEST01")
        assert result["results"][0]["committee_id"] == "C0TEST01"

    @pytest.mark.asyncio
    async def test_search_contributions(self, client):
        result = await client.search_contributions(committee_id="C0TEST01")
        assert result["results"][0]["contributor_name"] == "TEST DONOR"

    @pytest.mark.asyncio
    async def test_search_disbursements(self, client):
        result = await client.search_disbursements(committee_id="C0TEST01")
        assert result["results"][0]["recipient_name"] == "TEST VENDOR"

    @pytest.mark.asyncio
    async def test_search_disbursements_with_recipient_committee_id(self, client):
        result = await client.search_disbursements(
            committee_id="C0TEST01", recipient_committee_id="C0TEST02",
        )
        assert result["results"][0]["recipient_committee_id"] == "C0TEST02"

    @pytest.mark.asyncio
    async def test_api_key_included_in_params(self, client, mock_routes):
        await client.search_candidates(q="test")
        request = client._client._transport.requests[-1]
        assert request.url.params["api_key"] == "test_key"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        transport = MockTransport({
            "/candidates/search/": {"status": 500, "json": {"message": "Server Error"}},
        })
        c = OpenFECClient(api_key="test_key")
        c._client = httpx.AsyncClient(
            base_url="https://api.open.fec.gov/v1", transport=transport,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await c.search_candidates(q="test")


# =============================================================================
# LDAClient tests
# =============================================================================

class TestLDAClient:
    @pytest.fixture
    def mock_routes(self):
        return {
            "/filings/00000000-0000-0000-0000-000000000001/": {
                "json": {"filing_uuid": "00000000-0000-0000-0000-000000000001", "registrant": {"name": "TEST REGISTRANT"}},
            },
            "/filings/": {
                "json": {"results": [{"filing_uuid": "00000000-0000-0000-0000-000000000001", "registrant": {"name": "TEST REGISTRANT"}}]},
            },
            "/contributions/": {
                "json": {"results": [{"filing_uuid": "00000000-0000-0000-0000-000000000002", "registrant": {"name": "TEST REGISTRANT"}}]},
            },
            "/registrants/42/": {
                "json": {"id": 42, "name": "TEST REGISTRANT"},
            },
            "/registrants/": {
                "json": {"results": [{"id": 42, "name": "TEST REGISTRANT"}]},
            },
            "/clients/": {
                "json": {"results": [{"id": 7, "name": "TEST CLIENT"}]},
            },
            "/error/": {
                "status": 500,
                "json": {"detail": "Server Error"},
            },
        }

    @pytest.fixture
    def client(self, mock_routes):
        transport = MockTransport(mock_routes)
        c = LDAClient(api_key="test_key")
        c._client = httpx.AsyncClient(
            base_url="https://lda.gov/api/v1",
            headers={"Authorization": "Token test_key"},
            transport=transport,
        )
        return c

    @pytest.mark.asyncio
    async def test_search_filings(self, client):
        result = await client.search_filings(registrant_name="test")
        assert result["results"][0]["registrant"]["name"] == "TEST REGISTRANT"

    @pytest.mark.asyncio
    async def test_get_filing(self, client):
        result = await client.get_filing("00000000-0000-0000-0000-000000000001")
        assert result["filing_uuid"] == "00000000-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_search_contributions(self, client):
        result = await client.search_contributions(lobbyist_name="test")
        assert result["results"][0]["filing_uuid"] == "00000000-0000-0000-0000-000000000002"

    @pytest.mark.asyncio
    async def test_search_registrants(self, client):
        result = await client.search_registrants(registrant_name="test")
        assert result["results"][0]["name"] == "TEST REGISTRANT"

    @pytest.mark.asyncio
    async def test_get_registrant(self, client):
        result = await client.get_registrant(42)
        assert result["id"] == 42

    @pytest.mark.asyncio
    async def test_search_clients(self, client):
        result = await client.search_clients(client_name="test")
        assert result["results"][0]["name"] == "TEST CLIENT"

    @pytest.mark.asyncio
    async def test_authorization_header_included(self, client):
        await client.search_filings(registrant_name="test")
        request = client._client._transport.requests[-1]
        assert request.headers["Authorization"] == "Token test_key"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        transport = MockTransport({
            "/filings/": {"status": 500, "json": {"detail": "Server Error"}},
        })
        c = LDAClient(api_key="test_key")
        c._client = httpx.AsyncClient(
            base_url="https://lda.gov/api/v1", transport=transport,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await c.search_filings(registrant_name="test")


# =============================================================================
# ProPublicaNPEClient tests
# =============================================================================

class TestProPublicaNPEClient:
    @pytest.fixture
    def mock_routes(self):
        return {
            "/search.json": {
                "json": {
                    "total_results": 1,
                    "organizations": [{"ein": 142007220, "name": "TEST NONPROFIT", "subseccd": 4}],
                },
            },
            "/organizations/142007220.json": {
                "json": {
                    "organization": {"ein": 142007220, "name": "TEST NONPROFIT"},
                    "filings_with_data": [{"ein": 142007220, "tax_prd_yr": 2024, "totrevenue": 100000}],
                },
            },
            "/error.json": {
                "status": 500,
                "json": {"error": "Server Error"},
            },
        }

    @pytest.fixture
    def client(self, mock_routes):
        transport = MockTransport(mock_routes)
        c = ProPublicaNPEClient()
        c._client = httpx.AsyncClient(
            base_url="https://projects.propublica.org/nonprofits/api/v2",
            transport=transport,
        )
        return c

    @pytest.mark.asyncio
    async def test_search(self, client):
        result = await client.search(q="test")
        assert result["organizations"][0]["name"] == "TEST NONPROFIT"

    @pytest.mark.asyncio
    async def test_search_with_c_code_filter(self, client):
        result = await client.search(q="test", c_code=4)
        assert "organizations" in result

    @pytest.mark.asyncio
    async def test_get_organization(self, client):
        result = await client.get_organization(142007220)
        assert result["organization"]["ein"] == 142007220
        assert len(result["filings_with_data"]) == 1

    @pytest.mark.asyncio
    async def test_get_organization_strips_dashes(self, client):
        result = await client.get_organization("14-2007220")
        assert result["organization"]["ein"] == 142007220

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        transport = MockTransport({
            "/search.json": {"status": 500, "json": {"error": "Server Error"}},
        })
        c = ProPublicaNPEClient()
        c._client = httpx.AsyncClient(
            base_url="https://projects.propublica.org/nonprofits/api/v2", transport=transport,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await c.search(q="test")
