"""Qdrant collection schema preparation (definition only, no server start).

Qdrant is NOT running on Mac. This module only prepares the collection
schema definition and writes collection_plan.md for later deployment.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


PAYLOAD_INDEX_FIELDS = [
    {"field": "unit_type", "type": "keyword", "description": "entity/entity_identity/entity_mention/event/relation/claim/article/ocr_evidence/account_profile"},
    {"field": "account", "type": "keyword", "description": "WeChat source account"},
    {"field": "article_hash", "type": "keyword", "description": "SHA1 of article content"},
    {"field": "article_id", "type": "keyword", "description": "WeChat article ID"},
    {"field": "entity_type", "type": "keyword", "description": "person/org/location/etc (entities only)"},
    {"field": "confidence", "type": "float", "description": "LLM extraction confidence score"},
    {"field": "evidence_source", "type": "keyword", "description": "chunk_id or ocr source"},
    {"field": "created_at", "type": "datetime", "description": "Embedding creation timestamp"},
]


@dataclass
class CollectionDef:
    """Qdrant collection definition (not created, just described)."""
    name: str
    model: str
    dim: int
    object_kind: str
    distance: str = "Cosine"
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100
    payload_index_fields: list[dict] = field(default_factory=lambda: PAYLOAD_INDEX_FIELDS)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_collection_defs(
    model: str = "infgrad/stella-large-zh-v2",
    dim: int = 1024,
) -> list[CollectionDef]:
    """Build collection definitions for all object kinds."""
    safe_model = model.replace("/", "_").replace(".", "_")
    kinds = [
        "entity",
        "entity_identity",
        "entity_mention",
        "event",
        "relation",
        "claim",
        "article",
        "ocr_evidence",
        "account_profile",
    ]
    return [
        CollectionDef(
            name=f"wechat_{kind}_{safe_model}_{dim}",
            model=model,
            dim=dim,
            object_kind=kind,
        )
        for kind in kinds
    ]


def write_collection_plan(
    output_dir: Path,
    collection_defs: list[CollectionDef],
) -> Path:
    """Write collection_plan.md describing collections to create later."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "collection_plan.md"

    lines = [
        "# Qdrant Collection Plan",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "**NOTE**: Qdrant is NOT running on Mac. This is a definition-only plan.",
        "Collections will be created when Qdrant is deployed.",
        "",
        "## Collections",
        "",
    ]

    for cd in collection_defs:
        lines.append(f"### `{cd.name}`")
        lines.append("")
        lines.append(f"- **Model**: {cd.model}")
        lines.append(f"- **Dimension**: {cd.dim}")
        lines.append(f"- **Distance**: {cd.distance}")
        lines.append(f"- **Object Kind**: {cd.object_kind}")
        lines.append(f"- **HNSW M**: {cd.hnsw_m}")
        lines.append(f"- **HNSW ef_construct**: {cd.hnsw_ef_construct}")
        lines.append("")
        lines.append("#### Payload Index Fields")
        lines.append("")
        lines.append("| Field | Type | Description |")
        lines.append("|-------|------|-------------|")
        for f in cd.payload_index_fields:
            lines.append(f"| {f['field']} | {f['type']} | {f['description']} |")
        lines.append("")

    lines.append("## Create Command (reference)")
    lines.append("")
    lines.append("```python")
    lines.append("from qdrant_client import QdrantClient")
    lines.append("from qdrant_client.models import Distance, VectorParams, PayloadSchemaType")
    lines.append("")
    lines.append("client = QdrantClient(url='http://localhost:6333')")
    lines.append("")
    for cd in collection_defs:
        lines.append(f"client.create_collection(")
        lines.append(f"    collection_name='{cd.name}',")
        lines.append(f"    vectors_config=VectorParams(size={cd.dim}, distance=Distance.{cd.distance.upper()}),")
        lines.append(f"    hnsw_config={{'m': {cd.hnsw_m}, 'ef_construct': {cd.hnsw_ef_construct}}},")
        lines.append(f")")
        for f in cd.payload_index_fields:
            ptype = "PayloadSchemaType.KEYWORD" if f["type"] == "keyword" else f"PayloadSchemaType.{f['type'].upper()}"
            lines.append(f"client.create_payload_index('{cd.name}', '{f['field']}', {ptype})")
        lines.append("")
    lines.append("```")
    lines.append("")

    plan_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote collection plan: {plan_path}")
    return plan_path
