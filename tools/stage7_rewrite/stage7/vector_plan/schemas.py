"""Vector job schemas for Stage 8 embedding pipeline."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class VectorJob:
    """A single embedding job for one extracted object."""
    job_id: str
    object_kind: str  # entity | entity_identity | entity_mention | event | relation | claim | article | ocr_evidence | account_profile
    object_id: str
    article_id: str
    source_path: str
    model: str
    endpoint: str
    dim: int
    collection: str
    canonical_text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_sha1(self) -> str:
        return hashlib.sha1(self.canonical_text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["text_sha1"] = self.text_sha1
        return d


@dataclass
class VectorResult:
    """Successful embedding result."""
    job_id: str
    vector: list[float]
    model: str
    dim: int
    endpoint: str
    namespace: str
    text_sha1: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VectorFailed:
    """Failed embedding record."""
    job_id: str
    error_type: str
    error_message: str
    endpoint: str
    model: str
    text_sha1: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VectorManifest:
    """Manifest describing a vector job batch."""
    schema_version: str = "vector_manifest.v1"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_stage7_root: str = ""
    job_count: int = 0
    by_unit_type: dict[str, int] = field(default_factory=dict)
    embedding_models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
