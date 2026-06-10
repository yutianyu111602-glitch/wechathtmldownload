#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_previous_csv(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("account_id"):
            out[row["account_id"]] = row
        if row.get("account_name"):
            out.setdefault(row["account_name"], row)
    return out


def article_probe(endpoint: str, auth_key: str, fakeid: str, timeout: int) -> dict[str, Any]:
    if not fakeid:
        return {"status": "missing_fakeid"}
    params = urllib.parse.urlencode({"fakeid": fakeid, "begin": "0", "size": "1"})
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/api/public/v1/article?{params}", headers={"X-Auth-Key": auth_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - keep exact probe error for audit
        return {"status": "probe_error", "error": str(exc)}
    base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
    ret = base_resp.get("ret", payload.get("ret"))
    message = base_resp.get("err_msg", payload.get("message"))
    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    status = "live_ok" if ret == 0 else "live_error"
    if ret == 0 and not articles:
        status = "live_ok_empty"
    if ret == 200013 or "freq control" in str(message).lower():
        status = "rate_limited"
    latest = articles[0] if articles and isinstance(articles[0], dict) else {}
    latest_published_at = latest.get("publish_time") or latest.get("published_at") or latest.get("date") or ""
    if not latest_published_at and latest.get("update_time"):
        try:
            latest_published_at = datetime.fromtimestamp(int(latest["update_time"])).date().isoformat()
        except Exception:
            latest_published_at = str(latest.get("update_time") or "")
    return {
        "status": status,
        "ret": ret,
        "message": message,
        "article_count_sample": len(articles),
        "latest_title": latest.get("title") or "",
        "latest_published_at": latest_published_at,
    }


def account_dir_stats(download_dir: Path, account_name: str) -> dict[str, Any]:
    account_dir = download_dir / account_name
    if not account_dir.exists():
        return {"download_exact_dir": "no", "download_articles": 0, "latest_download_article_date": ""}
    articles_path = account_dir / "_articles.json"
    if not articles_path.exists():
        return {"download_exact_dir": "yes", "download_articles": 0, "latest_download_article_date": ""}
    try:
        payload = load_json(articles_path)
    except Exception:
        return {"download_exact_dir": "yes", "download_articles": 0, "latest_download_article_date": ""}
    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    latest = ""
    for item in articles:
        if not isinstance(item, dict):
            continue
        value = str(item.get("publish_time") or item.get("published_at") or item.get("date") or "")[:10]
        if value > latest:
            latest = value
    return {"download_exact_dir": "yes", "download_articles": len(articles), "latest_download_article_date": latest}


def write_reports(out_json: Path, out_md: Path, out_csv: Path, report: dict[str, Any]) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = report["rows"]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "account_id",
                "account_name",
                "followed_in_registry",
                "docker_live_verified",
                "where_to_rave_image_match",
                "city_key",
                "registry_status",
                "operating_bucket",
                "download_exact_dir",
                "download_articles",
                "latest_download_article_date",
                "probe_ret",
                "probe_message",
                "probe_latest_title",
                "probe_latest_published_at",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = report["summary"]
    inactive = [row for row in rows if row["registry_status"] != "active"]
    lines = [
        f"# Weekly Docker Registry Crosscheck {report['generated_at'][:10]}",
        "",
        "## Summary",
        "",
        f"- registry_followed_accounts: `{summary['registry_followed_accounts']}`",
        f"- registry_active_operating_bucket: `{summary['registry_active_operating_bucket']}`",
        f"- registry_inactive_or_non_event_source: `{summary['registry_inactive_or_non_event_source']}`",
        f"- exact_download_account_dirs: `{summary['exact_download_account_dirs']}`",
        f"- where_to_rave_image_matches_by_manual_ocr_list: `{summary['where_to_rave_image_matches_by_manual_ocr_list']}`",
        f"- docker_live_probe_ok_or_empty: `{summary['docker_live_probe_ok_or_empty']}`",
        f"- docker_live_probe_rate_limited: `{summary['docker_live_probe_rate_limited']}`",
        f"- docker_live_probe_errors: `{summary['docker_live_probe_errors']}`",
        f"- docker_follow_list_probe: `{summary['docker_follow_list_probe']}`",
        "",
        "## Inactive / Closed / Non-event Source Table",
        "",
        "| account | followed | image_match | status | docker_live | evidence/action |",
        "|---|---:|---:|---|---|---|",
    ]
    for row in inactive:
        lines.append(
            f"| {row['account_name']} | yes | {row['where_to_rave_image_match']} | {row['registry_status']} | {row['docker_live_verified']} | {row['notes']} |"
        )
    lines.extend(
        [
            "",
            "## Full Table",
            "",
            f"Full table is in CSV: `{out_csv}`.",
            "",
            "| account | city | image | status | docker_live | articles | latest |",
            "|---|---|---:|---|---|---:|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['account_name']} | {row['city_key']} | {row['where_to_rave_image_match']} | {row['registry_status']} | {row['docker_live_verified']} | {row['download_articles']} | {row['latest_download_article_date']} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--previous-csv", default="")
    parser.add_argument("--endpoint", default=os.environ.get("EXPORTER_URL", "http://localhost:17300"))
    parser.add_argument("--auth-env", default="MPTEXT_AUTH_KEY")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--out-csv", required=True)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep-ms", type=int, default=150)
    args = parser.parse_args()

    auth_key = os.environ.get(args.auth_env, "")
    registry = load_json(Path(args.registry))
    accounts = registry.get("accounts") if isinstance(registry.get("accounts"), list) else []
    previous = read_previous_csv(Path(args.previous_csv)) if args.previous_csv else {}
    rows = []
    counters: Counter[str] = Counter()

    follow_list_probe = "not_attempted"
    if auth_key:
        params = urllib.parse.urlencode({"keyword": "", "begin": "0", "size": "200"})
        req = urllib.request.Request(f"{args.endpoint.rstrip('/')}/api/public/v1/account?{params}", headers={"X-Auth-Key": auth_key})
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
            follow_list_probe = f"not_available: ret={base_resp.get('ret')} err={base_resp.get('err_msg')}"
        except Exception as exc:  # noqa: BLE001
            follow_list_probe = f"error: {exc}"
    else:
        follow_list_probe = f"not_verified: {args.auth_env} missing"

    for account in accounts:
        account_id = str(account.get("account_id") or "")
        account_name = str(account.get("account_name") or account_id)
        prev = previous.get(account_id) or previous.get(account_name) or {}
        status = str(account.get("status") or "review")
        image_match = prev.get("where_to_rave_image_match") or "unknown"
        notes = str(account.get("inactive_reason") or prev.get("notes") or "")
        if not notes and status == "active":
            notes = "active registry source"
        dir_stats = account_dir_stats(Path(args.download_dir), account_name)
        probe = article_probe(args.endpoint, auth_key, str(account.get("fakeid") or ""), args.timeout) if auth_key else {"status": "not_verified_auth_key_missing"}
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000)
        docker_status = str(probe.get("status"))
        operating_bucket = "运营中/可抓取" if status == "active" else "已停运/非活动源/暂停发布"
        rows.append(
            {
                "account_id": account_id,
                "account_name": account_name,
                "followed_in_registry": "yes",
                "docker_live_verified": docker_status,
                "where_to_rave_image_match": image_match,
                "city_key": str(account.get("city_key") or ""),
                "registry_status": status,
                "operating_bucket": operating_bucket,
                "download_exact_dir": dir_stats["download_exact_dir"],
                "download_articles": dir_stats["download_articles"],
                "latest_download_article_date": dir_stats["latest_download_article_date"],
                "probe_ret": str(probe.get("ret") if probe.get("ret") is not None else ""),
                "probe_message": str(probe.get("message") or probe.get("error") or ""),
                "probe_latest_title": str(probe.get("latest_title") or ""),
                "probe_latest_published_at": str(probe.get("latest_published_at") or ""),
                "notes": notes,
            }
        )
        counters[status] += 1
        counters[f"docker_{docker_status}"] += 1
        if dir_stats["download_exact_dir"] == "yes":
            counters["exact_download_account_dirs"] += 1
        if image_match == "yes":
            counters["image_matches"] += 1

    summary = {
        "registry_followed_accounts": len(accounts),
        "registry_active_operating_bucket": counters.get("active", 0),
        "registry_inactive_or_non_event_source": len(accounts) - counters.get("active", 0),
        "exact_download_account_dirs": counters.get("exact_download_account_dirs", 0),
        "where_to_rave_image_matches_by_manual_ocr_list": counters.get("image_matches", 0),
        "docker_live_probe_ok_or_empty": counters.get("docker_live_ok", 0) + counters.get("docker_live_ok_empty", 0),
        "docker_live_probe_rate_limited": counters.get("docker_rate_limited", 0),
        "docker_live_probe_errors": counters.get("docker_live_error", 0) + counters.get("docker_probe_error", 0),
        "docker_follow_list_probe": follow_list_probe,
        "docker_status_counts": {k.removeprefix("docker_"): v for k, v in counters.items() if k.startswith("docker_")},
    }
    report = {
        "schema_version": "weekly_docker_registry_crosscheck.v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "endpoint": args.endpoint,
        "registry": args.registry,
        "download_dir": args.download_dir,
        "summary": summary,
        "rows": rows,
    }
    write_reports(Path(args.out_json), Path(args.out_md), Path(args.out_csv), report)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
