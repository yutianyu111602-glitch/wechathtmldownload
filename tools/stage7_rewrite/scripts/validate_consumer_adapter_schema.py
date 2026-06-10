"""Validate the Stage7 consumer adapter against the locked consumer schema.

This is a release gate, not a publisher. It reads small Qdrant samples from the
current local Qwen3 aliases, checks that they satisfy the minimum staging
adapter shape, and reports the remaining final-release schema gaps that must be
filled from stable extracts before badDJ/weekly publish.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from consumer_staging_adapter import DEFAULT_ALIASES, DEFAULT_QDRANT_URL  # noqa: E402


DEFAULT_OUT_DIR = Path("reports/consumer_schema_validation_20260514")
MINIMUM_REQUIRED = {
    "article": ["card_id", "card_type", "article_uid", "source_account", "title", "text", "text_sha1"],
    "entity": ["card_id", "card_type", "article_uid", "name", "entity_type", "text", "text_sha1"],
    "event": ["card_id", "card_type", "article_uid", "name", "text", "text_sha1"],
}
FINAL_REQUIRED_MAPPING = {
    "article": {
        "article_uid": "article_uid",
        "source_account": "source_account",
        "title": "title",
        "publish_time": None,
        "entity_count": None,
        "event_count": None,
        "extract_version": "const:V6",
        "vector_text": "text",
    },
    "entity": {
        "eid": "card_id",
        "name": "name",
        "type": "entity_type",
        "confidence": None,
        "source_article_uid": "article_uid",
        "source_kind": None,
        "vector_text": "text",
    },
    "event": {
        "evid": "card_id",
        "name": "name",
        "confidence": None,
        "source_article_uid": "article_uid",
        "source_kind": None,
        "vector_text": "text",
    },
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def require_local_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must be local for consumer schema validation: {url}")


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def validate_minimum_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    required = MINIMUM_REQUIRED[kind]
    missing = [field for field in required if not is_present(payload.get(field))]
    wrong_type = []
    if is_present(payload.get("card_type")) and payload.get("card_type") != kind:
        wrong_type.append({"field": "card_type", "expected": kind, "actual": payload.get("card_type")})
    return {
        "ok": not missing and not wrong_type,
        "required": required,
        "missing": missing,
        "wrong_type": wrong_type,
    }


def validate_final_schema_mapping(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    mapping = FINAL_REQUIRED_MAPPING[kind]
    missing_required = []
    mapped_fields: dict[str, str] = {}
    for final_field, source_field in mapping.items():
        if source_field is None:
            missing_required.append(final_field)
            continue
        if source_field.startswith("const:"):
            mapped_fields[final_field] = source_field
            continue
        if is_present(payload.get(source_field)):
            mapped_fields[final_field] = source_field
        else:
            missing_required.append(final_field)
    return {
        "release_ready": not missing_required,
        "mapped_fields": mapped_fields,
        "missing_required": missing_required,
    }


def qdrant_scroll_samples(qdrant_url: str, aliases: dict[str, str], sample_per_kind: int) -> dict[str, list[dict[str, Any]]]:
    require_local_url(qdrant_url, "Qdrant URL")
    samples: dict[str, list[dict[str, Any]]] = {}
    for kind, alias in aliases.items():
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(alias)}/points/scroll",
            json={"limit": sample_per_kind, "with_payload": True, "with_vector": False},
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Qdrant scroll failed for {kind} {response.status_code}: {response.text[:500]}")
        points = ((response.json().get("result") or {}).get("points") or [])
        samples[kind] = [point.get("payload") or {} for point in points]
    return samples


def build_report(samples: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    per_kind: dict[str, Any] = {}
    release_blockers: list[str] = []
    minimum_ok = True
    release_ready = True
    for kind in ("article", "entity", "event"):
        rows = samples.get(kind) or []
        minimum_results = [validate_minimum_payload(kind, row) for row in rows]
        final_results = [validate_final_schema_mapping(kind, row) for row in rows]
        kind_minimum_ok = bool(rows) and all(item["ok"] for item in minimum_results)
        kind_release_ready = bool(rows) and all(item["release_ready"] for item in final_results)
        minimum_ok = minimum_ok and kind_minimum_ok
        release_ready = release_ready and kind_release_ready
        missing_counts: dict[str, int] = {}
        for result in final_results:
            for field in result["missing_required"]:
                missing_counts[field] = missing_counts.get(field, 0) + 1
        for field in missing_counts:
            release_blockers.append(f"{kind}.{field}")
        per_kind[kind] = {
            "sample_count": len(rows),
            "minimum_ok": kind_minimum_ok,
            "release_ready": kind_release_ready,
            "minimum_failures": [item for item in minimum_results if not item["ok"]],
            "final_missing_required_counts": missing_counts,
            "final_mapping": FINAL_REQUIRED_MAPPING[kind],
        }
    return {
        "schema_version": "stage7_consumer_schema_validation.v1",
        "generated_at": now_iso(),
        "ok": minimum_ok,
        "release_ready": release_ready,
        "release_blockers": sorted(set(release_blockers)),
        "per_kind": per_kind,
        "decision": "release_pack_mapping_required" if minimum_ok and not release_ready else "ready_for_release_pack",
        "writes": "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Consumer Schema Validation",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- release_ready: `{report['release_ready']}`",
        f"- decision: `{report['decision']}`",
        "",
        "## Per Kind",
        "",
    ]
    for kind, item in report["per_kind"].items():
        lines.extend(
            [
                f"### {kind}",
                "",
                f"- sample_count: `{item['sample_count']}`",
                f"- minimum_ok: `{item['minimum_ok']}`",
                f"- release_ready: `{item['release_ready']}`",
                f"- missing_required_counts: `{json.dumps(item['final_missing_required_counts'], ensure_ascii=False)}`",
                "",
            ]
        )
    lines.extend(["## Release Blockers", ""])
    if report["release_blockers"]:
        for blocker in report["release_blockers"]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Current Qdrant card payload is sufficient for staging retrieval adapter smoke.",
            "- It is not yet a final badDJ/weekly release payload.",
            "- The next step is a release-pack mapper that joins stable extracts/source metadata to fill required fields.",
            "- This script writes reports only; it does not publish, write DBs, call paid APIs, or scan D:.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    samples = qdrant_scroll_samples(args.qdrant_url, dict(DEFAULT_ALIASES), args.sample_per_kind)
    report = build_report(samples)
    report["qdrant_url"] = args.qdrant_url
    report["aliases"] = dict(DEFAULT_ALIASES)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "consumer_schema_validation.json", report)
    write_markdown(args.out_dir / "consumer_schema_validation.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "release_ready": report["release_ready"],
                "decision": report["decision"],
                "report": str(args.out_dir / "consumer_schema_validation.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.strict_release and not report["release_ready"]:
        return 2
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--sample-per-kind", type=int, default=5)
    parser.add_argument("--strict-release", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
