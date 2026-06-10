"""Validate Maigret breadth hits against public source pages.

This is a reports-only P1 gate. It does not prove identity by itself and never
writes graph/vector/DB state. A hit becomes graph-eligible only after a later
human or source-specific gate accepts the evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, request


DEFAULT_CANARY = Path("reports/p1_maigret_canary_20260514/maigret_canary_summary.json")
DEFAULT_CANDIDATES = Path("reports/p1_maigret_candidates_20260514/maigret_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_maigret_source_validation_20260514")
SCHEMA_VERSION = "stage7_p1_maigret_source_validation.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Maigret source validation: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8"))


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
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def token_present(haystack: str, needle: str) -> bool:
    normalized_needle = normalize_token(needle)
    if len(normalized_needle) < 3:
        return False
    return normalized_needle in normalize_token(haystack)


def candidate_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {first_text(row.get("username")): row for row in rows if first_text(row.get("username"))}


def iter_claimed_hits(
    canary: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    limit: int,
    site_filter: set[str] | None = None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for summary in canary.get("summaries") or []:
        username = first_text(summary.get("username"))
        candidate = candidates.get(username, {})
        for hit in summary.get("found") or []:
            url = first_text(hit.get("url"))
            site_name = first_text(hit.get("site_name"))
            if not url:
                continue
            if site_filter and site_name.casefold() not in site_filter:
                continue
            hits.append(
                {
                    "schema_version": SCHEMA_VERSION + ".hit",
                    "username": username,
                    "subject_name": first_text(candidate.get("subject_name")),
                    "source_family": first_text(candidate.get("source_family")),
                    "candidate_score": candidate.get("candidate_score"),
                    "maigret_site_name": site_name,
                    "maigret_status": first_text(hit.get("status")),
                    "maigret_tags": hit.get("tags") or [],
                    "url": url,
                    "candidate_evidence": candidate.get("evidence") or [],
                }
            )
            if limit and len(hits) >= limit:
                return hits
    return hits


def fetch_public_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Stage7MaigretSourceValidation/1.0",
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
    except Exception as exc:  # noqa: BLE001 - report-only canary must capture network failures.
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "content_type": "",
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def evaluate_hit(hit: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    body = first_text(fetched.get("body"))
    final_url = first_text(fetched.get("final_url")) or hit["url"]
    username = first_text(hit.get("username"))
    subject_name = first_text(hit.get("subject_name"))
    body_username_match = token_present(body, username)
    body_subject_match = bool(subject_name) and token_present(body, subject_name)
    url_username_match = token_present(final_url, username)
    accessible = bool(fetched.get("ok"))

    if accessible and (body_username_match or body_subject_match):
        validation_status = "source_validated"
    elif accessible and url_username_match:
        validation_status = "url_accessible_needs_manual_review"
    else:
        validation_status = "blocked_or_unreachable"

    result = dict(hit)
    result.update(
        {
            "checked_at": now_iso(),
            "accessible": accessible,
            "status_code": fetched.get("status_code"),
            "final_url": final_url,
            "content_type": first_text(fetched.get("content_type")),
            "error": first_text(fetched.get("error")),
            "body_username_match": body_username_match,
            "body_subject_match": body_subject_match,
            "url_username_match": url_username_match,
            "validation_status": validation_status,
            "graph_ready": False,
            "identity_proof": False,
        }
    )
    return result


def build_validation_report(
    canary_path: Path,
    candidate_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    site_filter: set[str] | None = None,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_public_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    canary = read_json(canary_path)
    candidates = candidate_map(read_jsonl(candidate_path))
    hits = iter_claimed_hits(canary, candidates, limit=limit, site_filter=site_filter)
    results = [evaluate_hit(hit, fetcher(hit["url"], timeout_sec, max_bytes)) for hit in hits]

    status_counts: dict[str, int] = {}
    for result in results:
        status = result["validation_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    validated = status_counts.get("source_validated", 0)
    accessible_review = status_counts.get("url_accessible_needs_manual_review", 0)
    if validated:
        decision = "maigret_source_validation_partial"
    elif accessible_review:
        decision = "maigret_source_validation_needs_manual_review"
    elif results:
        decision = "maigret_source_validation_blocked"
    else:
        decision = "maigret_source_validation_empty"

    result_path = out_dir / "maigret_source_validation.jsonl"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(results),
        "canary_path": str(canary_path),
        "candidate_path": str(candidate_path),
        "result_path": str(result_path),
        "checked_hits": len(results),
        "status_counts": status_counts,
        "source_validated_hits": validated,
        "manual_review_hits": accessible_review,
        "graph_ready_hits": 0,
        "identity_proof_hits": 0,
        "safety": [
            "reports_only",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
            "maigret_hit_is_not_identity_proof",
        ],
    }
    write_jsonl(result_path, results)
    write_json(out_dir / "maigret_source_validation_summary.json", report)
    write_markdown(out_dir / "maigret_source_validation_summary.md", report, results)
    return report


def write_markdown(path: Path, report: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        "# P1 Maigret Source Validation",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- checked_hits: `{report['checked_hits']}`",
        f"- source_validated_hits: `{report['source_validated_hits']}`",
        f"- manual_review_hits: `{report['manual_review_hits']}`",
        f"- graph_ready_hits: `{report['graph_ready_hits']}`",
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
            "## Checked Hits",
            "",
            "| username | site | status | http | body_user | body_subject | url_user |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for result in results:
        lines.append(
            "| {username} | {site} | {status} | {http} | {bu} | {bs} | {uu} |".format(
                username=result["username"],
                site=result["maigret_site_name"],
                status=result["validation_status"],
                http=result.get("status_code") or "",
                bu=result["body_username_match"],
                bs=result["body_subject_match"],
                uu=result["url_username_match"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Source validation is not identity proof.",
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
    parser.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--max-bytes", type=int, default=256_000)
    parser.add_argument("--site", action="append", default=[], help="Optional site_name filter; may be repeated.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    site_filter = {site.casefold() for site in args.site} if args.site else None
    report = build_validation_report(
        canary_path=args.canary,
        candidate_path=args.candidates,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
        site_filter=site_filter,
    )
    print(json.dumps({"decision": report["decision"], "checked_hits": report["checked_hits"], "summary": str(args.out_dir / "maigret_source_validation_summary.json")}, ensure_ascii=False, indent=2))
    return 0 if report["checked_hits"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
