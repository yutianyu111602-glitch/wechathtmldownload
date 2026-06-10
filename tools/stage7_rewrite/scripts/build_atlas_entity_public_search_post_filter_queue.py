#!/usr/bin/env python3
"""Build a strict post-filter queue from Atlas entity public search telemetry.

This is intentionally report-only. It reads the raw public search review and
evidence JSONL files, writes derived review/quarantine/discovery queues, and
never writes accepted graph edges or production state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = STAGE7_ROOT / "reports" / "atlas_entity_public_search_138102_20260521"
DEFAULT_REVIEW_JSONL = DEFAULT_RAW_DIR / "entity_public_search_review.jsonl"
DEFAULT_EVIDENCE_JSONL = DEFAULT_RAW_DIR / "entity_public_search_evidence.jsonl"
DEFAULT_RULES = STAGE7_ROOT / "config" / "atlas_entity_public_search_post_filter_rules.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_entity_public_search_post_filter_138102_20260521"
SCHEMA_VERSION = "stage7_atlas_entity_public_search_post_filter.v1"

SENSITIVE_QUERY_KEYS = {"authkey", "key", "pass_ticket", "poc_token", "signature", "sig", "token", "code"}
CANDIDATE_STATUSES = {
    "candidate_entity_context_needs_human_review",
    "candidate_weak_entity_context_needs_human_review",
}


DEFAULT_RULES_PAYLOAD: dict[str, Any] = {
    "schema_version": "stage7_atlas_entity_public_search_post_filter.rules.v1",
    "thresholds": {"filtered_candidate": 35, "review_queue": 45},
    "identity_types": [
        "artist",
        "band",
        "brand",
        "event",
        "group",
        "label",
        "organization",
        "organisation",
        "organizer",
        "organiation",
        "organizations",
        "organiztion",
        "organzation",
        "organziation",
        "person",
        "project",
        "venue",
        "work",
    ],
    "discovery_types": ["concept", "location", "place", "platform", "product", "program", "series", "unknown"],
    "generic_stoplist": [
        "all",
        "axis",
        "cisco",
        "dada",
        "disco",
        "exit",
        "gas",
        "hao",
        "house",
        "hum",
        "oil",
        "tag",
        "techno",
        "watermelon",
        "nasa",
    ],
    "platform_stoplist": [
        "bandcamp",
        "mixcloud",
        "soundcloud",
        "spotify",
        "网易云",
        "网易云音乐",
    ],
    "music_genre_lexicon": [
        "acid",
        "ambient",
        "bass",
        "breakbeat",
        "club",
        "disco",
        "downtempo",
        "drumandbass",
        "dub",
        "electro",
        "electronica",
        "hardcore",
        "house",
        "idm",
        "jungle",
        "minimal",
        "rave",
        "techno",
        "trance",
    ],
    "music_context_terms": [
        "artist",
        "bandcamp",
        "beatport",
        "club",
        "collective",
        "dance music",
        "dj",
        "electronic music",
        "festival",
        "label",
        "lineup",
        "live music",
        "mix",
        "music",
        "nightclub",
        "party",
        "producer",
        "ra",
        "rave",
        "resident advisor",
        "soundcloud",
        "techno",
        "venue",
        "电子",
        "电子音乐",
        "俱乐部",
        "厂牌",
        "唱片",
        "夜店",
        "派对",
        "演出",
        "现场",
        "音乐",
        "音乐人",
        "音乐节",
        "驻场",
    ],
    "strong_music_context_terms": [
        "artist profile",
        "bandcamp",
        "beatport",
        "club",
        "dj",
        "electronic music",
        "label",
        "lineup",
        "mixcloud",
        "nightclub",
        "producer",
        "resident advisor",
        "soundcloud",
        "techno",
        "venue",
        "电子音乐",
        "俱乐部",
        "厂牌",
        "夜店",
        "派对",
        "音乐人",
        "驻场",
    ],
    "negative_subject_terms": [
        "ai infrastructure",
        "art movement",
        "calories",
        "clinic",
        "definition",
        "definition & history",
        "dictionary",
        "for sale",
        "free game",
        "gas tariffs",
        "health",
        "history & facts",
        "house for sale",
        "ikea",
        "infrastructure",
        "medical",
        "mortgage",
        "networking",
        "nutrition",
        "play online",
        "property",
        "real estate",
        "rheumatoid arthritis",
        "roblox",
        "software solutions",
        "tuition",
    ],
    "deny_domains": [
        "amazon.co.jp",
        "autodesk.com",
        "cambridge.org",
        "chiebukuro.yahoo.co.jp",
        "cityenergy.com.sg",
        "clevelandclinic.org",
        "collinsdictionary.com",
        "cisco.com",
        "dictionary.com",
        "dictionary.cambridge.org",
        "finance.yahoo.com",
        "google.co.in",
        "ikea.com",
        "mayoclinic.org",
        "merriam-webster.com",
        "mom.gov.sg",
        "pexels.com",
        "poki.com",
        "propertyguru.com.sg",
        "roblox.com",
        "sbstransit.com.sg",
        "support.google.com",
        "support.microsoft.com",
        "taggame.io",
        "theartstory.org",
        "verywellhealth.com",
        "web.whatsapp.com",
    ],
    "deny_path_patterns": ["britannica.com/art/", "/dictionary/", "/search/car", "/property-for-sale"],
    "domain_tiers": {
        "T1_music_direct": [
            "bandcamp.com",
            "beatport.com",
            "boogie.sg",
            "discogs.com",
            "djmag.com",
            "mixcloud.com",
            "music.163.com",
            "musicbrainz.org",
            "ra.co",
            "residentadvisor.net",
            "songkick.com",
            "soundcloud.com",
            "y.qq.com",
        ],
        "T2_social_profile": [
            "bilibili.com",
            "douban.com",
            "facebook.com",
            "instagram.com",
            "linktr.ee",
            "twitter.com",
            "weibo.com",
            "xiaohongshu.com",
            "x.com",
            "youtube.com",
        ],
        "T3_china_music_media": [
            "dada-bar.com",
            "dada.org.cn",
            "neocha.com",
            "timeout.com",
            "thebeijinger.com",
            "thatsmags.com",
        ],
        "T4_reference": ["baike.baidu.com", "britannica.com", "en.wikipedia.org", "en.wiktionary.org", "zh.wikipedia.org", "wikipedia.org"],
        "T5_generic_video": ["youtube.com", "youtu.be"],
    },
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 240).casefold())


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for atlas public-search post-filter: {path}")


def sanitize_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 1000))
    if not parsed.scheme or not parsed.netloc:
        return compact(url, 1000)
    safe_query = [
        (key, value)
        for key, value in parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in SENSITIVE_QUERY_KEYS
    ]
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(safe_query), ""))


def domain_from_url(url: str) -> str:
    host = (parse.urlsplit(compact(url, 1000)).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def host_matches(host: str, rule_domain: str) -> bool:
    host = host.casefold()
    rule = rule_domain.casefold()
    return host == rule or host.endswith("." + rule)


def contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def ascii_word_match(needle: str, haystack: str) -> bool:
    needle = compact(needle).casefold()
    if not needle:
        return False
    if contains_cjk(needle):
        return normalize(needle) in normalize(haystack)
    normalized = normalize(needle)
    if not normalized:
        return False
    if len(normalized) <= 4:
        pattern = r"(?<![0-9a-z])" + re.escape(needle) + r"(?![0-9a-z])"
        return bool(re.search(pattern, haystack.casefold()))
    return normalized in normalize(haystack)


def term_match(term: str, haystack: str) -> bool:
    term = compact(term).casefold()
    if not term:
        return False
    if contains_cjk(term):
        return term in haystack.casefold()
    if " " in term:
        return term in haystack.casefold()
    return ascii_word_match(term, haystack)


def file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def load_rules(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return json.loads(json.dumps(DEFAULT_RULES_PAYLOAD))
    reject_d_path(path, "rules")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"rules must be a JSON object: {path}")
    merged = json.loads(json.dumps(DEFAULT_RULES_PAYLOAD))
    for key, value in loaded.items():
        merged[key] = value
    return merged


def read_jsonl(path: Path):
    reject_d_path(path, "jsonl")
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                value = json.loads(stripped)
                if isinstance(value, dict):
                    yield value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


class JsonlTempWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
        self._tmp = Path(self._handle.name)
        self.count = 0

    def write(self, row: dict[str, Any]) -> None:
        self._handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        self._handle.write("\n")
        self.count += 1

    def close(self) -> None:
        self._handle.close()
        self._tmp.replace(self.path)

    def abort(self) -> None:
        self._handle.close()
        try:
            self._tmp.unlink()
        except FileNotFoundError:
            pass


def rules_hash(rules: dict[str, Any]) -> str:
    payload = json.dumps(rules, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def domain_tier(domain: str, rules: dict[str, Any]) -> tuple[str, int]:
    tier_scores = {
        "T1_music_direct": 25,
        "T2_social_profile": 15,
        "T3_china_music_media": 12,
        "T4_reference": 0,
        "T5_generic_video": 3,
    }
    for tier, domains in (rules.get("domain_tiers") or {}).items():
        for rule_domain in domains or []:
            if host_matches(domain, str(rule_domain)):
                return tier, tier_scores.get(tier, 0)
    return "untrusted", 0


def deny_reason(url: str, rules: dict[str, Any]) -> str:
    domain = domain_from_url(url)
    for rule_domain in rules.get("deny_domains") or []:
        if host_matches(domain, str(rule_domain)):
            return f"deny_domain:{rule_domain}"
    lowered = sanitize_url(url).casefold()
    for pattern in rules.get("deny_path_patterns") or []:
        if str(pattern).casefold() in lowered:
            return f"deny_path:{pattern}"
    return ""


def is_generic_name(name: str, entity_type: str, rules: dict[str, Any]) -> tuple[bool, list[str]]:
    norm = normalize(name)
    hits: list[str] = []
    if norm in {normalize(item) for item in rules.get("generic_stoplist") or []}:
        hits.append("generic_stoplist")
    if norm in {normalize(item) for item in rules.get("platform_stoplist") or []}:
        hits.append("platform_stoplist")
    if norm in {normalize(item) for item in rules.get("music_genre_lexicon") or []}:
        hits.append("music_genre_lexicon")
    if entity_type == "concept":
        hits.append("concept_type")
    if norm and not contains_cjk(name) and len(norm) <= 3:
        hits.append("short_latin_name")
    return bool(hits), hits


def evidence_to_search_row(review: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
    if evidence:
        return evidence
    top = review.get("top_result") if isinstance(review.get("top_result"), dict) else {}
    return {
        "entity_search_id": review.get("entity_search_id"),
        "queue_index": review.get("queue_index"),
        "name": review.get("name"),
        "type": review.get("type"),
        "score": top.get("score", 0),
        "decision": top.get("decision", ""),
        "title": top.get("title", ""),
        "url": top.get("url", ""),
        "content": top.get("content", ""),
        "rank": top.get("rank"),
    }


def score_evidence(review: dict[str, Any], evidence: dict[str, Any] | None, rules: dict[str, Any]) -> dict[str, Any]:
    candidate = evidence_to_search_row(review, evidence)
    name = compact(review.get("name"), 160)
    entity_type = compact(review.get("type"), 80).casefold()
    aliases = review.get("aliases") if isinstance(review.get("aliases"), list) else []
    title = compact(candidate.get("title"), 240)
    content = compact(candidate.get("content"), 500)
    url = sanitize_url(str(candidate.get("url") or ""))
    domain = domain_from_url(url)
    haystack = " ".join([title, content, url])
    title_url_haystack = " ".join([title, url])
    raw_search_score = int(candidate.get("score") or 0)
    score = 0
    hits: list[str] = []
    penalties: list[str] = []

    tier, tier_score = domain_tier(domain, rules)
    if tier_score:
        score += tier_score
        hits.append(f"domain_tier:{tier}")

    if ascii_word_match(name, haystack):
        score += 12
        hits.append("name_match")
    else:
        penalties.append("missing_subject_name")

    if ascii_word_match(name, title):
        score += 5
        hits.append("name_in_title")

    matched_aliases = [
        compact(alias, 120)
        for alias in aliases
        if normalize(alias) != normalize(name) and ascii_word_match(str(alias), haystack)
    ]
    if matched_aliases:
        score += min(15, len(matched_aliases) * 10)
        hits.append("alias_match")

    music_terms = [term for term in rules.get("music_context_terms") or [] if term_match(str(term), haystack)]
    if music_terms:
        score += min(8, 2 + len(music_terms))
        hits.append("music_context")

    strong_music_terms = [term for term in rules.get("strong_music_context_terms") or [] if term_match(str(term), haystack)]
    strong_title_terms = [
        term for term in rules.get("strong_music_context_terms") or [] if term_match(str(term), title_url_haystack)
    ]
    if strong_music_terms:
        score += min(14, 6 + len(strong_music_terms) * 2)
        hits.append("strong_music_context")
    if strong_title_terms:
        hits.append("strong_title_context")

    type_terms = {
        "person": ["dj", "artist", "producer"],
        "artist": ["dj", "artist", "producer"],
        "organization": ["club", "label", "collective", "venue", "俱乐部", "厂牌"],
        "organisation": ["club", "label", "collective", "venue", "俱乐部", "厂牌"],
        "event": ["lineup", "festival", "party", "event", "演出", "派对", "音乐节"],
        "work": ["release", "mix", "track", "album"],
        "venue": ["venue", "club", "nightclub", "地址", "俱乐部"],
        "label": ["label", "厂牌"],
    }.get(entity_type, [])
    matched_type_terms = [term for term in type_terms if term_match(term, haystack)]
    matched_type_title_terms = [term for term in type_terms if term_match(term, title_url_haystack)]
    if matched_type_terms:
        score += 5
        hits.append("type_hint_match")

    negative_terms = [term for term in rules.get("negative_subject_terms") or [] if term_match(str(term), haystack)]
    if negative_terms:
        score -= min(30, 10 + len(negative_terms) * 5)
        penalties.append("negative_subject_terms")

    deny = deny_reason(url, rules)
    if deny:
        penalties.append(deny)

    generic, generic_hits = is_generic_name(name, entity_type, rules)
    if generic:
        penalties.extend(generic_hits)
        if not (matched_aliases or tier in {"T1_music_direct", "T2_social_profile"}):
            score -= 12

    score += min(4, raw_search_score // 3)
    return {
        "name": name,
        "type": entity_type,
        "title": title,
        "url": url,
        "domain": domain,
        "raw_search_score": raw_search_score,
        "post_filter_score": score,
        "rule_hits": hits,
        "rule_penalties": penalties,
        "domain_tier": tier,
        "matched_aliases": matched_aliases,
        "matched_music_terms": music_terms[:12],
        "matched_strong_music_terms": strong_music_terms[:12],
        "matched_strong_title_terms": strong_title_terms[:12],
        "matched_type_terms": matched_type_terms[:12],
        "matched_type_title_terms": matched_type_title_terms[:12],
        "subject_matched": bool(ascii_word_match(name, haystack) or matched_aliases),
        "deny_reason": deny,
        "generic": generic,
        "generic_hits": generic_hits,
        "negative_terms": negative_terms[:12],
    }


def classify(review: dict[str, Any], scored: dict[str, Any], rules: dict[str, Any], min_score: int, review_score: int) -> str:
    entity_type = compact(review.get("type"), 80).casefold()
    identity_types = {str(item).casefold() for item in rules.get("identity_types") or []}
    discovery_types = {str(item).casefold() for item in rules.get("discovery_types") or []}
    penalties = set(scored["rule_penalties"])
    tier = scored["domain_tier"]
    strong_subject_signal = bool(scored["matched_strong_music_terms"] or scored["matched_type_terms"] or scored["matched_aliases"])
    strong_title_signal = bool(scored["matched_strong_title_terms"] or scored["matched_type_title_terms"])
    subject_matched = bool(scored["subject_matched"])

    if scored["deny_reason"]:
        return "quarantine_generic_term" if scored["generic"] else "reject_domain"
    if "platform_stoplist" in penalties:
        return "quarantine_generic_term"
    if "negative_subject_terms" in penalties and scored["post_filter_score"] < review_score:
        return "quarantine_generic_term" if scored["generic"] else "reject_subject_mismatch"
    if scored["generic"] and not (tier == "T1_music_direct" and strong_subject_signal):
        return "quarantine_generic_term"
    if entity_type in discovery_types:
        return "discovery_telemetry" if scored["post_filter_score"] >= min_score else "quarantine_low_signal"
    if entity_type not in identity_types:
        return "discovery_telemetry" if scored["post_filter_score"] >= min_score else "quarantine_low_signal"
    if scored["post_filter_score"] >= review_score:
        if not subject_matched:
            return "filtered_candidate"
        if tier == "T1_music_direct" and strong_subject_signal:
            return "review_queue"
        if tier == "T2_social_profile" and strong_title_signal and "short_latin_name" not in penalties:
            return "review_queue"
        if tier == "T3_china_music_media" and strong_title_signal and scored["post_filter_score"] >= review_score + 8:
            return "review_queue"
        return "filtered_candidate"
    if scored["post_filter_score"] >= min_score:
        return "filtered_candidate"
    public_status = compact(review.get("public_search_status"), 120)
    if public_status == "no_public_search_results":
        return "no_public_search_results"
    return "reject_low_signal"


def build_output_row(review: dict[str, Any], scored: dict[str, Any], disposition: str) -> dict[str, Any]:
    reasons = scored["rule_hits"] + scored["rule_penalties"]
    return {
        "schema_version": f"{SCHEMA_VERSION}.{disposition}",
        "entity_search_id": review.get("entity_search_id"),
        "queue_index": review.get("queue_index"),
        "name": compact(review.get("name"), 160),
        "type": compact(review.get("type"), 80),
        "aliases": review.get("aliases") if isinstance(review.get("aliases"), list) else [],
        "row_count": review.get("row_count"),
        "article_count": review.get("article_count"),
        "public_search_status": review.get("public_search_status"),
        "source_tier": "filtered_candidate" if disposition in {"review_queue", "filtered_candidate"} else disposition,
        "post_filter_score": scored["post_filter_score"],
        "disposition": disposition,
        "disposition_reason": "+".join(reasons) if reasons else "no_rule_hits",
        "best_url": scored["url"],
        "best_domain": scored["domain"],
        "best_title": scored["title"],
        "domain_tier": scored["domain_tier"],
        "raw_search_score": scored["raw_search_score"],
        "rule_hits": scored["rule_hits"],
        "rule_penalties": scored["rule_penalties"],
        "matched_aliases": scored["matched_aliases"],
        "matched_music_terms": scored["matched_music_terms"],
        "matched_strong_music_terms": scored["matched_strong_music_terms"],
        "matched_strong_title_terms": scored["matched_strong_title_terms"],
        "matched_type_terms": scored["matched_type_terms"],
        "matched_type_title_terms": scored["matched_type_title_terms"],
        "expected_human_action": "review_direct_source" if disposition == "review_queue" else "none_unless_alias_proven",
        "identity_proof": False,
        "graph_write_allowed": False,
        "accepted_for_graph": False,
    }


def choose_best_evidence(review: dict[str, Any], evidence_rows: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    best_scored: dict[str, Any] | None = None
    best_evidence: dict[str, Any] | None = None
    candidates = evidence_rows or [None]
    for evidence in candidates:
        scored = score_evidence(review, evidence, rules)
        if best_scored is None or scored["post_filter_score"] > best_scored["post_filter_score"]:
            best_scored = scored
            best_evidence = evidence
    assert best_scored is not None
    return best_scored, best_evidence


def select_review_rows(
    review_jsonl: Path,
    *,
    only_candidates: bool,
    limit: int,
    validate_names: list[str],
) -> list[dict[str, Any]]:
    validate_norms = {normalize(name) for name in validate_names if normalize(name)}
    rows: list[dict[str, Any]] = []
    for row in read_jsonl(review_jsonl):
        if validate_norms and normalize(row.get("name")) not in validate_norms:
            continue
        if only_candidates and row.get("public_search_status") not in CANDIDATE_STATUSES:
            continue
        rows.append(row)
        if limit > 0 and len(rows) >= limit and not validate_norms:
            break
    return rows


def should_score_review(review: dict[str, Any], validate_names: list[str]) -> bool:
    if validate_names:
        return True
    return review.get("public_search_status") in CANDIDATE_STATUSES


def fast_disposition_for_noncandidate(review: dict[str, Any]) -> str:
    public_status = compact(review.get("public_search_status"), 120)
    if public_status == "no_public_search_results":
        return "no_public_search_results"
    if public_status == "skipped_unsearchable_entity_name":
        return "quarantine_low_signal"
    return "reject_low_signal"


def fast_scored_for_noncandidate(review: dict[str, Any]) -> dict[str, Any]:
    name = compact(review.get("name"), 160)
    entity_type = compact(review.get("type"), 80).casefold()
    public_status = compact(review.get("public_search_status"), 120)
    return {
        "name": name,
        "type": entity_type,
        "title": "",
        "url": "",
        "domain": "",
        "raw_search_score": 0,
        "post_filter_score": 0,
        "rule_hits": [],
        "rule_penalties": [public_status] if public_status else ["noncandidate_public_search_status"],
        "domain_tier": "not_scored",
        "matched_aliases": [],
        "matched_music_terms": [],
        "matched_strong_music_terms": [],
        "matched_strong_title_terms": [],
        "matched_type_terms": [],
        "matched_type_title_terms": [],
        "subject_matched": False,
        "deny_reason": "",
        "generic": False,
        "generic_hits": [],
        "negative_terms": [],
    }


def collect_evidence(evidence_jsonl: Path, wanted_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    evidence_by_id: dict[str, list[dict[str, Any]]] = {entity_id: [] for entity_id in wanted_ids}
    for row in read_jsonl(evidence_jsonl):
        entity_id = str(row.get("entity_search_id") or "")
        if entity_id in evidence_by_id:
            evidence_by_id[entity_id].append(row)
    return evidence_by_id


def run_post_filter(
    *,
    review_jsonl: Path,
    evidence_jsonl: Path,
    rules_path: Path | None,
    out_dir: Path,
    min_post_filter_score: int | None = None,
    review_score: int | None = None,
    only_candidates: bool = False,
    limit: int = 0,
    validate_names: list[str] | None = None,
    emit_quarantine: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    reject_d_path(review_jsonl, "review_jsonl")
    reject_d_path(evidence_jsonl, "evidence_jsonl")
    reject_d_path(out_dir, "out_dir")
    rules = load_rules(rules_path)
    thresholds = rules.get("thresholds") if isinstance(rules.get("thresholds"), dict) else {}
    min_score = int(min_post_filter_score or thresholds.get("filtered_candidate") or 35)
    queue_score = int(review_score or thresholds.get("review_queue") or 45)
    selected_reviews = select_review_rows(
        review_jsonl,
        only_candidates=only_candidates,
        limit=limit,
        validate_names=validate_names or [],
    )
    scoreable_reviews = [row for row in selected_reviews if should_score_review(row, validate_names or [])]
    wanted_ids = {str(row.get("entity_search_id")) for row in scoreable_reviews if row.get("entity_search_id")}
    evidence_by_id = collect_evidence(evidence_jsonl, wanted_ids)

    disposition_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()

    out_dir.mkdir(parents=True, exist_ok=True)
    filtered_writer = JsonlTempWriter(out_dir / "entity_public_search_filtered_candidates.jsonl")
    review_writer = JsonlTempWriter(out_dir / "entity_public_search_review_queue.jsonl")
    discovery_writer = JsonlTempWriter(out_dir / "entity_public_search_discovery_telemetry.jsonl")
    quarantine_writer = JsonlTempWriter(out_dir / "entity_public_search_quarantine.jsonl")
    audit_writer = JsonlTempWriter(out_dir / "entity_public_search_post_filter_audit.jsonl")
    writers = [filtered_writer, review_writer, discovery_writer, quarantine_writer, audit_writer]
    try:
        for review in selected_reviews:
            entity_id = str(review.get("entity_search_id") or "")
            if should_score_review(review, validate_names or []):
                scored, _best = choose_best_evidence(review, evidence_by_id.get(entity_id, []), rules)
                disposition = classify(review, scored, rules, min_score, queue_score)
            else:
                scored = fast_scored_for_noncandidate(review)
                disposition = fast_disposition_for_noncandidate(review)
            output = build_output_row(review, scored, disposition)
            disposition_counts[disposition] += 1
            if output["best_domain"]:
                domain_counts[output["best_domain"]] += 1
            audit_writer.write(output)
            if disposition == "review_queue":
                review_writer.write(output)
                filtered_writer.write(output)
            elif disposition == "filtered_candidate":
                filtered_writer.write(output)
            elif disposition == "discovery_telemetry":
                discovery_writer.write(output)
            elif emit_quarantine or disposition.startswith("reject_") or disposition.startswith("quarantine_"):
                quarantine_writer.write(output)
        for writer in writers:
            writer.close()
    except Exception:
        for writer in writers:
            writer.abort()
        raise

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_public_search_post_filter_ready_no_graph_acceptance",
        "dry_run": dry_run,
        "rules_path": str(rules_path) if rules_path else None,
        "rules_hash": rules_hash(rules),
        "review_jsonl": file_fingerprint(review_jsonl),
        "evidence_jsonl": file_fingerprint(evidence_jsonl),
        "selected_review_rows": len(selected_reviews),
        "scoreable_review_rows": len(scoreable_reviews),
        "filtered_candidate_rows": filtered_writer.count,
        "review_queue_rows": review_writer.count,
        "quarantine_rows": quarantine_writer.count,
        "discovery_telemetry_rows": discovery_writer.count,
        "audit_rows": audit_writer.count,
        "min_post_filter_score": min_score,
        "review_score": queue_score,
        "only_candidates": only_candidates,
        "limit": limit,
        "validate_names": validate_names or [],
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "top_domains": dict(domain_counts.most_common(30)),
        "paths": {
            "summary": str(out_dir / "entity_public_search_post_filter_summary.json"),
            "filtered_candidates": str(out_dir / "entity_public_search_filtered_candidates.jsonl"),
            "review_queue": str(out_dir / "entity_public_search_review_queue.jsonl"),
            "quarantine": str(out_dir / "entity_public_search_quarantine.jsonl"),
            "discovery_telemetry": str(out_dir / "entity_public_search_discovery_telemetry.jsonl"),
            "audit": str(out_dir / "entity_public_search_post_filter_audit.jsonl"),
        },
        "safety": {
            "report_only": True,
            "public_search_executed": False,
            "graph_write_executed": False,
            "accepted_graph_edges_written": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "d_scan_executed": False,
            "used_9router": False,
        },
    }
    write_json(out_dir / "entity_public_search_post_filter_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-jsonl", type=Path, default=DEFAULT_REVIEW_JSONL)
    parser.add_argument("--evidence-jsonl", type=Path, default=DEFAULT_EVIDENCE_JSONL)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-post-filter-score", type=int, default=None)
    parser.add_argument("--review-score", type=int, default=None)
    parser.add_argument("--only-candidates", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--validate-names", default="")
    parser.add_argument("--emit-quarantine", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-full-run", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_names = [item.strip() for item in args.validate_names.split(",") if item.strip()]
    fullish = args.limit <= 0 and not validate_names
    if fullish and not args.dry_run and args.confirm_full_run != "COMPLETE":
        raise SystemExit("Refusing full post-filter without --confirm-full-run COMPLETE or --dry-run.")
    summary = run_post_filter(
        review_jsonl=args.review_jsonl,
        evidence_jsonl=args.evidence_jsonl,
        rules_path=args.rules,
        out_dir=args.out_dir,
        min_post_filter_score=args.min_post_filter_score,
        review_score=args.review_score,
        only_candidates=args.only_candidates,
        limit=args.limit,
        validate_names=validate_names,
        emit_quarantine=args.emit_quarantine,
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "selected_review_rows": summary["selected_review_rows"],
                "filtered_candidate_rows": summary["filtered_candidate_rows"],
                "review_queue_rows": summary["review_queue_rows"],
                "quarantine_rows": summary["quarantine_rows"],
                "discovery_telemetry_rows": summary["discovery_telemetry_rows"],
                "summary": summary["paths"]["summary"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
