"""Tests for API clients.

Uses httpx mock transport to avoid hitting real APIs in tests.
"""

import pytest
import httpx
from packed.openfec_client import OpenFECClient


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
