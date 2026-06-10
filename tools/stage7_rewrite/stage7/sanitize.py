"""Sanitize and limit extracted data to prevent output bloat."""
from __future__ import annotations
import re
from typing import Any

from .validators import substring_match_kind

# Generic words that should not be extracted as entities
GENERIC_WORDS = {
    "现场", "音乐", "派对", "活动", "观众", "嘉宾", "舞台",
    "时间", "地点", "今晚", "本周", "我们", "大家", "朋友",
    "城市", "声音", "艺术", "文化", "生活", "世界", "时代",
    "未来", "梦想", "精神", "力量", "美好", "精彩", "经典",
    "传奇", "故事", "历史", "传统", "现代", "创新", "发展",
    "进步", "成功", "辉煌", "荣耀", "感动", "温暖", "希望",
    "青春", "岁月", "时光", "记忆", "回忆", "经历", "人生",
    "人们", "人类", "社会", "国家", "民族", "人民", "群众",
}

DEFAULT_LIMITS = {
    "entities_max": 8,
    "events_max": 5,
    "relations_max": 8,
    "claims_max": 5,
    "topics_max": 8,
    "keywords_max": 10,
    "ocr_evidence_max": 8,
    "aliases_per_entity_max": 4,
    "evidence_per_item_max": 2,
    "bio_max_chars": 80,
    "summary_max_chars": 160,
    "claim_text_max_chars": 100,
    "event_description_max_chars": 100,
    "evidence_text_max_chars": 100,
    "ocr_text_max_chars": 200,
}

ARTICLE_LIMITS = {
    "entities_max": 16,
    "events_max": 8,
    "relations_max": 16,
    "claims_max": 10,
    "topics_max": 10,
    "keywords_max": 16,
}

TITLE_PSEUDOQUOTE_PREFIX = "文章标题:"


def is_title_pseudoquote(value: Any) -> bool:
    """Return true for metadata title-label evidence, not article-body quotes."""
    return isinstance(value, str) and value.strip().startswith(TITLE_PSEUDOQUOTE_PREFIX)


def _score_entity(entity: dict, source_text: str | None = None) -> float:
    """Score entity quality for ranking."""
    score = 0.0
    name = entity.get("name", "")
    if name:
        score += 10
    etype = entity.get("type", "unknown")
    if etype and etype != "unknown":
        score += 5
    evidence = entity.get("evidence", [])
    if evidence:
        score += 10
        for ev in evidence:
            if ev.get("evidence_text") or ev.get("quote"):
                score += 10
                break
    bio = entity.get("bio", "")
    if bio and source_text and substring_match_kind(bio, source_text, ""):
        score += 8
    confidence = entity.get("confidence")
    if confidence is not None:
        try:
            score += float(confidence) * 10
        except (ValueError, TypeError):
            pass
    for ev in evidence:
        sk = ev.get("source_kind", "")
        if sk == "article_text":
            score += 3
        elif sk == "image_ocr":
            score += 1
    if name and len(name) <= 1:
        score -= 10
    if name and name.strip() in GENERIC_WORDS:
        score -= 8
    return score


def _score_event(event: dict) -> float:
    """Score event quality for ranking."""
    score = 0.0
    if event.get("name"):
        score += 10
    if event.get("time_text"):
        score += 8
    if event.get("place_text"):
        score += 8
    if event.get("participants") or event.get("organizers"):
        score += 5
    if event.get("evidence"):
        score += 10
    return score


def _score_relation(relation: dict) -> float:
    """Score relation quality for ranking."""
    score = 0.0
    if relation.get("subject") and relation.get("object"):
        score += 10
    if relation.get("evidence"):
        score += 10
    confidence = relation.get("confidence")
    if confidence is not None:
        try:
            score += float(confidence) * 10
        except (ValueError, TypeError):
            pass
    predicate = relation.get("predicate", "")
    if predicate and len(predicate) > 1:
        score += 3
    return score


def _score_claim(claim: dict) -> float:
    """Score claim quality for ranking."""
    score = 0.0
    if claim.get("claim_text"):
        score += 10
    confidence = claim.get("confidence")
    if confidence is not None:
        try:
            score += float(confidence) * 10
        except (ValueError, TypeError):
            pass
    if claim.get("source_kind"):
        score += 3
    return score


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text to max_chars, return (truncated_text, was_truncated)."""
    if not text or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _limit_evidence(
    evidence: list[dict],
    max_items: int,
    max_text_chars: int,
    stats: dict,
    source_text: str | None = None,
) -> list[dict]:
    """Limit evidence array and truncate evidence_text."""
    if not evidence:
        return evidence
    result = []
    for ev in evidence[:max_items]:
        if not isinstance(ev, dict):
            continue
        text = ev.get("evidence_text", "") or ev.get("quote", "")
        truncated_text, was_truncated = _truncate_text(text, max_text_chars)
        if was_truncated:
            stats["evidence_truncated_count"] += 1
            stats["long_text_truncated_count"] += 1
        if "evidence_text" in ev:
            ev["evidence_text"] = truncated_text
        elif "quote" in ev:
            ev["quote"] = truncated_text
        quote = ev.get("quote", "") or ev.get("evidence_text", "")
        if is_title_pseudoquote(quote):
            stats["title_pseudoquote_dropped_count"] += 1
            continue
        if source_text and quote:
            match_kind = substring_match_kind(quote, source_text, "")
            if match_kind == "normalized":
                stats["evidence_normalized_match_kept_count"] += 1
            elif not match_kind:
                stats["evidence_non_exact_dropped_count"] += 1
                continue
        result.append(ev)
    if len(evidence) > max_items:
        stats["evidence_truncated_count"] += len(evidence) - max_items
    return result


def _keep_item_with_evidence(item: dict, stats: dict) -> bool:
    evidence = item.get("evidence", [])
    if isinstance(evidence, list) and not evidence:
        stats["items_dropped_after_evidence_prune_count"] += 1
        return False
    return True


def _sanitize_bio(bio: str, source_text: str | None, max_chars: int, stats: dict) -> tuple[str, list[str]]:
    """Sanitize bio with strict substring rules."""
    flags = []
    if not bio:
        return bio, flags
    if len(bio) <= max_chars:
        return bio, flags
    truncated = bio[:max_chars]
    match_kind = substring_match_kind(truncated, source_text or "", "")
    if match_kind:
        stats["long_text_truncated_count"] += 1
        flags.append("bio_truncated")
        if match_kind == "normalized":
            stats["bio_normalized_match_kept_count"] += 1
        return truncated, flags
    stats["long_text_truncated_count"] += 1
    flags.append("bio_cleared_after_truncate")
    return "", flags


def sanitize_extract_limits(
    data: dict,
    source_text: str | None = None,
    limits: dict | None = None,
) -> tuple[dict, dict]:
    """Sanitize and limit extracted data. Returns (sanitized_data, stats)."""
    if limits is None:
        limits = DEFAULT_LIMITS
    stats = {
        "entities_truncated_count": 0,
        "events_truncated_count": 0,
        "relations_truncated_count": 0,
        "claims_truncated_count": 0,
        "topics_truncated_count": 0,
        "keywords_truncated_count": 0,
        "evidence_truncated_count": 0,
        "title_pseudoquote_dropped_count": 0,
        "long_text_truncated_count": 0,
        "aliases_truncated_count": 0,
        "bio_cleared_count": 0,
        "evidence_non_exact_dropped_count": 0,
        "evidence_normalized_match_kept_count": 0,
        "bio_normalized_match_kept_count": 0,
        "items_dropped_after_evidence_prune_count": 0,
    }
    data = dict(data)
    entities = data.get("entities", [])
    if isinstance(entities, list) and len(entities) > limits["entities_max"]:
        scored = [(e, _score_entity(e, source_text)) for e in entities if isinstance(e, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [e for e, _ in scored[:limits["entities_max"]]]
        stats["entities_truncated_count"] += len(entities) - len(kept)
        data["entities"] = kept
    events = data.get("events", [])
    if isinstance(events, list) and len(events) > limits["events_max"]:
        scored = [(e, _score_event(e)) for e in events if isinstance(e, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [e for e, _ in scored[:limits["events_max"]]]
        stats["events_truncated_count"] += len(events) - len(kept)
        data["events"] = kept
    relations = data.get("relations", [])
    if isinstance(relations, list) and len(relations) > limits["relations_max"]:
        scored = [(r, _score_relation(r)) for r in relations if isinstance(r, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [r for r, _ in scored[:limits["relations_max"]]]
        stats["relations_truncated_count"] += len(relations) - len(kept)
        data["relations"] = kept
    claims = data.get("claims", [])
    if isinstance(claims, list) and len(claims) > limits["claims_max"]:
        scored = [(c, _score_claim(c)) for c in claims if isinstance(c, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [c for c, _ in scored[:limits["claims_max"]]]
        stats["claims_truncated_count"] += len(claims) - len(kept)
        data["claims"] = kept
    topics = data.get("topics", [])
    if isinstance(topics, list) and len(topics) > limits["topics_max"]:
        stats["topics_truncated_count"] += len(topics) - limits["topics_max"]
        data["topics"] = topics[:limits["topics_max"]]
    keywords = data.get("keywords", [])
    if isinstance(keywords, list) and len(keywords) > limits["keywords_max"]:
        stats["keywords_truncated_count"] += len(keywords) - limits["keywords_max"]
        data["keywords"] = keywords[:limits["keywords_max"]]
    ocr_evidence = data.get("ocr_evidence", [])
    if isinstance(ocr_evidence, list) and len(ocr_evidence) > limits["ocr_evidence_max"]:
        stats["long_text_truncated_count"] += len(ocr_evidence) - limits["ocr_evidence_max"]
        data["ocr_evidence"] = ocr_evidence[:limits["ocr_evidence_max"]]
    kept_entities = []
    for entity in data.get("entities", []):
        if not isinstance(entity, dict):
            kept_entities.append(entity)
            continue
        aliases = entity.get("aliases", [])
        if isinstance(aliases, list) and len(aliases) > limits["aliases_per_entity_max"]:
            stats["aliases_truncated_count"] += len(aliases) - limits["aliases_per_entity_max"]
            entity["aliases"] = aliases[:limits["aliases_per_entity_max"]]
        bio = entity.get("bio", "")
        sanitized_bio, bio_flags = _sanitize_bio(bio, source_text, limits["bio_max_chars"], stats)
        entity["bio"] = sanitized_bio
        if bio_flags:
            qf = entity.get("quality_flags", [])
            if isinstance(qf, list):
                qf.extend(bio_flags)
                entity["quality_flags"] = qf
        if not sanitized_bio and bio:
            stats["bio_cleared_count"] += 1
        evidence = entity.get("evidence", [])
        if isinstance(evidence, list):
            entity["evidence"] = _limit_evidence(evidence, limits["evidence_per_item_max"], limits["evidence_text_max_chars"], stats, source_text)
        if _keep_item_with_evidence(entity, stats):
            kept_entities.append(entity)
    data["entities"] = kept_entities
    kept_events = []
    for event in data.get("events", []):
        if not isinstance(event, dict):
            kept_events.append(event)
            continue
        desc = event.get("description", "")
        truncated_desc, was_truncated = _truncate_text(desc, limits["event_description_max_chars"])
        if was_truncated:
            stats["long_text_truncated_count"] += 1
            event["description"] = truncated_desc
            event["generated_summary"] = True
        evidence = event.get("evidence", [])
        if isinstance(evidence, list):
            event["evidence"] = _limit_evidence(evidence, limits["evidence_per_item_max"], limits["evidence_text_max_chars"], stats, source_text)
        if _keep_item_with_evidence(event, stats):
            kept_events.append(event)
    data["events"] = kept_events
    kept_relations = []
    for relation in data.get("relations", []):
        if not isinstance(relation, dict):
            kept_relations.append(relation)
            continue
        evidence = relation.get("evidence", [])
        if isinstance(evidence, list):
            relation["evidence"] = _limit_evidence(evidence, limits["evidence_per_item_max"], limits["evidence_text_max_chars"], stats, source_text)
        if _keep_item_with_evidence(relation, stats):
            kept_relations.append(relation)
    data["relations"] = kept_relations
    kept_claims = []
    for claim in data.get("claims", []):
        if not isinstance(claim, dict):
            kept_claims.append(claim)
            continue
        text = claim.get("claim_text", "")
        truncated_text, was_truncated = _truncate_text(text, limits["claim_text_max_chars"])
        if was_truncated:
            stats["long_text_truncated_count"] += 1
            claim["claim_text"] = truncated_text
        evidence = claim.get("evidence", [])
        if isinstance(evidence, list):
            claim["evidence"] = _limit_evidence(evidence, limits["evidence_per_item_max"], limits["evidence_text_max_chars"], stats, source_text)
        if _keep_item_with_evidence(claim, stats):
            kept_claims.append(claim)
    data["claims"] = kept_claims
    summary = data.get("summary", "")
    truncated_summary, was_truncated = _truncate_text(summary, limits["summary_max_chars"])
    if was_truncated:
        stats["long_text_truncated_count"] += 1
        data["summary"] = truncated_summary
    for ocr in data.get("ocr_evidence", []):
        if not isinstance(ocr, dict):
            continue
        text = ocr.get("ocr_text", "")
        truncated_text, was_truncated = _truncate_text(text, limits["ocr_text_max_chars"])
        if was_truncated:
            stats["long_text_truncated_count"] += 1
            ocr["ocr_text"] = truncated_text
    return data, stats


def _normalize_entity_key(name: str, etype: str) -> str:
    """Create dedup key: normalized name + type."""
    normalized = name.strip().lower()
    return f"{normalized}||{etype}"


def sanitize_article_level(
    result: dict,
    source_text: str | None = None,
    limits: dict | None = None,
) -> tuple[dict, dict]:
    """Article-level sanitize: dedupe and limit after aggregation."""
    if limits is None:
        limits = ARTICLE_LIMITS
    stats = {
        "entities_deduped_count": 0,
        "article_entities_truncated_count": 0,
        "article_events_truncated_count": 0,
        "article_relations_truncated_count": 0,
        "article_claims_truncated_count": 0,
        "article_topics_truncated_count": 0,
    }
    result = dict(result)
    entities = result.get("entities", [])
    if isinstance(entities, list):
        seen: dict[str, dict] = {}
        deduped = 0
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            name = entity.get("name", "")
            etype = entity.get("type", "unknown")
            key = _normalize_entity_key(name, etype)
            if key in seen:
                existing = seen[key]
                existing_ev = existing.get("evidence", [])
                new_ev = entity.get("evidence", [])
                if isinstance(existing_ev, list) and isinstance(new_ev, list):
                    combined = existing_ev + new_ev
                    existing["evidence"] = combined[:3]
                existing_aliases = existing.get("aliases", [])
                new_aliases = entity.get("aliases", [])
                if isinstance(existing_aliases, list) and isinstance(new_aliases, list):
                    combined_aliases = list(dict.fromkeys(existing_aliases + new_aliases))
                    existing["aliases"] = combined_aliases[:8]
                if not existing.get("bio") and entity.get("bio"):
                    existing["bio"] = entity["bio"]
                elif entity.get("bio") and source_text and substring_match_kind(entity["bio"], source_text, ""):
                    existing["bio"] = entity["bio"]
                existing_conf = existing.get("confidence", 0)
                new_conf = entity.get("confidence", 0)
                try:
                    existing["confidence"] = max(float(existing_conf or 0), float(new_conf or 0))
                except (ValueError, TypeError):
                    pass
                existing_qf = existing.get("quality_flags", [])
                new_qf = entity.get("quality_flags", [])
                if isinstance(existing_qf, list) and isinstance(new_qf, list):
                    existing["quality_flags"] = list(dict.fromkeys(existing_qf + new_qf))
                deduped += 1
            else:
                seen[key] = entity
        stats["entities_deduped_count"] = deduped
        unique_entities = list(seen.values())
        if len(unique_entities) > limits["entities_max"]:
            scored = [(e, _score_entity(e, source_text)) for e in unique_entities if isinstance(e, dict)]
            scored.sort(key=lambda x: x[1], reverse=True)
            kept = [e for e, _ in scored[:limits["entities_max"]]]
            stats["article_entities_truncated_count"] += len(unique_entities) - len(kept)
            result["entities"] = kept
        else:
            result["entities"] = unique_entities
    events = result.get("events", [])
    if isinstance(events, list) and len(events) > limits["events_max"]:
        scored = [(e, _score_event(e)) for e in events if isinstance(e, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [e for e, _ in scored[:limits["events_max"]]]
        stats["article_events_truncated_count"] += len(events) - len(kept)
        result["events"] = kept
    relations = result.get("relations", [])
    if isinstance(relations, list) and len(relations) > limits["relations_max"]:
        scored = [(r, _score_relation(r)) for r in relations if isinstance(r, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [r for r, _ in scored[:limits["relations_max"]]]
        stats["article_relations_truncated_count"] += len(relations) - len(kept)
        result["relations"] = kept
    claims = result.get("claims", [])
    if isinstance(claims, list) and len(claims) > limits["claims_max"]:
        scored = [(c, _score_claim(c)) for c in claims if isinstance(c, dict)]
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = [c for c, _ in scored[:limits["claims_max"]]]
        stats["article_claims_truncated_count"] += len(claims) - len(kept)
        result["claims"] = kept
    topics = result.get("topics", [])
    if isinstance(topics, list) and len(topics) > limits["topics_max"]:
        stats["article_topics_truncated_count"] += len(topics) - limits["topics_max"]
        result["topics"] = topics[:limits["topics_max"]]
    return result, stats
