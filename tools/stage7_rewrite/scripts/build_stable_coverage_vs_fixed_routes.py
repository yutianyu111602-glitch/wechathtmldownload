from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


LANES = [
    "ready_text",
    "needs_ocr",
    "short_text_review",
    "empty_no_local_image",
    "needs_asset_repair",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def article_uid(row: dict[str, Any]) -> str:
    direct = row.get("article_uid") or row.get("uid")
    if direct:
        return str(direct)

    account = row.get("account_key") or row.get("account") or row.get("biz")
    article_id = row.get("msg_id") or row.get("mid") or row.get("article_id")
    if account and article_id:
        return f"{account}/{article_id}"
    return ""


def read_ids(path: Path) -> list[str]:
    ids: list[str] = []
    for row in read_jsonl(path):
        uid = article_uid(row)
        if uid:
            ids.append(uid)
    return ids


def build_report(*, route_root: Path, stable_manifest: Path, label: str) -> dict[str, Any]:
    stable_ids = set(read_ids(stable_manifest))
    lane_reports: dict[str, dict[str, Any]] = {}
    route_union: set[str] = set()

    covered_key = f"covered_by_{label}_unique"
    missing_key = f"missing_from_{label}_unique"
    remaining_missing_key = f"remaining_missing_from_{label}_unique"

    for lane in LANES:
        all_ids = read_ids(route_root / f"{lane}.all.jsonl")
        remaining_ids = read_ids(route_root / f"{lane}.remaining.jsonl")
        all_set = set(all_ids)
        remaining_set = set(remaining_ids)
        route_union |= all_set

        missing = sorted(all_set - stable_ids)
        remaining_missing = sorted(remaining_set - stable_ids)
        lane_reports[lane] = {
            "all_rows": len(all_ids),
            "all_unique": len(all_set),
            "remaining_rows": len(remaining_ids),
            "remaining_unique": len(remaining_set),
            covered_key: len(all_set & stable_ids),
            missing_key: len(missing),
            remaining_missing_key: len(remaining_missing),
            "sample_missing": missing[:20],
        }

    return {
        "schema_version": f"stage7_{label}_deepseek_stable_coverage_vs_fixed_routes.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stable_manifest": str(stable_manifest),
        "route_root": str(route_root),
        "stable_unique": len(stable_ids),
        "lanes": lane_reports,
        "totals": {
            "fixed_route_all_unique": len(route_union),
            f"fixed_route_covered_by_{label}_unique": len(route_union & stable_ids),
            f"fixed_route_missing_from_{label}_unique": len(route_union - stable_ids),
        },
        "writes": "coverage JSON only; no API/vector/DB/graph/source archive writes",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-root", required=True)
    parser.add_argument("--stable-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    report = build_report(
        route_root=Path(args.route_root),
        stable_manifest=Path(args.stable_manifest),
        label=args.label,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    compact = {
        "schema_version": report["schema_version"],
        "stable_unique": report["stable_unique"],
        "totals": report["totals"],
        "lanes": {
            lane: {
                key: value
                for key, value in lane_report.items()
                if key.endswith("_unique") or key in {"all_unique", "remaining_unique"}
            }
            for lane, lane_report in report["lanes"].items()
        },
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
