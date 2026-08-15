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
        contributor_employer: str | None = None,
        two_year_transaction_period: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        per_page: int = 20,
        last_index: str | None = None,
        last_contribution_receipt_date: str | None = None,
    ) -> dict[str, Any]:
        """Search itemized individual contributions (Schedule A).

        At least one of committee_id, contributor_name or
        contributor_employer should be set to keep results scoped — this
        endpoint covers a very large dataset.

        Schedule A pages by keyset, not by page number: a response's
        ``pagination.last_indexes`` carries the two values to pass back
        for the next page. Both must be sent together; sending only
        ``last_index`` returns a 422.
        """
        resp = await self._client.get(
            "/schedules/schedule_a/",
            params=self._params(
                committee_id=committee_id,
                contributor_name=contributor_name,
                contributor_employer=contributor_employer,
                two_year_transaction_period=two_year_transaction_period,
                min_amount=min_amount,
                max_amount=max_amount,
                per_page=per_page,
                last_index=last_index,
                last_contribution_receipt_date=last_contribution_receipt_date,
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

    async def search_independent_expenditures(
        self,
        candidate_id: str | None = None,
        committee_id: str | None = None,
        support_oppose_indicator: str | None = None,
        two_year_transaction_period: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search independent expenditures (Schedule E) — spending by a
        committee not coordinated with a candidate, expressly advocating
        for or against them.

        support_oppose_indicator: 'S' (supporting) or 'O' (opposing).
        At least one of candidate_id or committee_id should be set.
        """
        resp = await self._client.get(
            "/schedules/schedule_e/",
            params=self._params(
                candidate_id=candidate_id,
                committee_id=committee_id,
                support_oppose_indicator=support_oppose_indicator,
                two_year_transaction_period=two_year_transaction_period,
                min_amount=min_amount,
                max_amount=max_amount,
                per_page=per_page,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def search_coordinated_expenditures(
        self,
        committee_id: str | None = None,
        candidate_id: str | None = None,
        two_year_transaction_period: int | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        """Search coordinated party expenditures (Schedule F) — spending
        by a party committee made on behalf of (in coordination with) a
        candidate, a distinct disclosure category from independent
        expenditures.

        At least one of committee_id or candidate_id should be set.
        """
        resp = await self._client.get(
            "/schedules/schedule_f/",
            params=self._params(
                committee_id=committee_id,
                candidate_id=candidate_id,
                two_year_transaction_period=two_year_transaction_period,
                min_amount=min_amount,
                max_amount=max_amount,
                per_page=per_page,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_committee_totals(
        self, committee_id: str, cycle: int | None = None,
    ) -> dict[str, Any]:
        """Get a committee's aggregated financial totals (receipts,
        disbursements, cash on hand) per reporting period, without
        pulling itemized data.
        """
        resp = await self._client.get(
            f"/committee/{committee_id}/totals/",
            params=self._params(cycle=cycle),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_candidate_totals(
        self, candidate_id: str, cycle: int | None = None,
    ) -> dict[str, Any]:
        """Get a candidate's aggregated financial totals (receipts,
        disbursements, cash on hand) per election, without pulling
        itemized data.
        """
        resp = await self._client.get(
            f"/candidate/{candidate_id}/totals/",
            params=self._params(cycle=cycle),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_candidate_committees(
        self, candidate_id: str, cycle: int | None = None,
    ) -> dict[str, Any]:
        """Get the committees associated with a candidate — resolves
        candidate-to-committee linkage directly instead of inferring it
        from search results.
        """
        resp = await self._client.get(
            f"/candidate/{candidate_id}/committees/",
            params=self._params(cycle=cycle),
        )
        resp.raise_for_status()
        return resp.json()
