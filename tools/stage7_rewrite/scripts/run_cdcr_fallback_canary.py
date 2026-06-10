"""Run a bounded CDCR fallback canary through public Bilibili search URLs.

CDCR legacy rows contain Bilibili-derived text context but no direct live URL.
This gate checks whether bounded public search URLs are reachable and whether
returned pages contain enough CDCR/artist text evidence for a later source gate.
It is reports-only: no graph/vector/DB writes, no paid API, no D: scan.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


DEFAULT_ASSETS = Path("reports/p1_dj_dataset_import_20260514/radio_social_assets.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_cdcr_fallback_canary_20260515")
SCHEMA_VERSION = "stage7_p1_cdcr_fallback_canary.v1"
BILIBILI_SEARCH = "https://search.bilibili.com/all"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for CDCR fallback canary: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
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


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def token_present(haystack: str, needle: str) -> bool:
    needle_norm = normalize_token(needle)
    if len(needle_norm) < 3:
        return False
    return needle_norm in normalize_token(haystack)


def context_preview(contexts: list[str]) -> str:
    for context in contexts:
        text = first_text(context)
        if text:
            return text[:160]
    return ""


def search_query(row: dict[str, Any]) -> str:
    artist = first_text(row.get("artist_name") or row.get("title"))
    contexts = [first_text(item) for item in row.get("track_contexts") or [] if first_text(item)]
    if artist:
        return f"cdcr.live {artist}"
    preview = context_preview(contexts)
    return preview[:80] if preview else "cdcr.live"


def search_url(query: str) -> str:
    return BILIBILI_SEARCH + "?" + parse.urlencode({"keyword": query})


def select_cdcr_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if first_text(row.get("source_family")).casefold() != "cdcr":
            continue
        artist = first_text(row.get("artist_name") or row.get("title"))
        contexts = row.get("track_contexts") or []
        if not artist and not contexts:
            continue
        key = artist.casefold() or context_preview(contexts).casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
        if limit and len(selected) >= limit:
            break
    return selected


def fetch_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Stage7CDCRFallbackCanary/1.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "final_url": response.geturl(),
                "content_type": response.headers.get("Content-Type", ""),
                "body": body.decode(charset, errors="replace"),
                "error": "",
            }
    except error.HTTPError as exc:
        body = exc.read(max_bytes).decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": False,
            "status_code": int(exc.code),
            "final_url": exc.geturl(),
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": body,
            "error": f"HTTPError: {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001 - report-only canary captures network failures.
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "content_type": "",
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def evaluate_row(row: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    artist = first_text(row.get("artist_name") or row.get("title"))
    contexts = [first_text(item) for item in row.get("track_contexts") or [] if first_text(item)]
    query = search_query(row)
    url = search_url(query)
    body = first_text(fetched.get("body"))
    accessible = bool(fetched.get("ok"))
    cdcr_match = token_present(body, "cdcr") or token_present(body, "cdcr.live")
    artist_match = bool(artist) and token_present(body, artist)
    context_match = any(token_present(body, item) for item in contexts[:3])

    if accessible and cdcr_match and (artist_match or context_match):
        status = "fallback_source_candidate"
    elif accessible and (artist_match or context_match):
        status = "fallback_needs_manual_review"
    elif accessible:
        status = "fallback_search_accessible_no_match"
    else:
        status = "fallback_blocked_or_unreachable"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "checked_at": now_iso(),
        "artist_name": artist,
        "title": first_text(row.get("title")),
        "source_family": "cdcr",
        "verification_status": first_text(row.get("verification_status")),
        "query": query,
        "search_url": url,
        "context_preview": context_preview(contexts),
        "accessible": accessible,
        "status_code": fetched.get("status_code"),
        "final_url": first_text(fetched.get("final_url")) or url,
        "content_type": first_text(fetched.get("content_type")),
        "error": first_text(fetched.get("error")),
        "cdcr_match": cdcr_match,
        "artist_match": artist_match,
        "context_match": context_match,
        "fallback_status": status,
        "graph_ready": False,
        "identity_proof": False,
    }


def build_canary(
    assets_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    rows = select_cdcr_rows(read_jsonl(assets_path), limit)
    results: list[dict[str, Any]] = []
    for row in rows:
        url = search_url(search_query(row))
        results.append(evaluate_row(row, fetcher(url, timeout_sec, max_bytes)))

    status_counts: dict[str, int] = {}
    for result in results:
        status = result["fallback_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    candidate_count = status_counts.get("fallback_source_candidate", 0)
    review_count = status_counts.get("fallback_needs_manual_review", 0)
    if candidate_count:
        decision = "p1_cdcr_fallback_canary_partial"
    elif review_count:
        decision = "p1_cdcr_fallback_canary_needs_manual_review"
    elif results:
        decision = "p1_cdcr_fallback_canary_blocked"
    else:
        decision = "p1_cdcr_fallback_canary_empty"

    result_path = out_dir / "cdcr_fallback_canary.jsonl"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(results),
        "assets_path": str(assets_path),
        "result_path": str(result_path),
        "checked_rows": len(results),
        "status_counts": status_counts,
        "fallback_source_candidates": candidate_count,
        "manual_review_rows": review_count,
        "graph_ready_rows": 0,
        "identity_proof_rows": 0,
        "safety": [
            "reports_only",
            "public_bilibili_search_urls_only",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_jsonl(result_path, results)
    write_json(out_dir / "cdcr_fallback_canary_summary.json", report)
    write_markdown(out_dir / "cdcr_fallback_canary_summary.md", report, results)
    return report


def write_markdown(path: Path, report: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        "# P1 CDCR Fallback Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- checked_rows: `{report['checked_rows']}`",
        f"- fallback_source_candidates: `{report['fallback_source_candidates']}`",
        f"- manual_review_rows: `{report['manual_review_rows']}`",
        f"- graph_ready_rows: `{report['graph_ready_rows']}`",
        f"- result_path: `{report['result_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(report["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Checked Rows",
            "",
            "| artist | status | http | cdcr | artist | context |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for result in results:
        lines.append(
            "| {artist} | {status} | {http} | {cdcr} | {artist_match} | {context_match} |".format(
                artist=result["artist_name"],
                status=result["fallback_status"],
                http=result.get("status_code") or "",
                cdcr=result["cdcr_match"],
                artist_match=result["artist_match"],
                context_match=result["context_match"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Public Bilibili search URL evidence is not identity proof.",
            "- No graph/vector/DB write.",
            "- No paid API.",
            "- No D: scan.",
            "- No publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--max-bytes", type=int, default=256_000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    report = build_canary(
        assets_path=args.assets,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(json.dumps({"decision": report["decision"], "checked_rows": report["checked_rows"], "summary": str(args.out_dir / "cdcr_fallback_canary_summary.json")}, ensure_ascii=False, indent=2))
    return 0 if report["checked_rows"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
