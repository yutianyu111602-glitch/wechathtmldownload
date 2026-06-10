#!/usr/bin/env python3
"""Export weekly_entity_observations.jsonl for atlas ingest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.weekly_atlas_bridge.observations import (  # noqa: E402
    export_observations,
    write_observations_jsonl,
)
from tools.stage7_rewrite.weekly_atlas_bridge.snapshot import (  # noqa: E402
    build_snapshot_from_paths,
    load_current_items,
)


DEFAULT_REGISTRY = REPO_ROOT / "tools/stage7_rewrite/registries/weekly_artists_seed.json"


def default_source_map_path(current_path: Path) -> Path | None:
    candidates = [
        current_path.parent / "source_actions" / "source_url_map.json",
        REPO_ROOT / "services/weekly_activity_cloudrun/data/source_actions/source_url_map.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_source_map(path: Path | None) -> dict | None:
    if not path:
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--alias-export", type=Path, default=None)
    parser.add_argument("--source-map", type=Path, default=None)
    parser.add_argument("--publish-package", default="")
    parser.add_argument("--window-start", default="")
    parser.add_argument("--window-end", default="")
    parser.add_argument("--enable-vector-review", action="store_true")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    args = parser.parse_args()

    qdrant_url = args.qdrant_url if args.enable_vector_review else None
    items = load_current_items(args.current)
    publish_package = args.publish_package or args.current.parent.name
    snapshot = build_snapshot_from_paths(
        args.current,
        args.registry,
        alias_export_path=args.alias_export,
        qdrant_url=qdrant_url,
        publish_package=publish_package,
    )
    window = {}
    if args.window_start:
        window["start"] = args.window_start
    if args.window_end:
        window["end"] = args.window_end
    source_map_path = args.source_map or default_source_map_path(args.current)
    source_url_map = load_source_map(source_map_path)
    rows = export_observations(
        items,
        publish_package=publish_package,
        window=window,
        lineup_resolved=snapshot.get("lineup_resolved") or [],
        source_url_map=source_url_map,
    )
    write_observations_jsonl(args.out, rows)
    source_hash_count = sum(1 for row in rows if row.get("source_url_hash"))
    print(json.dumps({
        "observations": len(rows),
        "source_url_hash": source_hash_count,
        "source_map": str(source_map_path) if source_map_path else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
