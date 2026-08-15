"""Provenance for the detection patterns.

sift's patterns cite institutional typologies — FATF and others — so a
finding can be traced to an established standard rather than resting on
the author's judgement. This is the equivalent for packed.

Two things it does differently, both because of what this domain is
like:

**Citations carry a stance.** A work can support one pattern and
contradict another. Hall & Wayman is evidence *for* aggregating money by
committee seat and evidence *against* a votes-based timing pattern — the
same paper, opposite implications. A flat list of sources cannot say
that, and would let any citation read as blanket endorsement.

**An uncited pattern is visibly uncited.** Reporting `PROPOSED` with no
citations is a truthful statement about the state of the evidence.
Silence would let a reader assume grounding that is not there.

The registry is deliberately data, not code: adding a work is appending
to a YAML file, not editing Python. New works keep appearing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

def _patterns_dir() -> Path:
    """Locate the registry in a checkout or an installed wheel.

    In the repository the YAML sits at the project root, so it reads as
    project data rather than code. Packaging copies it inside the
    package, because a wheel without it raises on the first pattern
    result. Both layouts have to resolve.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here / "patterns", here.parent / "patterns"):
        if (candidate / "SOURCES.yaml").is_file():
            return candidate
    return here.parent / "patterns"   # report the repo path in the error


PATTERNS_DIR = _patterns_dir()
SOURCES_FILE = PATTERNS_DIR / "SOURCES.yaml"
PATTERNS_FILE = PATTERNS_DIR / "PATTERNS.yaml"

# A citation's relationship to the pattern citing it.
STANCES = frozenset({"supports", "limits", "contradicts"})


@dataclass
class Citation:
    """One work's bearing on one pattern."""

    source_key: str
    stance: str
    because: str
    citation: str = ""
    url: str = ""
    year: int | None = None
    kind: str = ""
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_key,
            "stance": self.stance,
            "because": self.because.strip(),
            "citation": self.citation.strip(),
            "url": self.url,
            "year": self.year,
            "kind": self.kind,
            "verified": self.verified,
        }


@dataclass
class Provenance:
    """What the literature says about one pattern."""

    pattern_name: str
    status: str
    note: str = ""
    citations: list[Citation] = field(default_factory=list)

    @property
    def contradicted(self) -> bool:
        return any(c.stance == "contradicts" for c in self.citations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_name": self.pattern_name,
            "status": self.status,
            "note": self.note.strip(),
            "contradicted": self.contradicted,
            "citations": [c.to_dict() for c in self.citations],
        }


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, Any], dict[str, Any]]:
    sources = yaml.safe_load(SOURCES_FILE.read_text()) or {}
    patterns = yaml.safe_load(PATTERNS_FILE.read_text()) or {}
    return sources, patterns


def _build(name: str, entry: dict[str, Any], sources: dict[str, Any]) -> Provenance:
    citations = []
    for c in entry.get("citations") or []:
        key = c.get("source", "")
        src = sources.get(key, {})
        citations.append(Citation(
            source_key=key,
            stance=c.get("stance", ""),
            because=c.get("because", ""),
            citation=src.get("citation", ""),
            url=src.get("url", ""),
            year=src.get("year"),
            kind=src.get("kind", ""),
            verified=bool(src.get("verified", False)),
        ))
    return Provenance(
        pattern_name=name,
        status=entry.get("status", "PROPOSED"),
        note=entry.get("note", ""),
        citations=citations,
    )


def for_pattern(pattern_name: str) -> Provenance | None:
    """Provenance for a built pattern, or None if it has no entry."""
    sources, patterns = _load()
    entry = (patterns.get("patterns") or {}).get(pattern_name)
    if entry is None:
        return None
    return _build(pattern_name, entry, sources.get("sources") or {})


def all_patterns() -> list[Provenance]:
    """Provenance for every built pattern."""
    sources, patterns = _load()
    src = sources.get("sources") or {}
    return [_build(n, e, src) for n, e in (patterns.get("patterns") or {}).items()]


def proposed_patterns() -> list[Provenance]:
    """Patterns considered but not built, with their grounding."""
    sources, patterns = _load()
    src = sources.get("sources") or {}
    return [_build(n, e, src) for n, e in (patterns.get("proposed") or {}).items()]


def sources() -> dict[str, Any]:
    """The full source registry."""
    return (_load()[0].get("sources") or {})


def rejected() -> dict[str, Any]:
    """Works evaluated and not adopted, with the reasoning."""
    return (_load()[0].get("rejected") or {})


def validate() -> list[str]:
    """Structural problems in the registry.

    Exists so a citation cannot silently reference a source that was
    renamed or never added — the failure mode of any keyed registry, and
    invisible without a check.
    """
    src_data, pat_data = _load()
    known = set(src_data.get("sources") or {})
    problems: list[str] = []

    for section in ("patterns", "proposed"):
        for name, entry in (pat_data.get(section) or {}).items():
            for c in entry.get("citations") or []:
                key = c.get("source", "")
                if key not in known:
                    problems.append(f"{section}/{name}: unknown source {key!r}")
                if c.get("stance") not in STANCES:
                    problems.append(
                        f"{section}/{name}: bad stance {c.get('stance')!r} on {key!r}"
                    )
                if not (c.get("because") or "").strip():
                    problems.append(f"{section}/{name}: citation {key!r} has no reason")

    for key, s in (src_data.get("sources") or {}).items():
        if not (s.get("citation") or "").strip():
            problems.append(f"sources/{key}: no citation text")

    return problems
