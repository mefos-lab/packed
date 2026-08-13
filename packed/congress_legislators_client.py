"""congress-legislators client — committee assignments and legislator identity.

Source: github.com/unitedstates/congress-legislators, a public-domain
shared commons of congressional data. Unlike the other sources, this is
not a REST API — it's a set of static YAML files fetched whole from raw
GitHub. No API key, no rate limit.

Why this source matters: `legislators-current.yaml` carries an `id`
block containing **FEC candidate IDs** alongside `bioguide` IDs. Since
committee membership is keyed by bioguide, this is what lets committee
assignments join to FEC contribution/expenditure data without fuzzy
name matching — the missing link that made the "dual role" and
"industry concentration" detection patterns infeasible before.

Data shapes confirmed live (2026-08-12):
- `committee-membership-current.yaml` — maps committee ID -> list of
  members, each with `name`, `party` (majority/minority), `rank`,
  optional `title` (Chairman / Ranking Member / Ex Officio), `bioguide`.
- `committees-current.yaml` — committee metadata, each with `thomas_id`,
  `name`, `type` (house/senate/joint), and nested `subcommittees` whose
  own `thomas_id` is a 2-digit suffix. A subcommittee's key in the
  membership file is parent + suffix (e.g. SSAF + 13 = "SSAF13").
- `legislators-current.yaml` — 537 legislators, each with `name` and
  `id` blocks.

Known data caveats, all confirmed against the live files:
- **Committee membership is current-only.** There are no historical
  snapshots, so anything built on this describes the present, not a
  point in time. Say so in any output derived from it.
- 2 of 537 current legislators have no FEC ID at all — they simply
  won't resolve via FEC lookup.
- 64 legislators have more than one FEC ID (up to 3), e.g. someone who
  ran for the House and later the Senate. The FEC index is therefore
  many-IDs-to-one-legislator.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx
import yaml

from packed import __version__

# Honorifics and titles that appear in front of names in other sources
# (LD-203 honoree names look like "Sen. Marsha Blackburn" / "The
# Honorable French Hill"), plus bare initials, which carry no matching
# signal and would otherwise cause false negatives.
_NAME_TITLES = {
    "the", "honorable", "hon", "sen", "senator", "rep", "representative",
    "cong", "congressman", "congresswoman", "dr", "mr", "mrs", "ms", "jr",
    "sr", "ii", "iii", "iv",
}


def _name_tokens(name: str | None) -> set[str]:
    """Lowercase, accent-stripped name tokens, minus titles and initials.

    Diacritics are stripped because other sources routinely write these
    names unaccented — LD-203 honoree fields say "Ben Ray Lujan" and
    "Linda Sanchez" where the official records say "Luján" and
    "Sánchez".
    """
    if not name:
        return set()
    folded = unicodedata.normalize("NFKD", name.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    raw = re.split(r"[^a-z]+", folded)
    return {t for t in raw if len(t) > 1 and t not in _NAME_TITLES}


_PREFIX_MIN = 3


def _token_matches(query_token: str, leg_tokens: set[str]) -> bool:
    """A query token matches exactly, or as a prefix of a legislator
    token (min 3 chars).

    Prefix matching exists to handle shortened first names, which are
    common in how other sources write legislator names: "Chris Coons"
    vs. the official "Christopher A. Coons", "Dan Meuser" vs. "Daniel
    Meuser". Since *every* query token must match, requiring the last
    name too, this stays tight in practice — measured against 141 real
    LD-203 honoree names it produced zero ambiguous (>1 match) results.

    It does not handle nicknames that aren't prefixes — "Elizabeth
    Fletcher" will not match "Lizzie Fletcher". That needs a nickname
    dictionary and is a known, accepted gap.
    """
    if query_token in leg_tokens:
        return True
    if len(query_token) < _PREFIX_MIN:
        return False
    return any(
        t.startswith(query_token)
        for t in leg_tokens
        if len(t) > len(query_token)
    )

BASE_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"

COMMITTEE_MEMBERSHIP_FILE = "committee-membership-current.yaml"
COMMITTEES_FILE = "committees-current.yaml"
LEGISLATORS_FILE = "legislators-current.yaml"


class CongressLegislatorsClient:
    """Async client for the congress-legislators data files.

    Files are fetched whole (~1.4MB total across the three) and cached
    in memory for the life of the client, since they're static files
    rather than a query API. Call `refresh()` to drop the cache.
    """

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": f"packed/{__version__}"},
            follow_redirects=True,
        )
        self._cache: dict[str, Any] = {}

    async def close(self):
        await self._client.aclose()

    def refresh(self) -> None:
        """Drop cached file contents so the next call refetches."""
        self._cache.clear()

    async def _fetch_yaml(self, filename: str) -> Any:
        if filename in self._cache:
            return self._cache[filename]
        resp = await self._client.get(f"/{filename}")
        resp.raise_for_status()
        parsed = yaml.safe_load(resp.text)
        self._cache[filename] = parsed
        return parsed

    # ── Raw file accessors ──────────────────────────────────────────

    async def get_committee_membership(self) -> dict[str, Any]:
        """Raw committee ID -> member list mapping."""
        return await self._fetch_yaml(COMMITTEE_MEMBERSHIP_FILE)

    async def get_committees(self) -> list[dict[str, Any]]:
        """Raw committee metadata list."""
        return await self._fetch_yaml(COMMITTEES_FILE)

    async def get_legislators(self) -> list[dict[str, Any]]:
        """Raw current-legislator list."""
        return await self._fetch_yaml(LEGISLATORS_FILE)

    # ── Lookups ─────────────────────────────────────────────────────

    async def find_legislator_by_fec_id(self, fec_id: str) -> dict[str, Any] | None:
        """Resolve an FEC candidate ID to a legislator record.

        This is the join that links FEC money data to committee
        assignments. Returns None if no current legislator holds that
        FEC ID (they may have left office, or never had one recorded).
        """
        legislators = await self.get_legislators()
        for leg in legislators:
            if fec_id in (leg.get("id", {}).get("fec") or []):
                return leg
        return None

    async def find_legislator_by_bioguide(self, bioguide: str) -> dict[str, Any] | None:
        """Resolve a bioguide ID to a legislator record."""
        legislators = await self.get_legislators()
        for leg in legislators:
            if leg.get("id", {}).get("bioguide") == bioguide:
                return leg
        return None

    async def search_legislators_by_name(self, name: str) -> list[dict[str, Any]]:
        """Match legislators by name tokens.

        Token-subset rather than substring: every token in the query
        must match some token of the legislator's name. This is what
        makes "Max Miller" match "Max L. Miller" — a plain substring
        check fails on the middle initial, which is common enough in
        this data to matter (it silently lost ~half of real matches
        when this was substring-based).
        """
        query_tokens = _name_tokens(name)
        if not query_tokens:
            return []
        results = []
        for leg in await self.get_legislators():
            n = leg.get("name", {})
            leg_tokens = set()
            for v in (n.get("first"), n.get("middle"), n.get("last"),
                      n.get("official_full"), n.get("nickname")):
                leg_tokens |= _name_tokens(v)
            if all(_token_matches(q, leg_tokens) for q in query_tokens):
                results.append(leg)
        return results

    async def get_committees_for_legislator(
        self, bioguide: str,
    ) -> list[dict[str, Any]]:
        """All committees and subcommittees a legislator sits on.

        Returns entries with the committee ID, resolved name, chamber
        type, whether it's a subcommittee, and the legislator's rank/
        title/party standing on it.
        """
        membership = await self.get_committee_membership()
        committee_index = await self._committee_index()

        results = []
        for committee_id, members in membership.items():
            for m in members:
                if m.get("bioguide") != bioguide:
                    continue
                meta = committee_index.get(committee_id, {})
                results.append({
                    "committee_id": committee_id,
                    "name": meta.get("name"),
                    "type": meta.get("type"),
                    "is_subcommittee": meta.get("is_subcommittee", False),
                    "parent_committee_id": meta.get("parent_committee_id"),
                    "parent_committee_name": meta.get("parent_committee_name"),
                    "rank": m.get("rank"),
                    "title": m.get("title"),
                    "party": m.get("party"),
                })
        return results

    async def get_committee_members(self, committee_id: str) -> dict[str, Any]:
        """All members of a committee, with each member's FEC IDs
        attached where available so the roster can be joined straight to
        FEC money data.
        """
        membership = await self.get_committee_membership()
        committee_index = await self._committee_index()
        meta = committee_index.get(committee_id, {})

        members = []
        for m in membership.get(committee_id, []):
            bioguide = m.get("bioguide")
            leg = await self.find_legislator_by_bioguide(bioguide) if bioguide else None
            members.append({
                "name": m.get("name"),
                "bioguide": bioguide,
                "party": m.get("party"),
                "rank": m.get("rank"),
                "title": m.get("title"),
                # May be empty: 2 of 537 current legislators have no FEC ID.
                "fec_ids": (leg or {}).get("id", {}).get("fec", []),
                "state": (leg or {}).get("terms", [{}])[-1].get("state"),
            })

        return {
            "committee_id": committee_id,
            "name": meta.get("name"),
            "type": meta.get("type"),
            "is_subcommittee": meta.get("is_subcommittee", False),
            "parent_committee_id": meta.get("parent_committee_id"),
            "parent_committee_name": meta.get("parent_committee_name"),
            "member_count": len(members),
            "members": members,
        }

    async def search_committees(self, query: str) -> list[dict[str, Any]]:
        """Case-insensitive substring match against committee names."""
        needle = query.lower().strip()
        if not needle:
            return []
        index = await self._committee_index()
        return [
            {"committee_id": cid, **{k: v for k, v in meta.items()}}
            for cid, meta in index.items()
            if needle in (meta.get("name") or "").lower()
        ]

    # ── Internal ────────────────────────────────────────────────────

    async def _committee_index(self) -> dict[str, dict[str, Any]]:
        """Flatten committees + subcommittees into one ID -> metadata map.

        A subcommittee's membership key is its parent's thomas_id
        concatenated with its own 2-digit thomas_id (SSAF + 13 =
        "SSAF13") — confirmed against the live files.
        """
        cache_key = "_committee_index"
        if cache_key in self._cache:
            return self._cache[cache_key]

        index: dict[str, dict[str, Any]] = {}
        for c in await self.get_committees():
            parent_id = c.get("thomas_id")
            if not parent_id:
                continue
            index[parent_id] = {
                "name": c.get("name"),
                "type": c.get("type"),
                "is_subcommittee": False,
                "parent_committee_id": None,
                "parent_committee_name": None,
            }
            for sub in c.get("subcommittees", []) or []:
                sub_suffix = sub.get("thomas_id")
                if not sub_suffix:
                    continue
                index[f"{parent_id}{sub_suffix}"] = {
                    "name": sub.get("name"),
                    "type": c.get("type"),
                    "is_subcommittee": True,
                    "parent_committee_id": parent_id,
                    "parent_committee_name": c.get("name"),
                }

        self._cache[cache_key] = index
        return index
