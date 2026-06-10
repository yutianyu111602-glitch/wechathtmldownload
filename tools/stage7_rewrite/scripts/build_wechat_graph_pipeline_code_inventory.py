from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StageDef:
    stage_id: int
    name: str
    purpose: str
    code_paths: tuple[str, ...]
    package_scripts: tuple[str, ...] = ()
    stage_script_keywords: tuple[str, ...] = ()
    evidence_rule: str = ""


STAGES: tuple[StageDef, ...] = (
    StageDef(
        0,
        "source_registry_url_discovery",
        "Build bounded article/account queues.",
        ("src/accounts", "src/api", "src/historyCli.ts"),
        ("prefetch-account-urls", "fetch-history-urls"),
        ("account", "history", "prefetch"),
        "Queue/discovery counts are not complete article-body counts.",
    ),
    StageDef(
        1,
        "archive_mptext_assets_dajiala",
        "Capture local archive bundles and retained media evidence.",
        ("src/archive", "src/dajiala", "src/mptext"),
        (
            "archive-article",
            "archive-batch",
            "mptext-archive-batch",
            "dajiala-repair-archive-batch",
            "filter-dajiala-repair-candidates",
            "extract-incomplete-archive-queue",
            "download-archive-assets",
            "download-archive-assets-batch",
            "audit-archive-run",
        ),
        ("dajiala", "archive", "asset", "mptext"),
        "Paid recapture needs a fresh ROI/yield gate and must not blindly retry old waves.",
    ),
    StageDef(
        2,
        "html_asset_normalization_ocr_markdown",
        "Normalize HTML/assets, run language-routed OCR, and build Markdown/MarkItDown evidence.",
        ("src/extract", "src/pipeline", "src/poster"),
        ("process-batch", "process-dual-track", "export-markitdown-batch", "ocr-poster-batch"),
        ("ocr", "markitdown", "poster", "v6_p1", "asset"),
        "Image/GIF evidence must become OCR text with provenance before DeepSeek text extraction.",
    ),
    StageDef(
        3,
        "llm_export_text_extraction",
        "Package LLM-ready text and materialize stable text extraction outputs.",
        ("src/artifacts", "src/llm", "src/packs"),
        ("export-llm-batch", "finalize-llm-pack", "run-downstream-llm", "run-downstream-llm-batch"),
        ("deepseek", "flash", "llm", "materialize", "parallel_flash"),
        "DeepSeek Flash/Pro is text-only; no image claims without OCR-to-Markdown evidence.",
    ),
    StageDef(
        4,
        "stage7_structured_extraction",
        "Convert text artifacts into stable article/entity/event structures.",
        ("tools/stage7_rewrite/stage7", "tools/stage7_rewrite/schemas"),
        (),
        ("stage7", "stable", "merge", "full93k", "quality", "gap_ledger"),
        "Stage7 is one large production stage, not the whole electronic-music atlas pipeline.",
    ),
    StageDef(
        5,
        "graph_candidate_pack_marker",
        "Build reviewable graph data, Neo4j staging, and verified graph production markers.",
        ("src/graph", "src/ignuke"),
        (),
        ("graph", "neo4j", "promote", "candidate", "collaboration", "readiness"),
        "Graph truth requires runner evidence; candidate evidence is not identity proof.",
    ),
    StageDef(
        6,
        "text_vector_retrieval_lanes",
        "Build 1024-d model-isolated retrieval lanes without mixing vector spaces.",
        ("tools/stage7_rewrite/stage8", "tools/stage7_rewrite/queries"),
        (),
        ("vector", "qdrant", "embed", "semantic", "router", "alias"),
        "Current route is BGE-M3/Snowflake/BGE-large-en role isolation; Qwen3 is control evidence only.",
    ),
    StageDef(
        7,
        "external_network_social_evidence",
        "Find public corroborating evidence for entities, handles, profiles, venues, and URLs.",
        ("src/ignuke", "tools/stage7_rewrite/registries"),
        (),
        ("external", "opencli", "maigret", "social", "public", "linktree", "soundcloud", "bandcamp"),
        "Public search/profile candidates stay report-only until normalized evidence and review accept them.",
    ),
    StageDef(
        8,
        "research_qa_orchestration",
        "Audit contradictions and coordinate gated runs around existing scripts.",
        ("tools/stage7_rewrite/prefect", "tools/stage7_rewrite/scripts"),
        (),
        ("audit", "verify", "prefect", "handoff", "smoke", "canary", "reconcile"),
        "LDR/Prefect are helpers, not truth sources or authority bypasses.",
    ),
    StageDef(
        9,
        "downstream_consumers",
        "Expose graph/event outputs after source-grounded gates.",
        ("services/weekly_activity_cloudrun", "apps/weekly_activity_miniprogram", "desktop"),
        ("weekly-api:start", "weekly-api:test", "start:gui"),
        ("weekly", "recommend", "rag", "consumer", "cloudrun", "miniprogram"),
        "Weekly/miniprogram is downstream consumer evidence unless explicitly routed.",
    ),
)


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def load_package_scripts(project_root: Path) -> dict[str, str]:
    package_path = project_root / "package.json"
    if not package_path.exists():
        return {}
    package = json.loads(package_path.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    return {str(k): str(v) for k, v in scripts.items()}


def list_stage_scripts(project_root: Path) -> list[str]:
    scripts_root = project_root / "tools" / "stage7_rewrite" / "scripts"
    if not scripts_root.exists():
        return []
    return sorted(
        rel(path, project_root)
        for path in scripts_root.glob("*.py")
        if path.is_file()
    )


def keyword_match(script_path: str, keywords: tuple[str, ...]) -> bool:
    name = Path(script_path).name.lower()
    return any(keyword.lower() in name for keyword in keywords)


def build_inventory(project_root: Path, out_dir: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    package_scripts = load_package_scripts(project_root)
    stage_scripts = list_stage_scripts(project_root)
    stages: list[dict[str, Any]] = []

    for stage in STAGES:
        code_paths = []
        for raw_path in stage.code_paths:
            abs_path = project_root / raw_path
            code_paths.append(
                {
                    "path": raw_path,
                    "exists": abs_path.exists(),
                    "kind": "dir" if abs_path.is_dir() else "file" if abs_path.is_file() else "missing",
                }
            )

        script_rows = [
            script_path
            for script_path in stage_scripts
            if keyword_match(script_path, stage.stage_script_keywords)
        ]
        package_rows = [
            {"name": name, "command": package_scripts[name]}
            for name in stage.package_scripts
            if name in package_scripts
        ]

        stages.append(
            {
                "stage_id": stage.stage_id,
                "name": stage.name,
                "purpose": stage.purpose,
                "code_paths": code_paths,
                "package_scripts": package_rows,
                "missing_package_scripts": [name for name in stage.package_scripts if name not in package_scripts],
                "stage_scripts": script_rows,
                "stage_script_count": len(script_rows),
                "evidence_rule": stage.evidence_rule,
            }
        )

    inventory = {
        "schema_version": "wechat_graph_pipeline_code_inventory.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "package_name": "wechat-ingest",
        "stage_count": len(stages),
        "stages": stages,
        "safety": {
            "d_scan_executed": False,
            "docs_only": True,
            "model_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
        },
    }

    (out_dir / "pipeline_code_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "pipeline_code_inventory.md").write_text(render_markdown(inventory), encoding="utf-8")
    return inventory


def render_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# WeChat Electronic Music Atlas / Graph Pipeline Code Inventory",
        "",
        f"Generated: `{inventory['generated_at']}`",
        "",
        "This report is derived from existing code paths and package/script entrypoints. It is a routing aid for **中国地下电子音乐图鉴**; graph/vector/network components are the atlas data and retrieval substrate, not the final product boundary by themselves.",
        "",
        "| Stage | Name | Existing code paths | Package scripts | Stage scripts | Evidence rule |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for stage in inventory["stages"]:
        existing_paths = sum(1 for item in stage["code_paths"] if item["exists"])
        package_count = len(stage["package_scripts"])
        lines.append(
            "| {stage_id} | `{name}` | {existing_paths}/{path_count} | {package_count} | {stage_script_count} | {rule} |".format(
                stage_id=stage["stage_id"],
                name=stage["name"],
                existing_paths=existing_paths,
                path_count=len(stage["code_paths"]),
                package_count=package_count,
                stage_script_count=stage["stage_script_count"],
                rule=stage["evidence_rule"].replace("|", "\\|"),
            )
        )

    lines.extend(["", "## Stage Details", ""])
    for stage in inventory["stages"]:
        lines.append(f"### Stage {stage['stage_id']} - {stage['name']}")
        lines.append("")
        lines.append(stage["purpose"])
        lines.append("")
        lines.append("Code paths:")
        for item in stage["code_paths"]:
            marker = "exists" if item["exists"] else "missing"
            lines.append(f"- `{item['path']}` - {marker} ({item['kind']})")
        if stage["package_scripts"]:
            lines.append("")
            lines.append("Package scripts:")
            for item in stage["package_scripts"]:
                lines.append(f"- `{item['name']}` -> `{item['command']}`")
        if stage["stage_scripts"]:
            lines.append("")
            lines.append("Representative Stage7/stage scripts:")
            for script_path in stage["stage_scripts"][:30]:
                lines.append(f"- `{script_path}`")
            if len(stage["stage_scripts"]) > 30:
                lines.append(f"- ... {len(stage['stage_scripts']) - 30} more")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=project_root_from_script())
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=project_root_from_script()
        / "reports"
        / "wechat_graph_pipeline_code_inventory_20260518",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inventory = build_inventory(args.project_root, args.out_dir)
    print(
        json.dumps(
            {
                "decision": "wechat_graph_pipeline_code_inventory_ready",
                "stage_count": inventory["stage_count"],
                "report": str(args.out_dir / "pipeline_code_inventory.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
