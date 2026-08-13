"""Tests for the congress-legislators client.

Uses httpx mock transport to avoid fetching real files in tests.
Unlike the other clients this one fetches whole YAML documents, so the
mock returns YAML text rather than JSON.
"""

import pytest
import httpx

from packed.congress_legislators_client import CongressLegislatorsClient


COMMITTEES_YAML = """
- type: senate
  name: Senate Committee on Agriculture, Nutrition, and Forestry
  thomas_id: SSAF
  subcommittees:
    - name: Commodities and Risk Management
      thomas_id: '13'
    - name: Conservation and Forestry
      thomas_id: '14'
- type: house
  name: House Committee on Agriculture
  thomas_id: HSAG
  subcommittees: []
"""

MEMBERSHIP_YAML = """
SSAF:
  - name: Test Chairman
    party: majority
    rank: 1
    title: Chairman
    bioguide: C000001
  - name: Test Member
    party: minority
    rank: 2
    bioguide: M000002
SSAF13:
  - name: Test Member
    party: minority
    rank: 1
    bioguide: M000002
HSAG:
  - name: No Fec Person
    party: majority
    rank: 1
    bioguide: N000003
"""

LEGISLATORS_YAML = """
- name:
    first: Test
    last: Chairman
    official_full: Test Chairman
  id:
    bioguide: C000001
    fec:
      - H2TEST001
      - S0TEST002
  terms:
    - state: AR
      type: sen
- name:
    first: Test
    last: Member
    official_full: Test Member
  id:
    bioguide: M000002
    fec:
      - S0TEST003
  terms:
    - state: ME
      type: sen
- name:
    first: No Fec
    last: Person
    official_full: No Fec Person
  id:
    bioguide: N000003
  terms:
    - state: TX
      type: rep
"""


class YamlMockTransport(httpx.AsyncBaseTransport):
    """Returns canned YAML text based on the requested filename."""

    def __init__(self, routes: dict[str, str], status: int = 200):
        self.routes = routes
        self.status = status
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for filename, body in self.routes.items():
            if filename in request.url.path:
                return httpx.Response(status_code=self.status, text=body)
        return httpx.Response(status_code=404, text="not found")


@pytest.fixture
def client():
    transport = YamlMockTransport({
        "committee-membership-current.yaml": MEMBERSHIP_YAML,
        "committees-current.yaml": COMMITTEES_YAML,
        "legislators-current.yaml": LEGISLATORS_YAML,
    })
    c = CongressLegislatorsClient()
    c._client = httpx.AsyncClient(
        base_url="https://raw.githubusercontent.com/unitedstates/congress-legislators/main",
        transport=transport,
    )
    return c


# =============================================================================
# Raw accessors and caching
# =============================================================================

class TestFetching:
    @pytest.mark.asyncio
    async def test_get_committees(self, client):
        result = await client.get_committees()
        assert len(result) == 2
        assert result[0]["thomas_id"] == "SSAF"

    @pytest.mark.asyncio
    async def test_get_legislators(self, client):
        result = await client.get_legislators()
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_files_are_cached_after_first_fetch(self, client):
        await client.get_legislators()
        await client.get_legislators()
        await client.get_legislators()
        paths = [r.url.path for r in client._client._transport.requests]
        assert sum("legislators-current" in p for p in paths) == 1

    @pytest.mark.asyncio
    async def test_refresh_drops_cache(self, client):
        await client.get_legislators()
        client.refresh()
        await client.get_legislators()
        paths = [r.url.path for r in client._client._transport.requests]
        assert sum("legislators-current" in p for p in paths) == 2

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        transport = YamlMockTransport({"legislators-current.yaml": ""}, status=500)
        c = CongressLegislatorsClient()
        c._client = httpx.AsyncClient(
            base_url="https://raw.githubusercontent.com/unitedstates/congress-legislators/main",
            transport=transport,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await c.get_legislators()


# =============================================================================
# Legislator lookups — the FEC join
# =============================================================================

class TestLegislatorLookups:
    @pytest.mark.asyncio
    async def test_find_by_fec_id(self, client):
        leg = await client.find_legislator_by_fec_id("S0TEST003")
        assert leg["id"]["bioguide"] == "M000002"

    @pytest.mark.asyncio
    async def test_find_by_fec_id_matches_any_of_multiple(self, client):
        """64 real legislators have more than one FEC ID — any should match."""
        first = await client.find_legislator_by_fec_id("H2TEST001")
        second = await client.find_legislator_by_fec_id("S0TEST002")
        assert first["id"]["bioguide"] == second["id"]["bioguide"] == "C000001"

    @pytest.mark.asyncio
    async def test_find_by_fec_id_not_found(self, client):
        assert await client.find_legislator_by_fec_id("H9NOPE999") is None

    @pytest.mark.asyncio
    async def test_legislator_with_no_fec_id_is_not_matched(self, client):
        """2 of 537 real legislators have no FEC ID — must not crash."""
        assert await client.find_legislator_by_fec_id("") is None

    @pytest.mark.asyncio
    async def test_find_by_bioguide(self, client):
        leg = await client.find_legislator_by_bioguide("N000003")
        assert leg["name"]["last"] == "Person"

    @pytest.mark.asyncio
    async def test_search_by_name(self, client):
        results = await client.search_legislators_by_name("chairman")
        assert len(results) == 1
        assert results[0]["id"]["bioguide"] == "C000001"

    @pytest.mark.asyncio
    async def test_search_by_name_empty_query(self, client):
        assert await client.search_legislators_by_name("  ") == []


# =============================================================================
# Committee lookups
# =============================================================================

class TestCommitteeLookups:
    @pytest.mark.asyncio
    async def test_committees_for_legislator_includes_subcommittees(self, client):
        results = await client.get_committees_for_legislator("M000002")
        ids = {c["committee_id"] for c in results}
        assert ids == {"SSAF", "SSAF13"}

    @pytest.mark.asyncio
    async def test_subcommittee_resolves_parent(self, client):
        results = await client.get_committees_for_legislator("M000002")
        sub = next(c for c in results if c["committee_id"] == "SSAF13")
        assert sub["is_subcommittee"] is True
        assert sub["parent_committee_id"] == "SSAF"
        assert sub["name"] == "Commodities and Risk Management"

    @pytest.mark.asyncio
    async def test_committees_for_legislator_carries_title(self, client):
        results = await client.get_committees_for_legislator("C000001")
        assert results[0]["title"] == "Chairman"
        assert results[0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_committees_for_unknown_legislator(self, client):
        assert await client.get_committees_for_legislator("X000000") == []

    @pytest.mark.asyncio
    async def test_committee_members_attaches_fec_ids(self, client):
        roster = await client.get_committee_members("SSAF")
        assert roster["member_count"] == 2
        chair = next(m for m in roster["members"] if m["bioguide"] == "C000001")
        assert chair["fec_ids"] == ["H2TEST001", "S0TEST002"]
        assert chair["title"] == "Chairman"

    @pytest.mark.asyncio
    async def test_committee_members_handles_missing_fec_id(self, client):
        roster = await client.get_committee_members("HSAG")
        assert roster["members"][0]["fec_ids"] == []

    @pytest.mark.asyncio
    async def test_committee_members_unknown_committee(self, client):
        roster = await client.get_committee_members("ZZZZ")
        assert roster["member_count"] == 0

    @pytest.mark.asyncio
    async def test_search_committees(self, client):
        results = await client.search_committees("agriculture")
        ids = {c["committee_id"] for c in results}
        assert "SSAF" in ids
        assert "HSAG" in ids

    @pytest.mark.asyncio
    async def test_search_committees_matches_subcommittee(self, client):
        results = await client.search_committees("conservation")
        assert len(results) == 1
        assert results[0]["committee_id"] == "SSAF14"

    @pytest.mark.asyncio
    async def test_search_committees_empty_query(self, client):
        assert await client.search_committees("") == []
