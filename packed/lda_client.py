"""LDA (Lobbying Disclosure Act database) API client.

Covers filings (LD-1 registrations, LD-2 quarterly activity),
contribution reports (LD-203 — lobbyist political contributions),
registrants, and clients. Requires a free API key from lda.gov.

Endpoint shapes and auth confirmed from the live OpenAPI schema at
https://lda.gov/api/openapi/v1/ (fetched 2026-08-12), then verified
against the live API with real data.
"""

from __future__ import annotations

import httpx
from typing import Any

from packed import __version__

BASE_URL = "https://lda.gov/api/v1"


class LDAClient:
    """Async client for the LDA (Lobbying Disclosure Act) API.

    Auth: `Authorization: Token <key>` header. Free key via
    https://lda.gov/api/register/ (full account, not just an email key).
    """

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "User-Agent": f"packed/{__version__}",
                "Authorization": f"Token {api_key}",
            },
        )

    async def close(self):
        await self._client.aclose()

    def _params(self, **kwargs: Any) -> dict[str, Any]:
        return {k: v for k, v in kwargs.items() if v is not None}

    async def search_filings(
        self,
        registrant_name: str | None = None,
        client_name: str | None = None,
        lobbyist_name: str | None = None,
        filing_year: int | None = None,
        filing_type: str | None = None,
        filing_period: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Search LD-1 registrations and LD-2 quarterly activity filings.

        At least one filter should be set — the API requires a query
        parameter when paginating this endpoint.
        """
        resp = await self._client.get(
            "/filings/",
            params=self._params(
                registrant_name=registrant_name, client_name=client_name,
                lobbyist_name=lobbyist_name, filing_year=filing_year,
                filing_type=filing_type, filing_period=filing_period,
                page=page, page_size=page_size,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_filing(self, filing_uuid: str) -> dict[str, Any]:
        """Get a single filing's full record by its UUID."""
        resp = await self._client.get(f"/filings/{filing_uuid}/")
        resp.raise_for_status()
        return resp.json()

    async def search_contributions(
        self,
        registrant_name: str | None = None,
        lobbyist_name: str | None = None,
        contribution_contributor: str | None = None,
        filing_year: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Search LD-203 contribution reports — lobbyist political
        contributions. This is the link between lobbying and campaign
        finance.

        At least one filter should be set — the API requires a query
        parameter when paginating this endpoint.
        """
        resp = await self._client.get(
            "/contributions/",
            params=self._params(
                registrant_name=registrant_name, lobbyist_name=lobbyist_name,
                contribution_contributor=contribution_contributor,
                filing_year=filing_year, page=page, page_size=page_size,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def search_registrants(
        self,
        registrant_name: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Search registrants (lobbying firms/individuals) by name."""
        resp = await self._client.get(
            "/registrants/",
            params=self._params(
                registrant_name=registrant_name, page=page, page_size=page_size,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_registrant(self, registrant_id: int) -> dict[str, Any]:
        """Get a single registrant's full record by ID."""
        resp = await self._client.get(f"/registrants/{registrant_id}/")
        resp.raise_for_status()
        return resp.json()

    async def search_clients(
        self,
        client_name: str | None = None,
        registrant_id: int | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Search lobbying clients by name, optionally scoped to a registrant."""
        resp = await self._client.get(
            "/clients/",
            params=self._params(
                client_name=client_name, registrant_id=registrant_id,
                page=page, page_size=page_size,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_client(self, client_id: int) -> dict[str, Any]:
        """Get a single lobbying client's full record by ID."""
        resp = await self._client.get(f"/clients/{client_id}/")
        resp.raise_for_status()
        return resp.json()

    async def search_lobbyists(
        self,
        lobbyist_name: str | None = None,
        registrant_id: int | None = None,
        registrant_name: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Search individual lobbyists by name, optionally scoped to a
        registrant. Lobbyists are a distinct entity from registrants — a
        registrant (firm) employs many lobbyists.
        """
        resp = await self._client.get(
            "/lobbyists/",
            params=self._params(
                lobbyist_name=lobbyist_name, registrant_id=registrant_id,
                registrant_name=registrant_name, page=page, page_size=page_size,
            ),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_lobbyist(self, lobbyist_id: int) -> dict[str, Any]:
        """Get a single lobbyist's full record by ID."""
        resp = await self._client.get(f"/lobbyists/{lobbyist_id}/")
        resp.raise_for_status()
        return resp.json()

    async def get_contribution(self, filing_uuid: str) -> dict[str, Any]:
        """Get a single LD-203 contribution report by its filing UUID."""
        resp = await self._client.get(f"/contributions/{filing_uuid}/")
        resp.raise_for_status()
        return resp.json()
