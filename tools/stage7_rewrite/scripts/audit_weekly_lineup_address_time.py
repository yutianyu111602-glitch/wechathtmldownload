#!/usr/bin/env python3
"""Audit weekly release lineup, address, and time against materialized LLM output.

This is a conservative publish-quality gate. It does not invent missing values.
It flags places where current release fields disagree with the materialized
DeepSeek Pro extraction or look like copied prose instead of structured data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_API_DIR = Path("services/weekly_activity_cloudrun/data/current_release")

LINEUP_NOISE_RE = re.compile(
    r"点击|海报|详情|查看|地址|时间|门票|票价|免费|入场|主办|活动|演出|这里|欢迎|扫码|公众号|来源|"
    r"转发|报名|工作坊|咖啡|酒吧|俱乐部|限定|预告|呈现|present|pres\.",
    re.I,
)
LINEUP_PROSE_RE = re.compile(
    r"组织|模式|操作|能量|输出|感染力|情绪|身体|系统|方式|闻名|负责|参与|推荐|售完|即止|商品|阵容|团体|成员|同时|钟爱|"
    r"因为|开始了|分享|不支持|退换|预售|限量|时而|融合|热情|惬意|地下音乐|玩家|听见|设计|单曲|"
    r"sound designer|music producer|he began",
    re.I,
)
GENRE_WORDS = {
    "afro",
    "ambient",
    "bass",
    "budots",
    "breaks",
    "disco",
    "drum",
    "electro",
    "funk",
    "hip-hop",
    "house",
    "jazz",
    "techno",
    "trance",
    "ukg",
}
AGGREGATE_TITLE_RE = re.compile(
    r"总览|活动一览|活动全览|活动安排|活动日程|全览|预览|本周活动|本周预览|月.*安排|月.*预告|月.*活动",
    re.I,
)
ADJUDICATED_ADDRESS_DECISIONS = {
    "manual_registry_over_llm",
    "manual_locked_place_over_llm",
    "registry_over_source_poi",
    "registry_over_poster_ocr_address",
    "source_candidate_over_registry",
    "source_candidate_over_source_text",
    "verified_registry_over_llm",
    "known_venue_resource_correction",
    "venue_id_normalization_correction",
    "event_specific_venue_correction",
}
ADJUDICATED_TIME_DECISIONS = {"poster_ocr_over_llm", "verified_registry_over_llm", "source_candidate_over_llm"}
MANUAL_LOCKED_ADDRESS_SOURCES = {
    "manual_registry",
    "manual_user_confirmed_map_crosscheck",
    "tencent_map_picker_user_confirmed",
    "tencent_amap_cross_geocode_user_confirmed",
    "tencent_amap_exact_place_user_confirmed",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def item_id(item: dict[str, Any]) -> str:
    return first(item.get("id") or item.get("event_id") or item.get("article_id") or item.get("queue_id"))


def has_manual_locked_address(item: dict[str, Any]) -> bool:
    source = first(item.get("address_source") or item.get("geo_source"))
    return (
        source in MANUAL_LOCKED_ADDRESS_SOURCES
        or bool(item.get("place_fields_locked"))
        or bool(item.get("geo_locked"))
    )


def title_of(item: dict[str, Any]) -> str:
    return first(item.get("title_display") or item.get("title") or item.get("title_original"))


def title_variants(item: dict[str, Any]) -> list[str]:
    values = [
        first(item.get("title_display")),
        first(item.get("title")),
        first(item.get("title_original")),
    ]
    raw_titles = item.get("raw_titles")
    if isinstance(raw_titles, list):
        values.extend(first(value) for value in raw_titles)
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def aggregate_title_text(item: dict[str, Any]) -> str:
    return "\n".join(title_variants(item))


def venue_of(item: dict[str, Any]) -> str:
    return first(item.get("venue_name") or item.get("venue"))


def current_address(item: dict[str, Any]) -> str:
    return first(item.get("address_full") or item.get("address"))


def current_time(item: dict[str, Any]) -> str:
    return first(item.get("event_time_text") or item.get("running_hours_text") or item.get("time_start"))


def item_date_end(item: dict[str, Any]) -> str:
    return first(
        item.get("event_date_end")
        or item.get("event_date_start")
        or item.get("event_date_iso_guess")
        or item.get("date_end")
        or item.get("date_start")
        or item.get("date")
    )


def item_is_current_or_future(item: dict[str, Any], today: str) -> bool:
    item_end = item_date_end(item)
    return not today or not item_end or item_end >= today


def list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [first(item) for item in value if first(item)]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[\n/、,，]+", value) if part.strip()]
    return []


def current_lineup(item: dict[str, Any]) -> list[str]:
    values = list_strings(item.get("lineup"))
    if not values:
        values = list_strings(item.get("lineup_artists"))
    return values


def norm_text(value: str) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"[\s\-—–:：,，.。()（）\[\]【】号室层楼铺店club酒吧音乐厅俱乐部]+", "", text)
    return text


def norm_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s\-—–:：,，.。()（）\[\]【】]+", "", text.lower())


def normalized_risk_flag(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", first(value).lower())


def has_strong_single_event_poster_evidence(item: dict[str, Any], artists: list[str]) -> bool:
    if not any(first(item.get(key)) for key in ("event_date_start", "event_date", "date")):
        return False
    if not any(first(item.get(key)) for key in ("venue_name", "venue")):
        return False
    if not artists:
        return False
    evidence = item.get("poster_selection_evidence")
    if not isinstance(evidence, dict):
        evidence = item.get("posterSelectionEvidence")
    if not isinstance(evidence, dict):
        return False
    if not any(first(evidence.get(key)) for key in ("selected_sha", "selected_source_url")):
        return False
    risk_flags = {normalized_risk_flag(value) for value in list_strings(evidence.get("risk_flags"))}
    if risk_flags & {"missinglineupvisible", "notmusicevent", "notelectronicmusicevent"}:
        return False
    evidence_text = "\n".join(
        list_strings(evidence.get("cleaned_lineup"))
        + list_strings(evidence.get("lineup_evidence"))
        + list_strings(evidence.get("visible_text_lines"))
    )
    normalized_evidence = norm_name(evidence_text)
    return bool(normalized_evidence) and all(
        norm_name(artist) and norm_name(artist) in normalized_evidence for artist in artists
    )


def time_tokens(value: str) -> tuple[str, str]:
    text = str(value or "").lower()
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"\s+", "", text)
    text = text.replace("late", "late").replace("end", "late").replace("？", "late").replace("?", "late")
    times = re.findall(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?!\d)", text)
    normalized = []
    for hour, minute, suffix in times:
        hour_int = int(hour)
        if suffix == "pm" and hour_int < 12:
            hour_int += 12
        elif suffix == "am" and hour_int == 12:
            hour_int = 0
        normalized.append(f"{hour_int:02d}:{minute or '00'}")
    start = normalized[0] if normalized else ""
    end = normalized[1] if len(normalized) > 1 else ("late" if "late" in text else "")
    return start, end


def time_equivalent(left: str, right: str) -> bool:
    if norm_name(left) == norm_name(right):
        return True
    left_start, left_end = time_tokens(left)
    right_start, right_end = time_tokens(right)
    if not left_start or not right_start:
        return False
    if left_start != right_start:
        return False
    # "22:30", "22:30-end", and "22:30-Late" are display-equivalent for the app.
    loose = {"", "late"}
    return left_end in loose and right_end in loose


def address_compatible(left: str, right: str) -> bool:
    a = norm_text(left)
    b = norm_text(right)
    if not a or not b:
        return True
    if a in b or b in a:
        return True
    return address_tokens_contained(a, b) or address_tokens_contained(b, a)


ADDRESS_TOKEN_RE = re.compile(
    r".+?(?:省|市|区|县|路|街道|街|镇|乡|村|广场|园区|公园|中心|大厦|工厂|厂|馆)|[a-z0-9]+",
    re.I,
)


def address_tokens(value: str) -> list[str]:
    text = norm_text(value)
    tokens = [match.group(0) for match in ADDRESS_TOKEN_RE.finditer(text)]
    return [token for token in tokens if len(token) >= 2]


def address_tokens_contained(haystack: str, needle: str) -> bool:
    tokens = address_tokens(needle)
    if len(tokens) < 2:
        return False
    position = 0
    for token in tokens:
        index = haystack.find(token, position)
        if index < 0:
            return False
        position = index + len(token)
    return True


def clean_lineup_for_compare(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        artist = first(value)
        artist = re.sub(r"\s+", " ", artist).strip(" \t\r\n-–—•·、,，;；")
        artist = re.sub(r"^[与和]\s*", "", artist)
        artist = re.sub(r"^\d{1,2}\s*[｜|]\s*", "", artist)
        artist = re.sub(r"\s*[｜|]\s*(?:pop|rock|techno|house|bass|jazz|funk|disco).*$", "", artist, flags=re.I)
        if not artist or len(artist) > 32:
            continue
        if re.match(r"^[在他她它]\s+", artist):
            continue
        if LINEUP_NOISE_RE.search(artist) or LINEUP_PROSE_RE.search(artist):
            continue
        if re.search(r"\b\d{1,2}[./-]\d{1,2}\b|^\d{1,2}[./-]\d{1,2}\s*[:：]", artist):
            continue
        if norm_name(artist) in {norm_name(item) for item in GENRE_WORDS}:
            continue
        key = norm_name(artist)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(artist)
    return out


def load_enrichments(api_dir: Path) -> dict[str, dict[str, Any]]:
    index_path = enrichment_index_path(api_dir)
    if not index_path.exists():
        return {}
    index = read_json(index_path)
    out: dict[str, dict[str, Any]] = {}
    for entry in index.get("enrichments") or []:
        eid = first(entry.get("id"))
        rel = first(entry.get("path"))
        if not eid or not rel:
            continue
        path = api_dir / rel
        if not path.exists():
            continue
        payload = read_json(path)
        enriched = ((payload.get("enriched") or {}).get("enrichment") or {})
        out[eid] = enriched
    return out


def enrichment_index_path(api_dir: Path) -> Path:
    return api_dir / "llm" / "enrichment_index.json"


def audit(
    api_dir: Path,
    soft_missing_lineup: bool = False,
    soft_missing_enrichment: bool = False,
) -> dict[str, Any]:
    current = read_json(api_dir / "current.json")
    items = current.get("items") if isinstance(current, dict) else current
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain items: {api_dir / 'current.json'}")

    today = date.today().isoformat()
    enrichment_index_expected = enrichment_index_path(api_dir).exists()
    enrichments = load_enrichments(api_dir)
    missing_enrichment_current_count = 0
    issues: dict[str, list[dict[str, Any]]] = {
        "missing_lineup": [],
        "underfilled_lineup_review": [],
        "suspicious_lineup": [],
        "lineup_diff": [],
        "adjudicated_lineup_diff": [],
        "address_diff": [],
        "adjudicated_address_diff": [],
        "time_diff": [],
        "adjudicated_time_diff": [],
        "aggregate_like": [],
        "missing_enrichment": [],
    }

    for item in items:
        iid = item_id(item)
        title = title_of(item)
        venue = venue_of(item)
        current_artists = current_lineup(item)
        enriched = enrichments.get(iid)
        has_enriched = enriched is not None
        if enriched is None:
            row = {
                "id": iid,
                "title": title,
                "venue": venue,
                "date_end": item_date_end(item),
                "current_feed_relevant": item_is_current_or_future(item, today),
            }
            if row["current_feed_relevant"]:
                missing_enrichment_current_count += 1
            issues["missing_enrichment"].append(row)
            enriched = {}
        pro_artists = list_strings(enriched.get("lineup_artists"))

        if not current_artists:
            issues["missing_lineup"].append(
                {
                    "id": iid,
                    "title": title,
                    "venue": venue,
                    "current_feed_relevant": item_is_current_or_future(item, today),
                }
            )
        elif item_is_current_or_future(item, today) and len(clean_lineup_for_compare(current_artists)) < 3:
            issues["underfilled_lineup_review"].append(
                {
                    "id": iid,
                    "title": title,
                    "venue": venue,
                    "lineup": current_artists[:8],
                    "note": "review with VL evidence if this is a normal club night; do not invent artists for one-guest or live-show events",
                }
            )

        bad_artists = [
            artist
            for artist in current_artists
            if len(artist) > 32
            or LINEUP_NOISE_RE.search(artist)
            or LINEUP_PROSE_RE.search(artist)
            or (re.search(r"[。；：:，]", artist) and re.search(r"[\u4e00-\u9fff]", artist))
        ]
        if bad_artists:
            issues["suspicious_lineup"].append({"id": iid, "title": title, "venue": venue, "bad": bad_artists[:8]})

        current_compare = clean_lineup_for_compare(current_artists)
        pro_compare = clean_lineup_for_compare(pro_artists)
        current_set = {norm_name(value) for value in current_compare if norm_name(value)}
        pro_set = {norm_name(value) for value in pro_compare if norm_name(value)}
        if has_enriched and current_set != pro_set and (current_set or pro_set):
            row = {
                "id": iid,
                "title": title,
                "venue": venue,
                "current": current_artists[:12],
                "pro": pro_artists[:12],
                "current_compared": current_compare[:12],
                "pro_compared": pro_compare[:12],
                "only_current": [value for value in current_compare if norm_name(value) not in pro_set][:8],
                "only_pro": [value for value in pro_compare if norm_name(value) not in current_set][:8],
            }
            verification = item.get("lineup_quality") if isinstance(item.get("lineup_quality"), dict) else {}
            decision = first(verification.get("decision"))
            if decision in {
                "source_candidate_over_llm_lineup",
                "cleaned_current_lineup",
                "cleaned_source_lineup",
                "deepseek_pro_source_grounded_lineup",
                "source_grounded_lineup",
                "poster_vl_source_grounded_lineup",
                "cleared_untrusted_lineup",
            }:
                row["decision"] = decision
                row["verification_note"] = first(verification.get("note"))
                issues["adjudicated_lineup_diff"].append(row)
            else:
                issues["lineup_diff"].append(row)

        pro_address = first(enriched.get("address_candidate"))
        if has_enriched and current_address(item) and pro_address and not address_compatible(current_address(item), pro_address):
            row = {
                "id": iid,
                "title": title,
                "venue": venue,
                "current": current_address(item),
                "pro": pro_address,
                "address_source": first(item.get("address_source")),
            }
            verification = item.get("address_verification") if isinstance(item.get("address_verification"), dict) else {}
            decision = first(verification.get("decision"))
            if decision in ADJUDICATED_ADDRESS_DECISIONS or has_manual_locked_address(item):
                row["decision"] = decision or "manual_locked_place_over_llm"
                row["verification_note"] = first(verification.get("note")) or (
                    "manual or locked venue address is treated as the public display authority over materialized LLM candidates"
                )
                issues["adjudicated_address_diff"].append(row)
            else:
                issues["address_diff"].append(row)

        pro_time = first(enriched.get("event_time_text"))
        if has_enriched and current_time(item) and pro_time and not time_equivalent(current_time(item), pro_time):
            row = {
                "id": iid,
                "title": title,
                "venue": venue,
                "current": current_time(item),
                "pro": pro_time,
                "time_source": first(item.get("event_time_source") or item.get("running_hours_source")),
            }
            verification = item.get("time_verification") if isinstance(item.get("time_verification"), dict) else {}
            decision = first(verification.get("decision"))
            if decision in ADJUDICATED_TIME_DECISIONS:
                row["decision"] = decision
                row["verification_note"] = first(verification.get("note"))
                issues["adjudicated_time_diff"].append(row)
            else:
                issues["time_diff"].append(row)

        if AGGREGATE_TITLE_RE.search(aggregate_title_text(item)) and not has_strong_single_event_poster_evidence(
            item,
            current_artists,
        ):
            issues["aggregate_like"].append(
                {
                    "id": iid,
                    "title": title,
                    "venue": venue,
                    "date": first(item.get("event_date_start") or item.get("event_date_iso_guess")),
                    "time": current_time(item),
                    "lineup": current_artists[:8],
                }
            )

    summary = {key: len(value) for key, value in issues.items()}
    missing_enrichment_fail_count = 0 if soft_missing_enrichment else (
        missing_enrichment_current_count if enrichment_index_expected else 0
    )
    missing_lineup_fail_count = sum(1 for row in issues["missing_lineup"] if row.get("current_feed_relevant", True))
    if soft_missing_lineup:
        missing_lineup_fail_count = 0
    hard_fail_count = (
        summary["suspicious_lineup"]
        + summary["address_diff"]
        + summary["time_diff"]
        + summary["aggregate_like"]
        + missing_enrichment_fail_count
        + missing_lineup_fail_count
    )
    return {
        "schema_version": "weekly_activity_lineup_address_time_audit.v1",
        "api_dir": str(api_dir),
        "current_date": today,
        "item_count": len(items),
        "enrichment_index_expected": enrichment_index_expected,
        "enrichment_count": len(enrichments),
        "missing_enrichment_current_count": missing_enrichment_current_count,
        "summary": summary,
        "hard_fail_count": hard_fail_count,
        "issues": {key: value[:80] for key, value in issues.items()},
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--soft-missing-lineup", action="store_true",
                        help="Downgrade missing_lineup from hard-fail to soft warning (for confirmed events with no DJs listed in source)")
    parser.add_argument("--soft-missing-enrichment", action="store_true",
                        help="Downgrade missing LLM enrichment from hard-fail to warning for incremental packages whose fields are already source-grounded")
    args = parser.parse_args(argv)

    report = audit(
        args.api_dir,
        soft_missing_lineup=args.soft_missing_lineup,
        soft_missing_enrichment=args.soft_missing_enrichment,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and report["hard_fail_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
