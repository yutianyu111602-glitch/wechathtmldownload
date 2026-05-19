"""Entity resolver ladder for weekly lineup strings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .indexes import MatchIndex, VectorReviewIndex, fuzzy_candidates, merge_indexes
from .normalize import normalize_name

MatchMethod = Literal[
    "registry_exact",
    "alias_exact",
    "fuzzy_unique",
    "fuzzy_multiple",
    "vector_candidate",
    "no_match",
    "blocked",
]

DisplayTier = Literal["show", "show_with_hint", "hide"]


@dataclass
class ResolvedArtist:
    raw: str
    artist_id: str | None
    canonical_name: str | None
    match_score: float
    match_method: MatchMethod
    verified: bool
    display_tier: DisplayTier
    candidates: list[dict[str, Any]] | None = None
    vector_review: dict[str, Any] | None = None

    def to_contract_row(self, event_id: str) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "raw": self.raw,
            "artist_id": self.artist_id,
            "canonical_name": self.canonical_name,
            "match_score": self.match_score,
            "match_method": self.match_method,
            "verified": self.verified,
            "display_tier": self.display_tier,
            "candidates": self.candidates,
            "vector_review": self.vector_review,
        }


@dataclass
class EntityResolver:
    index: MatchIndex
    vector_review: VectorReviewIndex | None = None
    fuzzy_threshold: float = 0.92
    alias_exact_threshold: float = 0.98

    def resolve(self, raw: str) -> ResolvedArtist:
        text = (raw or "").strip()
        if not text:
            return ResolvedArtist(
                raw=raw,
                artist_id=None,
                canonical_name=None,
                match_score=0.0,
                match_method="no_match",
                verified=False,
                display_tier="hide",
            )

        norm = normalize_name(text)
        if norm in self.index.blocked_norm:
            return ResolvedArtist(
                raw=text,
                artist_id=None,
                canonical_name=None,
                match_score=0.0,
                match_method="blocked",
                verified=False,
                display_tier="hide",
            )

        exact = self.index.exact(text)
        distinct_exact = []
        seen_ids = set()
        for r in exact:
            if r.artist_id not in seen_ids:
                seen_ids.add(r.artist_id)
                distinct_exact.append(r)

        if len(distinct_exact) == 1:
            rec = distinct_exact[0]
            method: MatchMethod = "registry_exact" if rec.source == "weekly_registry" else "alias_exact"
            return ResolvedArtist(
                raw=text,
                artist_id=rec.artist_id,
                canonical_name=rec.canonical_name,
                match_score=1.0,
                match_method=method,
                verified=rec.verified,
                display_tier="show",
            )
        if len(distinct_exact) > 1:
            cands = [
                {"artist_id": r.artist_id, "canonical_name": r.canonical_name, "score": 1.0}
                for r in distinct_exact[:5]
            ]
            return ResolvedArtist(
                raw=text,
                artist_id=None,
                canonical_name=cands[0]["canonical_name"],
                match_score=1.0,
                match_method="fuzzy_multiple",
                verified=False,
                display_tier="show_with_hint",
                candidates=cands,
            )

        fuzzy = fuzzy_candidates(text, self.index, min_score=self.fuzzy_threshold)
        if len(fuzzy) == 1:
            rec, score = fuzzy[0]
            return ResolvedArtist(
                raw=text,
                artist_id=rec.artist_id,
                canonical_name=rec.canonical_name,
                match_score=score,
                match_method="fuzzy_unique",
                verified=rec.verified,
                display_tier="show",
            )
        if len(fuzzy) > 1:
            cands = [
                {"artist_id": r.artist_id, "canonical_name": r.canonical_name, "score": s}
                for r, s in fuzzy
            ]
            return ResolvedArtist(
                raw=text,
                artist_id=None,
                canonical_name=cands[0]["canonical_name"],
                match_score=cands[0]["score"],
                match_method="fuzzy_multiple",
                verified=False,
                display_tier="show_with_hint",
                candidates=cands,
            )

        if self.vector_review is not None:
            hit = self.vector_review.review(text)
            if hit is not None:
                return ResolvedArtist(
                    raw=text,
                    artist_id=None,
                    canonical_name=hit.label or None,
                    match_score=round(hit.score, 4),
                    match_method="vector_candidate",
                    verified=False,
                    display_tier="hide",
                    vector_review={
                        "point_id": hit.point_id,
                        "score": hit.score,
                        "label": hit.label,
                        "collection": self.vector_review.collection,
                    },
                )

        return ResolvedArtist(
            raw=text,
            artist_id=None,
            canonical_name=None,
            match_score=0.0,
            match_method="no_match",
            verified=False,
            display_tier="hide",
        )


def resolve_lineup(
    names: list[str],
    resolver: EntityResolver,
    *,
    event_id: str,
) -> list[dict[str, Any]]:
    return [resolver.resolve(name).to_contract_row(event_id) for name in names]


def build_resolver(
    registry_index: MatchIndex,
    alias_index: MatchIndex | None = None,
    *,
    qdrant_url: str | None = None,
) -> EntityResolver:
    merged = merge_indexes(registry_index, alias_index or MatchIndex())
    vector = VectorReviewIndex.open(qdrant_url) if qdrant_url else None
    return EntityResolver(index=merged, vector_review=vector)
