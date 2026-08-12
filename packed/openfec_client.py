"""OpenFEC API client.

Covers candidates, committees, and itemized contributions (Schedule A).
Requires a free API key from api.data.gov.

Endpoints below verified against the live API (2026-08-12): candidate
search/get, committee search/get, and schedule_a contribution search
all confirmed working with real responses.
"""

from __future__ import annotations

import httpx
from typing import Any

from packed import __version__

BASE_URL = "https://api.open.fec.gov/v1"


class OpenFECClient:
    """Async client for the OpenFEC API.

    Requires an API key (free, self-serve via api.data.gov).
    """

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": f"packed/{__version__}"},
        )

    async def close(self):
        await self._client.aclose()

    def _params(self, **kwargs: Any) -> dict[str, Any]:
        params = {"api_key": self._api_key}
        params.update({k: v for k, v in kwargs.items() if v is not None})
        return params

    async def search_candidates(
        self,
        q: str,
        office: str | None = None,
        cycle: int | None = None,
        state: str | None = None,
        party: str | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search candidates by name.

        office: 'H' (House), 'S' (Senate), 'P' (President)
        cycle: two-year election cycle, e.g. 2026
        """
        resp = await self._client.get(
            "/candidates/search/",
            params=self._params(
                q=q, office=office, cycle=cycle, state=state,
                party=party, per_page=per_page,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Get a candidate's record by FEC candidate ID."""
        resp = await self._client.get(f"/candidate/{candidate_id}/", params=self._params())
        resp.raise_for_status()
        return resp.json()

    async def search_committees(
        self,
        q: str,
        committee_type: str | None = None,
        designation: str | None = None,
        cycle: int | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search committees (PACs, party committees, candidate committees) by name.

        committee_type: e.g. 'N' (PAC - nonqualified), 'Q' (PAC - qualified),
            'P' (Presidential), 'H' (House), 'S' (Senate), 'X'/'Y'/'Z' (party)
        designation: 'A' (authorized), 'J' (joint fundraising), 'P' (principal
            campaign committee), 'U' (unauthorized), 'D' (leadership PAC)
        """
        resp = await self._client.get(
            "/committees/",
            params=self._params(
                q=q, committee_type=committee_type, designation=designation,
                cycle=cycle, per_page=per_page,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_committee(self, committee_id: str) -> dict[str, Any]:
        """Get a committee's record by FEC committee ID."""
        resp = await self._client.get(f"/committee/{committee_id}/", params=self._params())
        resp.raise_for_status()
        return resp.json()

    async def search_contributions(
        self,
        committee_id: str | None = None,
        contributor_name: str | None = None,
        two_year_transaction_period: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search itemized individual contributions (Schedule A).

        At least one of committee_id or contributor_name should be set
        to keep results scoped — this endpoint covers a very large dataset.
        """
        resp = await self._client.get(
            "/schedules/schedule_a/",
            params=self._params(
                committee_id=committee_id,
                contributor_name=contributor_name,
                two_year_transaction_period=two_year_transaction_period,
                min_amount=min_amount,
                max_amount=max_amount,
                per_page=per_page,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def search_disbursements(
        self,
        committee_id: str | None = None,
        recipient_name: str | None = None,
        recipient_committee_id: str | None = None,
        two_year_transaction_period: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search itemized disbursements — where committee money goes out
        (Schedule B). Set recipient_committee_id to trace payments to
        another committee (leadership PAC / JFC transfers).

        At least one of committee_id, recipient_name, or
        recipient_committee_id should be set — this endpoint covers a
        very large dataset. Note: for very high-volume committees (e.g.
        ActBlue), the response's pagination.count is not reliably
        filtered even though the actual results are — confirmed against
        the live API (2026-08-12). Don't trust count for those; trust
        the returned results.
        """
        resp = await self._client.get(
            "/schedules/schedule_b/",
            params=self._params(
                committee_id=committee_id,
                recipient_name=recipient_name,
                recipient_committee_id=recipient_committee_id,
                two_year_transaction_period=two_year_transaction_period,
                min_amount=min_amount,
                max_amount=max_amount,
                per_page=per_page,
            ),
        )
        resp.raise_for_status()
        return resp.json()
