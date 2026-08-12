"""ProPublica Nonprofit Explorer API client.

Covers Form 990 filings for tax-exempt organizations, including
501(c)(4) "social welfare" organizations — the dark-money vehicles
that don't have to disclose donors but do have to file spending.
No authentication required.

Endpoint shapes confirmed from the live docs at
https://projects.propublica.org/nonprofits/api (fetched 2026-08-12)
and verified against the live API with real data.
"""

from __future__ import annotations

import httpx
from typing import Any

from packed import __version__

BASE_URL = "https://projects.propublica.org/nonprofits/api/v2"

# c_code[id] values for the /search.json c_code filter — subsection of
# 501(c) of the tax code. 4 = 501(c)(4), the dark-money category this
# tool cares about most, but any subsection can be searched.
C_CODE_501C4 = 4


class ProPublicaNPEClient:
    """Async client for the ProPublica Nonprofit Explorer API.

    No authentication required, but Form 990 PDF download links are
    separately rate limited by ProPublica (not exposed by this client).
    """

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": f"packed/{__version__}"},
        )

    async def close(self):
        await self._client.aclose()

    async def search(
        self,
        q: str | None = None,
        page: int = 0,
        state: str | None = None,
        ntee: int | None = None,
        c_code: int | None = None,
    ) -> dict[str, Any]:
        """Search organizations by name/city, optionally filtered by
        state, NTEE major group (1-10), or 501(c) subsection code.

        Pass c_code=4 (or use C_CODE_501C4) to scope to 501(c)(4)
        social welfare organizations — the dark-money category.
        """
        params: dict[str, Any] = {"page": page}
        if q is not None:
            params["q"] = q
        if state is not None:
            params["state[id]"] = state
        if ntee is not None:
            params["ntee[id]"] = ntee
        if c_code is not None:
            params["c_code[id]"] = c_code

        resp = await self._client.get("/search.json", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_organization(self, ein: str | int) -> dict[str, Any]:
        """Get full profile and filing history for an organization by EIN.

        EIN may be passed with or without the "XX-XXXXXXX" formatting —
        the API expects the plain integer form.
        """
        ein_str = str(ein).replace("-", "")
        resp = await self._client.get(f"/organizations/{ein_str}.json")
        resp.raise_for_status()
        return resp.json()
