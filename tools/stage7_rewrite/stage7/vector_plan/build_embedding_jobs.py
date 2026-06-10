"""Build embedding jobs from Stage 7 extract output."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from .schemas import VectorJob, VectorManifest
from .enrichment import card_payload, clean_account, evidence_text, infer_city, infer_venue

logger = logging.getLogger(__name__)

MAX_CANONICAL_CHARS = 2000


def truncate(text: str, max_chars: int = MAX_CANONICAL_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def canonical_text_entity(obj: dict, article: dict) -> str:
    name = obj.get("name", "")
    etype = obj.get("type", "")
    aliases = " ".join(obj.get("aliases", []))
    bio = obj.get("description", "")
    evidence = " ".join(e.get("quote", "") for e in obj.get("evidence", []))
    title = article.get("title", "")
    account = article.get("source_account", "")
    return truncate(_join(name, etype, aliases, bio, evidence, title, account))


def canonical_text_event(obj: dict, article: dict) -> str:
    name = obj.get("name", "")
    time = obj.get("time", "")
    place = obj.get("place", "")
    participants = " ".join(obj.get("participants", []))
    desc = obj.get("description", "")
    evidence = " ".join(e.get("quote", "") for e in obj.get("evidence", []))
    title = article.get("title", "")
    return truncate(_join(name, time, place, participants, desc, evidence, title))


def canonical_text_relation(obj: dict, article: dict) -> str:
    subject = obj.get("subject", "")
    predicate = obj.get("predicate", "")
    object_ = obj.get("object", "")
    evidence = " ".join(e.get("quote", "") for e in obj.get("evidence", []))
    title = article.get("title", "")
    return truncate(_join(subject, predicate, object_, evidence, title))


def canonical_text_claim(obj: dict, article: dict) -> str:
    claim_text = obj.get("claim", "")
    source_kind = obj.get("claim_type", "")
    title = article.get("title", "")
    return truncate(_join(claim_text, source_kind, title))


def canonical_text_article(article: dict) -> str:
    title = article.get("title", "")
    account = article.get("source_account", "")
    pub_time = article.get("publish_time", "")
    topics = " ".join(article.get("topics", []))
    summary = article.get("summary", "")
    top_entities = " ".join(
        e.get("name", "") for e in article.get("entities", [])[:5]
    )
    return truncate(_join(title, account, pub_time, topics, summary, top_entities))


def canonical_text_ocr_evidence(obj: dict, article: dict) -> str:
    image_id = obj.get("image_id", "")
    ocr_text = obj.get("ocr_text", "")
    nearby = obj.get("nearby_text", "")
    extracted = " ".join(str(v) for v in obj.get("extracted_items", {}).values())
    title = article.get("title", "")
    return truncate(_join(image_id, ocr_text, nearby, extracted, title))


def _labeled_lines(fields: list[tuple[str, Any]]) -> str:
    lines = []
    for label, value in fields:
        if isinstance(value, list):
            value = "；".join(str(v) for v in value if v)
        if value is None:
            value = ""
        value = str(value).strip()
        if value:
            lines.append(f"{label}: {value}")
    return truncate("\n".join(lines))


def source_lane(article: dict) -> str:
    account = str(article.get("source_account", ""))
    return account.split("__", 1)[0] if "__" in account else ""


def labeled_text_entity(obj: dict, article: dict, card_kind: str = "entity_identity_card") -> str:
    return _labeled_lines(
        [
            ("对象", card_kind),
            ("名称", obj.get("name", "")),
            ("类型", obj.get("type", "")),
            ("别名", obj.get("aliases", [])),
            ("城市", infer_city(article, obj)),
            ("场地", infer_venue(article, obj)),
            ("来源公众号", clean_account(article.get("source_account", ""))),
            ("文章标题", article.get("title", "")),
            ("发布时间", article.get("publish_time", "")),
            ("描述", obj.get("description", "") or obj.get("bio", "")),
            ("证据", evidence_text(obj)),
        ]
    )


def labeled_text_entity_mention(obj: dict, article: dict) -> str:
    return _labeled_lines(
        [
            ("对象", "entity_mention_card"),
            ("实体", obj.get("name", "")),
            ("类型", obj.get("type", "")),
            ("出现文章", article.get("title", "")),
            ("来源公众号", clean_account(article.get("source_account", ""))),
            ("城市", infer_city(article, obj)),
            ("上下文证据", evidence_text(obj)),
        ]
    )


def labeled_text_event(obj: dict, article: dict) -> str:
    return _labeled_lines(
        [
            ("对象", "event_card"),
            ("活动", obj.get("name", "")),
            ("类型", obj.get("type", "")),
            ("时间原文", obj.get("time", "")),
            ("城市", infer_city(article, obj)),
            ("场地", obj.get("place", "") or infer_venue(article, obj)),
            ("主办/账号", clean_account(article.get("source_account", ""))),
            ("阵容", obj.get("participants", [])),
            ("描述", obj.get("description", "")),
            ("文章标题", article.get("title", "")),
            ("证据", evidence_text(obj)),
        ]
    )


def labeled_text_relation(obj: dict, article: dict) -> str:
    return _labeled_lines(
        [
            ("对象", "relation_card"),
            ("主体", obj.get("subject", "")),
            ("关系", obj.get("predicate", "")),
            ("客体", obj.get("object", "")),
            ("城市", infer_city(article, obj)),
            ("场地", infer_venue(article, obj)),
            ("文章标题", article.get("title", "")),
            ("证据", evidence_text(obj)),
        ]
    )


def labeled_text_article(article: dict) -> str:
    top_entities = [e.get("name", "") for e in article.get("entities", [])[:8]]
    top_events = [e.get("name", "") for e in article.get("events", [])[:5]]
    return _labeled_lines(
        [
            ("对象", "article_card"),
            ("标题", article.get("title", "")),
            ("来源公众号", clean_account(article.get("source_account", ""))),
            ("发布时间", article.get("publish_time", "")),
            ("城市", infer_city(article)),
            ("主题", article.get("topics", [])),
            ("摘要", article.get("summary", "")),
            ("Top实体", top_entities),
            ("Top活动", top_events),
        ]
    )


def labeled_text_account_profile(article: dict) -> str:
    top_entities = [e.get("name", "") for e in article.get("entities", [])[:10]]
    top_events = [e.get("name", "") for e in article.get("events", [])[:8]]
    return _labeled_lines(
        [
            ("对象", "account_profile_card"),
            ("公众号", clean_account(article.get("source_account", ""))),
            ("来源分层", source_lane(article)),
            ("城市", infer_city(article)),
            ("代表场地", infer_venue(article)),
            ("近期标题", article.get("title", "")),
            ("发布时间", article.get("publish_time", "")),
            ("主题", article.get("topics", [])),
            ("代表实体", top_entities),
            ("代表活动", top_events),
            ("摘要", article.get("summary", "")),
        ]
    )


def labeled_text_ocr_evidence(obj: dict, article: dict) -> str:
    return _labeled_lines(
        [
            ("对象", "ocr_evidence_card"),
            ("图片ID", obj.get("image_id", "")),
            ("OCR文本", obj.get("ocr_text", "")),
            ("附近正文", obj.get("nearby_text", "")),
            ("城市", infer_city(article, obj)),
            ("文章标题", article.get("title", "")),
        ]
    )


def _ocr_text_from_blocks(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return ""
    texts: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            text = block
        elif isinstance(block, dict):
            text = (
                block.get("text")
                or block.get("ocr_text")
                or block.get("content")
                or ""
            )
        else:
            text = ""
        text = str(text).strip()
        if text:
            texts.append(text)
    return " ".join(texts)


def _ocr_image_id(value: dict, key: str, index: int) -> str:
    for field in ("image_id", "id", "url", "image_path", "path", "src"):
        raw = value.get(field)
        if not raw:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if field in {"url", "image_path", "path", "src"}:
            tail = text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            return tail or text
        return text
    return f"{key}:{index}"


def _normalize_ocr_item(value: Any, key: str, index: int) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = value.strip()
        return {"image_id": f"{key}:{index}", "ocr_text": text} if text else None
    if not isinstance(value, dict):
        return None
    text = (
        value.get("ocr_text")
        or value.get("text")
        or value.get("content")
        or value.get("poster_ocr")
        or value.get("plain_text")
        or value.get("caption")
        or _ocr_text_from_blocks(value.get("blocks"))
        or ""
    )
    text = str(text).strip()
    if not text:
        return None
    return {
        "image_id": _ocr_image_id(value, key, index),
        "ocr_text": text,
        "nearby_text": value.get("nearby_text") or value.get("caption") or "",
        "confidence": value.get("confidence"),
    }


def iter_ocr_evidence(article: dict) -> list[dict[str, Any]]:
    """Return normalized OCR evidence cards from common Stage7 article shapes."""
    items: list[dict[str, Any]] = []
    for key in ("ocr_evidence", "ocr", "image_ocr", "images", "image_cards", "media", "poster_ocr"):
        value = article.get(key)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        for idx, item in enumerate(values, 1):
            normalized = _normalize_ocr_item(item, key, idx)
            if normalized:
                items.append(normalized)
    return items


CANONICAL_BUILDERS: dict[str, Any] = {
    "entity": canonical_text_entity,
    "event": canonical_text_event,
    "relation": canonical_text_relation,
    "claim": canonical_text_claim,
    "article": canonical_text_article,
    "ocr_evidence": canonical_text_ocr_evidence,
}

EVENT_LIKE_ENTITY_TYPES = {"event", "activity", "party", "show", "festival", "concert", "gig", "活动", "派对", "演出"}


def _is_event_like_entity(obj: dict) -> bool:
    etype = str(obj.get("type", "")).strip().lower()
    name = str(obj.get("name", "")).lower()
    return etype in EVENT_LIKE_ENTITY_TYPES or any(cue in name for cue in ("派对", "活动", "festival", "party"))


def _object_id(kind: str, article: dict, obj: dict) -> str:
    if kind == "entity":
        return obj.get("entity_id", "")
    if kind == "event":
        return obj.get("event_id", "")
    if kind == "relation":
        parts = [obj.get("subject", ""), obj.get("predicate", ""), obj.get("object", "")]
        return ":".join(parts)
    if kind == "claim":
        return obj.get("claim", "")[:64]
    if kind == "article":
        return article.get("article_uid", "")
    if kind == "ocr_evidence":
        return obj.get("image_id", "")
    return ""


def _collection_name(object_kind: str, model: str, dim: int) -> str:
    safe_model = model.replace("/", "_").replace(".", "_")
    return f"wechat_{object_kind}_{safe_model}_{dim}"


def build_jobs_from_article(
    article_data: dict,
    source_path: str,
    model: str,
    endpoint: str,
    dim: int,
    route_metadata: dict[str, Any] | None = None,
    card_template: str = "baseline",
) -> list[VectorJob]:
    """Build VectorJob list from one extract.article.v1.json."""
    jobs: list[VectorJob] = []
    article_id = article_data.get("article_id", "")
    account = article_data.get("source_account", "")
    route_metadata = route_metadata or {}

    kinds = [
        ("entity", article_data.get("entities", [])),
        ("event", article_data.get("events", [])),
        ("relation", article_data.get("relations", [])),
        ("claim", article_data.get("claims", [])),
    ]

    for kind, objects in kinds:
        builder = CANONICAL_BUILDERS.get(kind)
        if not builder:
            continue
        for obj in objects:
            obj_id = _object_id(kind, article_data, obj)
            if not obj_id:
                continue
            if card_template == "baseline":
                card_defs = [(kind, kind, builder(obj, article_data), obj_id)]
            elif card_template == "labeled_v2":
                if kind == "entity":
                    card_defs = [("entity", "entity_identity_card", labeled_text_entity(obj, article_data), obj_id)]
                elif kind == "event":
                    card_defs = [("event", "event_card", labeled_text_event(obj, article_data), obj_id)]
                elif kind == "relation":
                    card_defs = [("relation", "relation_card", labeled_text_relation(obj, article_data), obj_id)]
                else:
                    card_defs = [(kind, kind, builder(obj, article_data), obj_id)]
            elif card_template in {"multi_card", "research_v1"}:
                if kind == "entity":
                    card_defs = [
                        ("entity_identity", "entity_identity_card", labeled_text_entity(obj, article_data), obj_id),
                        ("entity_mention", "entity_mention_card", labeled_text_entity_mention(obj, article_data), obj_id),
                    ]
                    if _is_event_like_entity(obj):
                        card_defs.append(("event", "event_card", labeled_text_event(obj, article_data), f"entity:{obj_id}"))
                elif kind == "event":
                    card_defs = [("event", "event_card", labeled_text_event(obj, article_data), obj_id)]
                elif kind == "relation":
                    card_defs = [("relation", "relation_card", labeled_text_relation(obj, article_data), obj_id)]
                else:
                    card_defs = [(kind, kind, builder(obj, article_data), obj_id)]
            else:
                raise ValueError(f"unknown card_template={card_template}")

            for job_kind, card_kind, ctext, output_obj_id in card_defs:
                if not ctext.strip():
                    continue
                collection = _collection_name(job_kind, model, dim)
                if card_template == "baseline":
                    metadata = {
                        **route_metadata,
                        "account": account,
                        "article_title": article_data.get("title", ""),
                        "confidence": obj.get("confidence"),
                    }
                else:
                    payload_kind = "entity" if job_kind in {"entity_identity", "entity_mention"} else job_kind
                    metadata = card_payload(article_data, obj, payload_kind, card_kind, route_metadata)
                    metadata["template"] = card_template
                job = VectorJob(
                    job_id=f"{account}:{article_id}:{job_kind}:{output_obj_id}",
                    object_kind=job_kind,
                    object_id=output_obj_id,
                    article_id=article_id,
                    source_path=source_path,
                    model=model,
                    endpoint=endpoint,
                    dim=dim,
                    collection=collection,
                    canonical_text=ctext,
                    metadata=metadata,
                )
                jobs.append(job)

    # Article-level job
    ctext = (
        labeled_text_article(article_data)
        if card_template in {"labeled_v2", "multi_card", "research_v1"}
        else canonical_text_article(article_data)
    )
    if ctext.strip():
        collection = _collection_name("article", model, dim)
        if card_template == "baseline":
            metadata = {
                **route_metadata,
                "account": account,
                "article_title": article_data.get("title", ""),
            }
        else:
            metadata = card_payload(article_data, None, "article", "article_card", route_metadata)
            metadata["template"] = card_template
        jobs.append(VectorJob(
            job_id=f"{account}:{article_id}:article:{article_id}",
            object_kind="article",
            object_id=article_id,
            article_id=article_id,
            source_path=source_path,
            model=model,
            endpoint=endpoint,
            dim=dim,
            collection=collection,
            canonical_text=ctext,
            metadata=metadata,
        ))

    if card_template == "research_v1":
        ctext = labeled_text_account_profile(article_data)
        if ctext.strip():
            metadata = card_payload(article_data, None, "account_profile", "account_profile_card", route_metadata)
            metadata["template"] = card_template
            metadata["profile_level"] = "article_account"
            jobs.append(VectorJob(
                job_id=f"{account}:{article_id}:account_profile:{article_id}",
                object_kind="account_profile",
                object_id=article_id,
                article_id=article_id,
                source_path=source_path,
                model=model,
                endpoint=endpoint,
                dim=dim,
                collection=_collection_name("account_profile", model, dim),
                canonical_text=ctext,
                metadata=metadata,
            ))

        for idx, ocr in enumerate(iter_ocr_evidence(article_data), 1):
            ctext = labeled_text_ocr_evidence(ocr, article_data)
            if not ctext.strip():
                continue
            object_id = str(ocr.get("image_id") or f"ocr:{idx}")
            metadata = card_payload(article_data, ocr, "ocr_evidence", "ocr_evidence_card", route_metadata)
            metadata["template"] = card_template
            metadata["evidence_source"] = "ocr"
            metadata["evidence_ref"] = str(ocr.get("ocr_text", "")).strip()
            metadata["image_id"] = object_id
            jobs.append(VectorJob(
                job_id=f"{account}:{article_id}:ocr_evidence:{object_id}",
                object_kind="ocr_evidence",
                object_id=object_id,
                article_id=article_id,
                source_path=source_path,
                model=model,
                endpoint=endpoint,
                dim=dim,
                collection=_collection_name("ocr_evidence", model, dim),
                canonical_text=ctext,
                metadata=metadata,
            ))

    return jobs
