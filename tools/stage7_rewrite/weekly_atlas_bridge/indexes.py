"""In-memory indexes for registry, atlas alias export, and optional Qdrant review."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .normalize import atlas_entity_id, normalize_name


@dataclass
class ArtistRecord:
    artist_id: str
    canonical_name: str
    verified: bool
    bio_manual: str = ""
    avatar_url: str = ""
    source: str = "weekly_registry"


@dataclass
class MatchIndex:
    by_norm: dict[str, list[ArtistRecord]] = field(default_factory=dict)
    blocked_norm: set[str] = field(default_factory=set)

    def add(self, record: ArtistRecord, alias: str | None = None) -> None:
        keys = {normalize_name(record.canonical_name)}
        if alias:
            keys.add(normalize_name(alias))
        for key in keys:
            if not key:
                continue
            self.by_norm.setdefault(key, []).append(record)

    def exact(self, raw: str) -> list[ArtistRecord]:
        return list(self.by_norm.get(normalize_name(raw), []))


def load_registry_seed(path: Path) -> MatchIndex:
    payload = json.loads(path.read_text(encoding="utf-8"))
    index = MatchIndex()
    for term in payload.get("blocked_lineup_terms") or []:
        key = normalize_name(str(term))
        if key:
            index.blocked_norm.add(key)
    for row in payload.get("artists") or []:
        if not isinstance(row, dict):
            continue
        aid = atlas_entity_id(str(row.get("artist_id") or ""))
        if not aid:
            continue
        record = ArtistRecord(
            artist_id=aid,
            canonical_name=str(row.get("canonical_name") or row.get("artist_id") or ""),
            verified=bool(row.get("verified")),
            bio_manual=str(row.get("bio_manual") or ""),
            avatar_url=str(row.get("avatar_url") or ""),
            source="weekly_registry",
        )
        index.add(record)
        for alias in row.get("aliases") or []:
            if alias:
                index.add(record, str(alias))
    return index


def load_atlas_alias_export(path: Path) -> MatchIndex:
    """JSONL rows: artist_id, canonical_name, alias, verified (optional)."""
    index = MatchIndex()
    if not path.is_file():
        return index
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        aid = atlas_entity_id(str(row.get("artist_id") or ""))
        if not aid:
            continue
        record = ArtistRecord(
            artist_id=aid,
            canonical_name=str(row.get("canonical_name") or ""),
            verified=bool(row.get("verified")),
            bio_manual=str(row.get("bio_manual") or ""),
            avatar_url=str(row.get("avatar_url") or ""),
            source="atlas_alias_export",
        )
        alias = row.get("alias") or row.get("canonical_name")
        index.add(record, str(alias) if alias else None)
    return index


def merge_indexes(*indexes: MatchIndex) -> MatchIndex:
    merged = MatchIndex()
    for idx in indexes:
        merged.blocked_norm |= idx.blocked_norm
        for key, records in idx.by_norm.items():
            merged.by_norm.setdefault(key, []).extend(records)
    return merged


def fuzzy_candidates(raw: str, index: MatchIndex, *, min_score: float = 0.92, limit: int = 5) -> list[tuple[ArtistRecord, float]]:
    needle = normalize_name(raw)
    if not needle or needle in index.blocked_norm:
        return []
    scored: list[tuple[ArtistRecord, float]] = []
    seen: set[str] = set()
    for norm_key, records in index.by_norm.items():
        if not norm_key:
            continue
        ratio = SequenceMatcher(None, needle, norm_key).ratio()
        if ratio < min_score:
            continue
        for record in records:
            if record.artist_id in seen:
                continue
            seen.add(record.artist_id)
            scored.append((record, round(ratio, 4)))
    scored.sort(key=lambda row: row[1], reverse=True)
    return scored[:limit]


def resolve_person_current_collection(qdrant_url: str) -> str | None:
    try:
        response = requests.get(f"{qdrant_url.rstrip('/')}/aliases", timeout=15)
        if response.status_code >= 400:
            return None
        rows = (response.json().get("result") or {}).get("aliases") or []
        for row in rows:
            if str(row.get("alias_name") or "") == "person_current":
                return str(row.get("collection_name") or "")
    except requests.RequestException:
        return None
    return None


def qdrant_scroll_payloads(qdrant_url: str, collection: str, *, limit: int = 400) -> list[dict[str, Any]]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/scroll",
        json={"limit": limit, "with_payload": True, "with_vector": True},
        timeout=60,
    )
    if response.status_code >= 400:
        return []
    return (response.json().get("result") or {}).get("points") or []


def qdrant_search_vector(qdrant_url: str, collection: str, vector: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    for endpoint, body in (
        ("search", {"vector": vector, "limit": limit, "with_payload": True}),
        ("query", {"query": vector, "limit": limit, "with_payload": True}),
    ):
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/{endpoint}",
            json=body,
            timeout=60,
        )
        if response.status_code == 404 and endpoint == "search":
            continue
        if response.status_code >= 400:
            return []
        result = response.json().get("result")
        if isinstance(result, dict):
            result = result.get("points")
        return result or []
    return []


def payload_label(payload: dict[str, Any]) -> str:
    for key in ("canonical_name", "name", "title", "text", "display_name"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


@dataclass
class VectorReviewHit:
    point_id: str
    score: float
    label: str
    payload: dict[str, Any]


class VectorReviewIndex:
    """Read-only ANN review: seed vector from best payload label match, then search."""

    def __init__(self, qdrant_url: str, collection: str, *, scroll_limit: int = 400) -> None:
        self.qdrant_url = qdrant_url
        self.collection = collection
        self.points = qdrant_scroll_payloads(qdrant_url, collection, limit=scroll_limit)

    @classmethod
    def open(cls, qdrant_url: str) -> VectorReviewIndex | None:
        collection = resolve_person_current_collection(qdrant_url)
        if not collection:
            return None
        return cls(qdrant_url, collection)

    def review(self, raw: str, *, min_label_score: float = 0.88) -> VectorReviewHit | None:
        needle = normalize_name(raw)
        if not needle:
            return None
        best_point = None
        best_ratio = 0.0
        for point in self.points:
            payload = point.get("payload") or {}
            label = payload_label(payload)
            ratio = SequenceMatcher(None, needle, normalize_name(label)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_point = point
        if not best_point or best_ratio < min_label_score:
            return None
        vector = best_point.get("vector")
        if not vector:
            return None
        hits = qdrant_search_vector(self.qdrant_url, self.collection, vector, limit=3)
        if not hits:
            return None
        top = hits[0]
        payload = top.get("payload") or {}
        try:
            score = float(top.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        return VectorReviewHit(
            point_id=str(top.get("id") or ""),
            score=score,
            label=payload_label(payload),
            payload=payload,
        )
