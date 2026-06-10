"""Schema normalization for Stage 7 extract output."""
from __future__ import annotations
from typing import Any


TOP_LEVEL_DEFAULTS = {
    "schema_version": "article_extract.v1",
    "summary": "",
    "topics": [],
    "keywords": [],
    "entities": [],
    "events": [],
    "relations": [],
    "claims": [],
    "ocr_evidence": [],
    "quality": {
        "is_empty": False,
        "empty_reason": "",
        "parse_repaired": False,
        "has_ocr_only_items": False,
        "warnings": [],
    },
}

REQUIRED_TOP_LEVEL_KEYS = set(TOP_LEVEL_DEFAULTS.keys())


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, number))


def _normalize_evidence(value: Any) -> tuple[list[dict], bool]:
    if not isinstance(value, list):
        return [], value is not None
    changed = False
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            changed = True
            continue
        quote = item.get("quote") or item.get("evidence_text") or item.get("text")
        if not isinstance(quote, str) or not quote.strip():
            changed = True
            continue
        ev = dict(item)
        ev["quote"] = quote.strip()
        normalized.append(ev)
        if "quote" not in item or item.get("quote") != ev["quote"]:
            changed = True
    return normalized, changed


def _normalize_entities(value: Any) -> tuple[list[dict], dict]:
    stats = {"item_defaults": 0, "dropped_items": 0}
    if not isinstance(value, list):
        return [], stats
    normalized = []
    for item in value:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            stats["dropped_items"] += 1
            continue
        evidence, evidence_changed = _normalize_evidence(item.get("evidence", []))
        if not evidence:
            stats["dropped_items"] += 1
            continue
        ent = dict(item)
        ent["name"] = str(ent.get("name", "")).strip()
        ent["evidence"] = evidence
        if not ent.get("type"):
            ent["type"] = "unknown"
            stats["item_defaults"] += 1
        if "confidence" not in ent:
            ent["confidence"] = 0.5
            stats["item_defaults"] += 1
        else:
            coerced = _coerce_confidence(ent.get("confidence"))
            if coerced != ent.get("confidence"):
                stats["item_defaults"] += 1
            ent["confidence"] = coerced
        if not isinstance(ent.get("aliases", []), list):
            ent["aliases"] = []
            stats["item_defaults"] += 1
        if evidence_changed:
            stats["item_defaults"] += 1
        normalized.append(ent)
    return normalized, stats


def _normalize_events(value: Any) -> tuple[list[dict], dict]:
    stats = {"item_defaults": 0, "dropped_items": 0}
    if not isinstance(value, list):
        return [], stats
    normalized = []
    for item in value:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            stats["dropped_items"] += 1
            continue
        evidence, evidence_changed = _normalize_evidence(item.get("evidence", []))
        if not evidence:
            stats["dropped_items"] += 1
            continue
        event = dict(item)
        event["name"] = str(event.get("name", "")).strip()
        event["evidence"] = evidence
        if "confidence" not in event:
            event["confidence"] = 0.5
            stats["item_defaults"] += 1
        else:
            coerced = _coerce_confidence(event.get("confidence"))
            if coerced != event.get("confidence"):
                stats["item_defaults"] += 1
            event["confidence"] = coerced
        if evidence_changed:
            stats["item_defaults"] += 1
        normalized.append(event)
    return normalized, stats


def _normalize_relations(value: Any) -> tuple[list[dict], dict]:
    stats = {"item_defaults": 0, "dropped_items": 0}
    if not isinstance(value, list):
        return [], stats
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            stats["dropped_items"] += 1
            continue
        subject = str(item.get("subject") or item.get("subject_id") or "").strip()
        obj = str(item.get("object") or item.get("object_id") or "").strip()
        if not subject or not obj:
            stats["dropped_items"] += 1
            continue
        evidence, evidence_changed = _normalize_evidence(item.get("evidence", []))
        if not evidence:
            stats["dropped_items"] += 1
            continue
        relation = dict(item)
        relation["subject"] = subject
        relation["object"] = obj
        relation["predicate"] = str(relation.get("predicate") or "unknown").strip() or "unknown"
        relation["evidence"] = evidence
        if "confidence" not in relation:
            relation["confidence"] = 0.5
            stats["item_defaults"] += 1
        else:
            coerced = _coerce_confidence(relation.get("confidence"))
            if coerced != relation.get("confidence"):
                stats["item_defaults"] += 1
            relation["confidence"] = coerced
        if evidence_changed:
            stats["item_defaults"] += 1
        normalized.append(relation)
    return normalized, stats


def _normalize_claims(value: Any) -> tuple[list[dict], dict]:
    stats = {"item_defaults": 0, "dropped_items": 0}
    if not isinstance(value, list):
        return [], stats
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            stats["dropped_items"] += 1
            continue
        claim_text = item.get("claim", item.get("claim_text", ""))
        if not str(claim_text).strip():
            stats["dropped_items"] += 1
            continue
        evidence, evidence_changed = _normalize_evidence(item.get("evidence", []))
        if not evidence:
            stats["dropped_items"] += 1
            continue
        claim = dict(item)
        claim["claim"] = str(claim_text).strip()
        claim["evidence"] = evidence
        if "confidence" not in claim:
            claim["confidence"] = 0.5
            stats["item_defaults"] += 1
        else:
            coerced = _coerce_confidence(claim.get("confidence"))
            if coerced != claim.get("confidence"):
                stats["item_defaults"] += 1
            claim["confidence"] = coerced
        if evidence_changed:
            stats["item_defaults"] += 1
        normalized.append(claim)
    return normalized, stats


def normalize_extract_schema(parsed: Any) -> tuple[Any, dict]:
    """Normalize a parsed JSON object to have all required top-level fields.

    Returns (normalized_data, stats) where stats contains:
      - normalized: bool
      - missing_fields: list[str]
      - is_empty_object: bool (True if original was {})
    """
    stats = {
        "normalized": False,
        "missing_fields": [],
        "is_empty_object": False,
        "item_defaults": 0,
        "dropped_items": 0,
    }

    if not isinstance(parsed, dict):
        return parsed, stats

    # Check if completely empty object
    if len(parsed) == 0:
        stats["is_empty_object"] = True
        return parsed, stats

    missing = REQUIRED_TOP_LEVEL_KEYS - set(parsed.keys())
    normalized = dict(parsed)
    for key in missing:
        default_val = TOP_LEVEL_DEFAULTS[key]
        if isinstance(default_val, list):
            normalized[key] = []
        elif isinstance(default_val, dict):
            normalized[key] = dict(default_val)
        elif isinstance(default_val, str):
            normalized[key] = ""
        elif isinstance(default_val, bool):
            normalized[key] = False
        else:
            normalized[key] = default_val

    if missing:
        stats["normalized"] = True
    stats["missing_fields"] = sorted(missing)
    for key, normalizer in [
        ("entities", _normalize_entities),
        ("events", _normalize_events),
        ("relations", _normalize_relations),
        ("claims", _normalize_claims),
    ]:
        normalized_items, item_stats = normalizer(normalized.get(key, []))
        if normalized_items != normalized.get(key, []):
            stats["normalized"] = True
        normalized[key] = normalized_items
        stats["item_defaults"] += item_stats["item_defaults"]
        stats["dropped_items"] += item_stats["dropped_items"]
    return normalized, stats


def is_legal_empty(normalized: dict) -> bool:
    """Check if a normalized object is a legal empty result.

    Legal empty means:
    - All required fields present
    - entities/events/relations/claims are all empty arrays
    - quality.is_empty = True
    - quality.empty_reason is non-empty
    """
    if not isinstance(normalized, dict):
        return False
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in normalized:
            return False
    for arr_key in ["entities", "events", "relations", "claims"]:
        val = normalized.get(arr_key)
        if not isinstance(val, list) or len(val) > 0:
            return False
    quality = normalized.get("quality", {})
    if not isinstance(quality, dict):
        return False
    if not quality.get("is_empty"):
        return False
    if not quality.get("empty_reason"):
        return False
    return True
