"""Parsing LDA `covered_position` free text.

Lobbying Disclosure Act filings require a lobbyist who previously held a
"covered" government position to disclose it. The field is free text
written by the filer, so it carries the revolving door in prose:

    Deputy Chief of Staff, Rep. Lamar Smith/Professional Staff member,
    House Science Cmte; Legislative Director, Rep. Louie Gohmert

This module turns that into two kinds of reference — members and
committees — and nothing else. It deliberately does not try to extract
the job title, the dates, or the seniority: those vary without limit and
nothing downstream needs them.

**The design rule is that the parser proposes and the roster disposes.**
Extraction is generous; every candidate is then resolved against
congress-legislators, and one that does not match exactly one current
entity is reported unresolved rather than guessed at. This is what makes
the free text usable without the editorial construction this project has
declined elsewhere — no fuzzy committee inference, no assuming a chamber
that the filer did not write.

Two consequences worth stating, because they bound what a result means:

- A reference to a member who has left office does not resolve, since
  congress-legislators' current files are the only roster consulted. That
  is most of what does not resolve, and it is correct: the pattern asks
  whose current committee seats a lobbyist has a prior tie to.
- A committee phrase naming no chamber ("Commerce Committee") is
  genuinely ambiguous between two real committees. It is reported as
  ambiguous, never resolved by picking one.

Measured when this was written, against 448 distinct 2024
`covered_position` values: 41.5% of them yielded at least one current
member or committee. That figure is why the member route was worth
building after the committee-only route was assessed as too sparse —
re-measure before assuming it still holds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# How filers name a legislator. Both "Rep." and "Rep" appear, as do the
# spelled-out forms.
_HONORIFIC = r"(?:Rep|Reps|Representative|Congressman|Congresswoman|Sen|Senator)\.?"

_MEMBER_RE = re.compile(
    rf"\b{_HONORIFIC}\s+([A-Z][A-Za-z'’\-\.]*(?:\s+[A-Z][A-Za-z'’\-\.]*){{0,3}})"
)

# A capitalised word that begins the next job title rather than
# continuing the name. Filers routinely run the two together with no
# delimiter ("Congressman Elijah E. Cummings Legislative Assistant"), so
# without this the name absorbs the following role and never resolves.
# A legislator whose surname is one of these words would be truncated and
# then fail to resolve, which is the safe direction to be wrong in.
_TITLE_WORDS = frozenset({
    "legislative", "chief", "staff", "deputy", "counsel", "director",
    "assistant", "professional", "senior", "special", "advisor", "adviser",
    "scheduler", "clerk", "press", "secretary", "policy", "communications",
    "executive", "associate", "research", "intern", "fellow", "manager",
    "analyst", "attorney", "sr", "jr", "office", "member", "committee",
    "cmte", "subcommittee", "and", "to", "for",
})

# Shorthand a substring match cannot reach. Expansions are the words that
# appear in the official committee name, so they score through the same
# token overlap as spelled-out phrases.
_ABBREVIATIONS = {
    "e&c": "energy commerce",
    "ag": "agriculture",
    "approps": "appropriations",
    "approp": "appropriations",
    "help": "health education labor pensions",
    "hsgac": "homeland security governmental affairs",
    "sasc": "armed services",
    "hasc": "armed services",
    "sfrc": "foreign relations",
    "hfac": "foreign affairs",
    "t&i": "transportation infrastructure",
    "w&m": "ways means",
    "epw": "environment public works",
    "fsc": "financial services",
    "sbc": "small business",
    "hpsci": "intelligence",
    "ssci": "intelligence",
    "intel": "intelligence",
    "natres": "natural resources",
}

# "Comm" is deliberately absent: it collides with "Dept of Comm",
# "FHA Commissioner" and "Deputy Comm(issioner)", and admitting it
# produced more false candidates than real committees.
_COMMITTEE_TOKEN = r"(?:Committee|Cmte|Subcommittee|Subcmte|Subcttee)"

_COMMITTEE_RE = re.compile(
    rf"((?:House|Senate|Joint)?\s*"
    rf"(?:[A-Z][A-Za-z&'\-]*\s+){{0,4}}"
    rf"\b{_COMMITTEE_TOKEN}\.?"
    rf"(?:\s+on\s+(?:the\s+)?[A-Za-z&'\- ]{{1,60}})?)",
    re.I,
)

# Words carrying no committee identity — chamber markers, the word
# "committee" itself, and the job titles that sit next to it in a clause.
_TOPIC_STOPWORDS = frozenset({
    "committee", "cmte", "comm", "subcommittee", "subcmte", "subcttee",
    "on", "the", "of", "and", "house", "senate", "joint", "select",
    "permanent", "special", "us", "min", "maj", "minority", "majority",
    "prof", "professional", "staff", "dir", "director", "counsel", "chief",
    "clerk", "intern", "assistant", "member", "coordinator", "conference",
    "republican", "democratic", "office", "for", "to", "deputy", "senior",
    "sr",
})

# Party and caucus bodies that read as committees but are not standing
# committees of either chamber, so no roster will ever match them. Matched
# on the party word plus the body word rather than on whole phrases,
# because filers abbreviate ("Republican Study Cmte").
_PARTY_BODY_RE = re.compile(
    r"\b(?:republican|democratic|democrat|gop)\b[\w\s&'\-]{0,20}?"
    r"\b(?:study|policy|conference|caucus|steering)\b"
    r"|\b(?:study|policy|conference|caucus|steering)\b[\w\s&'\-]{0,20}?"
    r"\b(?:republican|democratic|democrat|gop)\b",
    re.I,
)

# A position is one clause. Filers separate them with semicolons and
# slashes, and use commas between a title and its office; splitting on all
# three keeps an adjacent clause's words from bleeding into a committee
# phrase and making it ambiguous.
_CLAUSE_SPLIT = re.compile(r"[;,/]|(?<=\w)\s+-\s+")


@dataclass(frozen=True)
class ParsedPosition:
    """References extracted from one `covered_position` value."""

    member_names: tuple[str, ...] = ()
    committee_phrases: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.member_names or self.committee_phrases)


def _trim_to_name(captured: str) -> str:
    kept: list[str] = []
    for token in captured.split():
        if token.strip(".").lower() in _TITLE_WORDS:
            break
        kept.append(token)
    return " ".join(kept).rstrip(".,;:")


def parse(text: str | None) -> ParsedPosition:
    """Extract member and committee references from one disclosure.

    Order is preserved and duplicates dropped, so a filer naming the same
    office twice does not inflate a count downstream.
    """
    if not text or not text.strip():
        return ParsedPosition()

    members: list[str] = []
    for match in _MEMBER_RE.finditer(text):
        name = _trim_to_name(match.group(1))
        if name and name not in members:
            members.append(name)

    committees: list[str] = []
    for clause in _CLAUSE_SPLIT.split(text):
        if not clause.strip():
            continue
        for match in _COMMITTEE_RE.finditer(clause):
            phrase = match.group(1).strip(" .,;:")
            if not phrase or _PARTY_BODY_RE.search(phrase):
                continue
            # A bare "Cmte" or "Subcommittee" names nothing. Dropping it
            # here keeps it out of the candidate count, so the reported
            # resolution rate describes phrases that could have resolved.
            if not topic_tokens(phrase):
                continue
            if phrase not in committees:
                committees.append(phrase)

    return ParsedPosition(tuple(members), tuple(committees))


def topic_tokens(phrase: str) -> set[str]:
    """The words in a phrase that identify which committee it is."""
    tokens: list[str] = []
    low = phrase.lower()
    for abbrev, expansion in _ABBREVIATIONS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(abbrev)}(?![a-z0-9])", low):
            tokens.extend(expansion.split())
    tokens.extend(t for t in re.split(r"[^A-Za-z]+", low) if t)
    return {t for t in tokens if len(t) > 1 and t not in _TOPIC_STOPWORDS}


def chamber_of(phrase: str) -> str | None:
    """The chamber the filer named, or None if they did not name one."""
    low = phrase.lower()
    if re.search(r"\bhouse\b", low):
        return "house"
    if re.search(r"\bsenate\b|\bsen\b", low):
        return "senate"
    return None


def match_committees(
    phrase: str, committees: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Committees a phrase could name, best overlap first.

    Returns every equally-good candidate rather than a single winner. One
    result is a resolution; more than one is an ambiguity the caller must
    report rather than break, because a phrase naming no chamber
    ("Commerce Committee") really does name two real committees and
    picking one would be invention.
    """
    tokens = topic_tokens(phrase)
    if not tokens:
        return []
    chamber = chamber_of(phrase)

    scored: list[tuple[int, dict[str, Any]]] = []
    for committee in committees:
        if chamber and committee.get("type") != chamber:
            continue
        overlap = tokens & topic_tokens(committee.get("name") or "")
        if overlap:
            scored.append((len(overlap), committee))

    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [c for score, c in scored if score == best]
