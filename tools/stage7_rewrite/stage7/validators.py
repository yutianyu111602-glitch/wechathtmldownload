"""Schema validation for Stage 7 extract output."""
from __future__ import annotations
import unicodedata
from typing import Any, Optional


REQUIRED_TOP_LEVEL = ["schema_version", "summary", "topics", "keywords", "entities", "events", "relations", "claims"]

ENTITY_REQUIRED = ["name", "type", "confidence", "evidence"]
EVENT_REQUIRED = ["name", "confidence", "evidence"]
RELATION_REQUIRED = ["subject", "predicate", "object", "confidence", "evidence"]
CLAIM_REQUIRED = ["claim", "confidence", "evidence"]
EVIDENCE_REQUIRED = ["quote"]

VALID_ENTITY_TYPES = {"person", "organization", "place", "brand", "work", "event", "concept", "product", "unknown"}
VALID_PREDICATES = {"founded", "joined", "performed_at", "collaborated_with", "located_in", "mentioned_with", "organized", "unknown"}
VALID_CLAIM_TYPES = {"fact", "opinion", "quote", "statistic", "announcement", "unknown"}

VALID_EVIDENCE_SOURCES = {"text", "image_ocr", "meta", "mixed"}
TITLE_PSEUDOQUOTE_PREFIX = "文章标题:"


def _is_title_pseudoquote(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith(TITLE_PSEUDOQUOTE_PREFIX)


def validate_extract(value: Any, source_text: str = "", ocr_digest: str = "") -> dict:
    """Validate a Stage 7 extract object. Returns {ok, data, errors, warnings}.

    Includes bio exact substring check and evidence exact match check.
    """
    errors: list[str] = []
    warnings: list[str] = []
    bio_stats = {
        "entity_bio_total": 0,
        "entity_bio_exact_match_pass": 0,
        "entity_bio_soft_match_pass": 0,
        "entity_bio_cleared": 0,
        "entity_bio_abstraction_rejected": 0,
    }
    evidence_stats = {
        "entity_evidence_exact_match_pass": 0,
        "entity_evidence_soft_match_pass": 0,
        "entity_evidence_failed": 0,
        "event_evidence_exact_match_pass": 0,
        "event_evidence_soft_match_pass": 0,
        "event_evidence_failed": 0,
        "relation_evidence_exact_match_pass": 0,
        "relation_evidence_soft_match_pass": 0,
        "relation_evidence_failed": 0,
        "claim_evidence_exact_match_pass": 0,
        "claim_evidence_soft_match_pass": 0,
        "claim_evidence_failed": 0,
    }

    if not isinstance(value, dict):
        return {"ok": False, "data": None, "errors": ["Root is not an object"], "warnings": [], "bio_stats": bio_stats, "evidence_stats": evidence_stats}

    for field in REQUIRED_TOP_LEVEL:
        if field not in value:
            errors.append(f"Missing required field: {field}")

    for arr_field in ["entities", "events", "relations", "claims", "topics", "keywords"]:
        if arr_field in value and not isinstance(value[arr_field], list):
            errors.append(f"Field {arr_field} must be an array")

    entities = value.get("entities", [])
    if isinstance(entities, list):
        for i, ent in enumerate(entities):
            if not isinstance(ent, dict):
                errors.append(f"Entity[{i}] is not an object")
                continue
            for req in ENTITY_REQUIRED:
                if req not in ent:
                    errors.append(f"Entity[{i}] missing {req}")
            if ent.get("type") and ent.get("type") not in VALID_ENTITY_TYPES:
                warnings.append(f"Entity[{i}] unknown type: {ent['type']}")
            if "confidence" in ent and not (0.0 <= float(ent["confidence"]) <= 1.0):
                warnings.append(f"Entity[{i}] confidence out of range")
            if ent.get("evidence_source") and ent["evidence_source"] not in VALID_EVIDENCE_SOURCES:
                warnings.append(f"Entity[{i}] invalid evidence_source: {ent['evidence_source']}")

            bio_stats["entity_bio_total"] += 1
            bio = ent.get("bio", "")
            if bio:
                bio_match = substring_match_kind(bio, source_text, ocr_digest)
                if bio_match == "exact":
                    bio_stats["entity_bio_exact_match_pass"] += 1
                elif bio_match == "normalized":
                    bio_stats["entity_bio_soft_match_pass"] += 1
                    warnings.append(f"bio_normalized_substring:Entity[{i}] '{bio[:50]}...'")
                else:
                    bio_stats["entity_bio_abstraction_rejected"] += 1
                    warnings.append(f"bio_not_exact_substring:Entity[{i}] '{bio[:50]}...'")
                    ent["bio"] = ""
                    bio_stats["entity_bio_cleared"] += 1
                    warnings.append(f"bio_cleared_due_to_abstraction:Entity[{i}]")

            _validate_evidence(ent.get("evidence", []), f"Entity[{i}]", errors, warnings)
            _check_evidence_exact(ent.get("evidence", []), source_text, ocr_digest, f"Entity[{i}]", evidence_stats, "entity", warnings, errors)

    events = value.get("events", [])
    if isinstance(events, list):
        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                errors.append(f"Event[{i}] is not an object")
                continue
            for req in EVENT_REQUIRED:
                if req not in ev:
                    errors.append(f"Event[{i}] missing {req}")
            if ev.get("evidence_source") and ev["evidence_source"] not in VALID_EVIDENCE_SOURCES:
                warnings.append(f"Event[{i}] invalid evidence_source: {ev['evidence_source']}")
            _validate_evidence(ev.get("evidence", []), f"Event[{i}]", errors, warnings)
            _check_evidence_exact(ev.get("evidence", []), source_text, ocr_digest, f"Event[{i}]", evidence_stats, "event", warnings, errors)

    relations = value.get("relations", [])
    if isinstance(relations, list):
        for i, rel in enumerate(relations):
            if not isinstance(rel, dict):
                errors.append(f"Relation[{i}] is not an object")
                continue
            for req in RELATION_REQUIRED:
                if req not in rel:
                    errors.append(f"Relation[{i}] missing {req}")
            if rel.get("predicate") and rel["predicate"] not in VALID_PREDICATES:
                warnings.append(f"Relation[{i}] unknown predicate: {rel['predicate']}")
            if rel.get("evidence_source") and rel["evidence_source"] not in VALID_EVIDENCE_SOURCES:
                warnings.append(f"Relation[{i}] invalid evidence_source: {rel['evidence_source']}")
            _validate_evidence(rel.get("evidence", []), f"Relation[{i}]", errors, warnings)
            _check_evidence_exact(rel.get("evidence", []), source_text, ocr_digest, f"Relation[{i}]", evidence_stats, "relation", warnings, errors)

    claims = value.get("claims", [])
    if isinstance(claims, list):
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append(f"Claim[{i}] is not an object")
                continue
            for req in CLAIM_REQUIRED:
                if req not in claim:
                    errors.append(f"Claim[{i}] missing {req}")
            if claim.get("claim_type") and claim["claim_type"] not in VALID_CLAIM_TYPES:
                warnings.append(f"Claim[{i}] unknown claim_type: {claim['claim_type']}")
            if claim.get("evidence_source") and claim["evidence_source"] not in VALID_EVIDENCE_SOURCES:
                warnings.append(f"Claim[{i}] invalid evidence_source: {claim['evidence_source']}")
            _validate_evidence(claim.get("evidence", []), f"Claim[{i}]", errors, warnings)
            _check_evidence_exact(claim.get("evidence", []), source_text, ocr_digest, f"Claim[{i}]", evidence_stats, "claim", warnings, errors)

    ok = len(errors) == 0
    if ok and isinstance(value, dict):
        for field in ["entities", "events", "relations", "claims", "topics", "keywords"]:
            if field not in value:
                value[field] = []

    return {
        "ok": ok,
        "data": value if ok else None,
        "errors": errors,
        "warnings": warnings,
        "bio_stats": bio_stats,
        "evidence_stats": evidence_stats,
    }


def _is_exact_substring(value: str, source_text: str, ocr_digest: str) -> bool:
    """Check if value is an exact substring of source_text or ocr_digest."""
    if not value or not value.strip():
        return True
    v = value.strip()
    if source_text and v in source_text:
        return True
    if ocr_digest and v in ocr_digest:
        return True
    return False


def _normalize_for_substring(value: str) -> str:
    """Normalize only for quote containment checks, not canonical output."""
    normalized = []
    for ch in str(value):
        category = unicodedata.category(ch)
        if ch.isspace() or category[0] in {"P", "Z"}:
            continue
        normalized.append(ch.casefold())
    return "".join(normalized)


def _is_normalized_substring(value: str, source_text: str, ocr_digest: str) -> bool:
    """Allow punctuation/whitespace drift while preserving substring order."""
    if not value or not value.strip():
        return True
    v = _normalize_for_substring(value)
    if len(v) < 4:
        return False
    for candidate in (source_text, ocr_digest):
        if candidate and v in _normalize_for_substring(candidate):
            return True
    return False


def substring_match_kind(value: str, source_text: str = "", ocr_digest: str = "") -> Optional[str]:
    if _is_exact_substring(value, source_text, ocr_digest):
        return "exact"
    if _is_normalized_substring(value, source_text, ocr_digest):
        return "normalized"
    return None


def _check_evidence_exact(evidence_list: list, source_text: str, ocr_digest: str,
                          context: str, stats: dict, kind: str, warnings: list,
                          errors: list) -> None:
    """Check evidence quotes are exact substrings.

    Exact-span is a hard production gate: a non-empty quote that is not a
    verbatim substring of article text or OCR digest must make validation fail,
    not merely add a soft warning.
    """
    pass_key = f"{kind}_evidence_exact_match_pass"
    soft_pass_key = f"{kind}_evidence_soft_match_pass"
    fail_key = f"{kind}_evidence_failed"
    for ev in evidence_list:
        if not isinstance(ev, dict):
            continue
        quote = ev.get("quote", "")
        if quote and _is_title_pseudoquote(quote):
            stats[fail_key] = stats.get(fail_key, 0) + 1
            msg = f"evidence_title_pseudoquote:{context} '{quote[:50]}...'"
            warnings.append(msg)
            errors.append(msg)
        elif quote:
            match_kind = substring_match_kind(quote, source_text, ocr_digest)
            if match_kind == "exact":
                stats[pass_key] = stats.get(pass_key, 0) + 1
            elif match_kind == "normalized":
                stats[soft_pass_key] = stats.get(soft_pass_key, 0) + 1
                warnings.append(f"evidence_normalized_substring:{context} '{quote[:50]}...'")
            else:
                stats[fail_key] = stats.get(fail_key, 0) + 1
                msg = f"evidence_not_exact_substring:{context} '{quote[:50]}...'"
                warnings.append(msg)
                errors.append(msg)


def _validate_evidence(evidence_list: Any, context: str, errors: list, warnings: list) -> None:
    if not isinstance(evidence_list, list):
        errors.append(f"{context} evidence is not an array")
        return
    for j, ev in enumerate(evidence_list):
        if not isinstance(ev, dict):
            errors.append(f"{context} evidence[{j}] not an object")
            continue
        if "quote" not in ev:
            errors.append(f"{context} evidence[{j}] missing quote")
        elif not str(ev.get("quote", "")).strip():
            errors.append(f"{context} evidence[{j}] blank quote")


def check_evidence_quotes(source_text: str, extract: dict) -> dict:
    """Check that evidence quotes are substrings of source text."""
    total = 0
    hit = 0
    miss = 0
    warnings: list[str] = []
    miss_examples: list[str] = []

    def check_list(items: list, label: str) -> None:
        nonlocal total, hit, miss
        for item in items:
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                for ev in evidence:
                    total += 1
                    quote = ev.get("quote", "") if isinstance(ev, dict) else ""
                    if not quote:
                        miss += 1
                        warnings.append(f"{label} empty quote")
                        continue
                    if _is_title_pseudoquote(quote):
                        miss += 1
                        warnings.append(f"{label} title pseudoquote: '{quote[:80]}'")
                    elif substring_match_kind(quote, source_text, ""):
                        hit += 1
                    else:
                        miss += 1
                        if len(miss_examples) < 20:
                            miss_examples.append(f"{label}: '{quote[:80]}'")
                        if len(quote) < 5:
                            warnings.append(f"{label} very short quote: '{quote}'")

    check_list(extract.get("entities", []), "entity")
    check_list(extract.get("events", []), "event")
    check_list(extract.get("relations", []), "relation")
    check_list(extract.get("claims", []), "claim")

    hit_rate = hit / total if total > 0 else 1.0
    return {
        "evidence_total": total,
        "evidence_hit": hit,
        "evidence_miss": miss,
        "evidence_hit_rate": hit_rate,
        "warnings": warnings,
        "miss_examples_top20": miss_examples,
    }
