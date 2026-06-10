"""Generate a production-writer design from a green Stage8 vector gate.

This is a design artifact generator, not a production writer. It reads a gate
dry-run/canary directory and writes a production-writer contract that preserves
the tiered vector strategy, resume keys, rollback order, and store naming.
It does not embed, write Qdrant, write Neo4j, or touch production databases.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stage8_vector_rollback_resume_report as rollback_reporter
from stage7.atomic_io import safe_read_json


PRODUCTION_CONFIRM_TOKEN = "ENABLE_PRODUCTION_VECTOR_WRITE_93K"


def safe_name(value: Any) -> str:
    text = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "")).strip("_").lower()
    return text or "unknown"


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def model_slug(model: str) -> str:
    return safe_name(model).replace("_large_zh_v2", "_large_zh_v2")


def collection_names(plan: dict[str, Any], release_id: str) -> dict[str, Any]:
    model = model_slug(str(plan.get("model") or "unknown_model"))
    dim = str(plan.get("dim") or "unknown_dim")
    kinds = sorted((plan.get("job_kind_counts") or {}).keys()) or ["article"]
    split = {
        kind: f"wechat_prod_{safe_name(kind)}_{model}_{dim}_{safe_name(release_id)}_staging"
        for kind in kinds
    }
    return {
        "split_by_kind": split,
        "unified_optional": f"wechat_prod_unified_{model}_{dim}_{safe_name(release_id)}_staging",
        "alias_prefix": f"wechat_prod_{model}_{dim}",
    }


def route_contract(plan: dict[str, Any]) -> dict[str, Any]:
    card_template = str(plan.get("card_template") or "")
    candidate_cap = plan.get("candidate_cap")
    score_profile = str(plan.get("score_profile") or "")
    tier_counts = plan.get("tier_counts") or {}
    return {
        "this_gate_route": {
            "card_template": card_template,
            "candidate_cap": candidate_cap,
            "score_profile": score_profile,
            "tier_counts": tier_counts,
        },
        "global_tiered_policy": [
            {
                "scenario": "ocr_present_or_broad_ocr_rich",
                "strategy": "research_v1 + cap20 + adaptive_v3_source_guard",
                "note": "required when OCR evidence cards must be retrievable",
            },
            {
                "scenario": "strict_source_without_ocr_or_account",
                "strategy": "multi_card + cap25 + adaptive_v4_source_gate",
                "note": "source-sensitive read path with fewer jobs",
            },
            {
                "scenario": "strict_source_with_ocr_or_account",
                "strategy": "research_v1 + cap20 + adaptive_v4_source_gate",
                "note": "use when source gate and richer cards are both required",
            },
            {
                "scenario": "clean_qwen_account_event_clean_read_path",
                "strategy": "multi_card + cap5 + adaptive_v3_source_guard",
                "note": "current Qwen micro gate route",
            },
            {
                "scenario": "tier_d_platform_privacy_partial",
                "strategy": "no broad-map vector write",
                "note": "quarantine or repair before vector write",
            },
        ],
    }


def preflight_checks(plan: dict[str, Any], rollback: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "gate_canary_green",
            "required": True,
            "observed": bool(rollback.get("canary_green")),
            "source": "rollback_resume_report.canary_green",
        },
        {
            "name": "no_quarantine_in_this_gate",
            "required": True,
            "observed": int(plan.get("quarantined_articles") or 0) == 0,
            "source": "production_gate_plan.quarantined_articles",
        },
        {
            "name": "mac_endpoint_only",
            "required": True,
            "observed": "192.168.8.234" in str(plan.get("endpoint") or ""),
            "source": "production_gate_plan.endpoint",
        },
        {
            "name": "rollback_resume_report_exists",
            "required": True,
            "observed": bool(rollback),
            "source": "rollback_resume_report.json",
        },
        {
            "name": "manual_confirm_token_required",
            "required": True,
            "observed": False,
            "source": PRODUCTION_CONFIRM_TOKEN,
        },
    ]


def writer_phases(release_id: str, collections: dict[str, Any], rollback: dict[str, Any]) -> list[dict[str, Any]]:
    resume_key = (rollback.get("resume_policy") or {}).get("resume_key") or "object_kind + object_id + text_sha1"
    return [
        {
            "phase": "preflight",
            "writes": "none",
            "resume": "re-read gate plan, rollback report, endpoint route, and target collection manifest",
        },
        {
            "phase": "pc_ledger_claim",
            "writes": "pc sqlite production ledger only after explicit production enablement",
            "resume": f"claim rows by {resume_key}; never regenerate completed vector object claims",
        },
        {
            "phase": "mac_embedding_resume",
            "writes": "append-only embeddings artifact and ledger status",
            "resume": "skip existing text_sha1/object_kind/object_id rows; no PC-local model fallback",
        },
        {
            "phase": "qdrant_staging_upsert",
            "writes": collections["split_by_kind"],
            "resume": "idempotent point ids derived from object_kind/object_id/text_sha1",
        },
        {
            "phase": "qdrant_verify_then_alias",
            "writes": "alias swap only after self-hit/equivalent-hit checks pass",
            "resume": "if verification fails, delete staging collections listed in rollback manifest",
        },
        {
            "phase": "neo4j_chunked_stage",
            "writes": "WechatNode/WECHAT_REL only under a production run_id after explicit enablement",
            "resume": "batch node/edge writes and delete by run_id on rollback",
        },
        {
            "phase": "commit_manifest",
            "writes": f"release manifest for {release_id}",
            "resume": "final marker written only after all target stores verify green",
        },
    ]


def build_design(gate_dir: Path, release_id: str | None = None) -> dict[str, Any]:
    gate_dir = gate_dir.resolve()
    plan = safe_read_json(gate_dir / "production_gate_plan.json", {})
    if not isinstance(plan, dict):
        plan = {}
    rollback_path = gate_dir / "rollback_resume_report.json"
    rollback = safe_read_json(rollback_path, {})
    if not isinstance(rollback, dict) or not rollback:
        rollback = rollback_reporter.build_report(gate_dir)
    release = release_id or f"stage8_vector_{now_stamp()}"
    collections = collection_names(plan, release)
    checks = preflight_checks(plan, rollback)
    executable_writer = SCRIPT_DIR / "stage8_vector_production_writer.py"
    return {
        "schema_version": "stage8_vector_production_writer_design.v1",
        "design_only": True,
        "production_enabled": False,
        "production_writer_available": executable_writer.exists(),
        "production_writer_path": str(executable_writer),
        "confirm_token_required": PRODUCTION_CONFIRM_TOKEN,
        "release_id": release,
        "gate_dir": str(gate_dir),
        "gate_summary": {
            "mode": plan.get("mode"),
            "card_template": plan.get("card_template"),
            "candidate_cap": plan.get("candidate_cap"),
            "score_profile": plan.get("score_profile"),
            "model": plan.get("model"),
            "dim": plan.get("dim"),
            "endpoint": plan.get("endpoint"),
            "eligible_articles": plan.get("eligible_articles"),
            "quarantined_articles": plan.get("quarantined_articles"),
            "job_count": plan.get("job_count"),
            "tier_counts": plan.get("tier_counts") or {},
        },
        "route_contract": route_contract(plan),
        "collection_contract": collections,
        "preflight_checks": checks,
        "writer_phases": writer_phases(release, collections, rollback),
        "rollback_order": rollback.get("rollback_order") or [],
        "resume_policy": rollback.get("resume_policy") or {},
        "production_blockers": [
            "this file is a design artifact; execute stage8_vector_production_writer.py to write production targets",
            "manual production confirm token is absent",
        ],
    }


def write_markdown(design: dict[str, Any], out_md: Path) -> None:
    gate = design["gate_summary"]
    lines = [
        "# Stage8 Vector Production Writer Design",
        "",
        f"- design_only: `{design['design_only']}`",
        f"- production_enabled: `{design['production_enabled']}`",
        f"- production_writer_available: `{design.get('production_writer_available')}`",
        f"- production_writer_path: `{design.get('production_writer_path')}`",
        f"- release_id: `{design['release_id']}`",
        f"- gate_dir: `{design['gate_dir']}`",
        f"- route: `{gate.get('card_template')} cap{gate.get('candidate_cap')} {gate.get('score_profile')}`",
        f"- endpoint: `{gate.get('endpoint')}` / `{gate.get('model')}` / dim `{gate.get('dim')}`",
        f"- eligible/quarantine/jobs: `{gate.get('eligible_articles')}` / `{gate.get('quarantined_articles')}` / `{gate.get('job_count')}`",
        "",
        "## Preflight Checks",
        "",
    ]
    for item in design["preflight_checks"]:
        lines.append(
            f"- `{item['name']}` required `{item['required']}` observed `{item['observed']}` source `{item['source']}`"
        )
    lines.extend(["", "## Writer Phases", ""])
    for phase in design["writer_phases"]:
        lines.append(f"- `{phase['phase']}`: writes `{phase['writes']}`; resume `{phase['resume']}`")
    lines.extend(["", "## Collection Contract", ""])
    for kind, name in design["collection_contract"]["split_by_kind"].items():
        lines.append(f"- split `{kind}`: `{name}`")
    lines.append(f"- unified_optional: `{design['collection_contract']['unified_optional']}`")
    lines.extend(["", "## Tiered Routing Policy", ""])
    for item in design["route_contract"]["global_tiered_policy"]:
        lines.append(f"- `{item['scenario']}`: `{item['strategy']}`")
    lines.extend(["", "## Rollback Order", ""])
    for step in design["rollback_order"]:
        lines.append(f"- {step}")
    lines.extend(["", "## Production Blockers", ""])
    for blocker in design["production_blockers"]:
        lines.append(f"- {blocker}")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-dir", required=True)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--release-id", default="")
    args = parser.parse_args(argv)
    gate_dir = Path(args.gate_dir)
    out_dir = Path(args.out_dir) if args.out_dir else gate_dir / "production_writer_design"
    out_dir.mkdir(parents=True, exist_ok=True)
    design = build_design(gate_dir, args.release_id or None)
    out_json = out_dir / "production_writer_design.json"
    out_md = out_dir / "PRODUCTION_WRITER_DESIGN.md"
    out_json.write_text(json.dumps(design, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(design, out_md)
    print(json.dumps({"ok": True, "json": str(out_json), "markdown": str(out_md)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
