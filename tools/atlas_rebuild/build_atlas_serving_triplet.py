#!/usr/bin/env python3
"""Build one immutable, externally staged ATLAS serving triplet.

The command emits the mini-program static star map plus the CloudRun index and
neighborhood bundles under one snapshot-derived public ``datasetId``.  It never writes
repository data directories, never changes a serving pointer, and has no deploy
mode.  Generation happens in a sibling temporary directory; the requested
candidate directory appears only after every artifact passes the triplet gate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from atlas_dataset_identity import file_sha256, validate_dataset_id
from build_neighbor_bundle_from_miniapp import build_bundle as build_neighborhood
from export_mp_starmap_bundle import build as build_starmap
from export_mp_starmap_from_miniapp import build as build_starmap_from_miniapp
from export_v2_miniapp_index import export_index


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1].resolve()
STAGE7_SCRIPTS = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(STAGE7_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STAGE7_SCRIPTS))

from export_atlas_core_to_miniapp_index import export_index as export_index_from_miniapp  # noqa: E402
from weekly_public_projection import local_path_reason  # noqa: E402

STATIC_JSON = "atlas_starmap.json"
STATIC_JS = "atlas_starmap.js"
INDEX_GZ = "atlas_index.json.gz"
INDEX_MANIFEST = "atlas_index.json.gz.manifest.json"
NEIGHBORHOOD_GZ = "atlas_neighborhood.json.gz"
TRIPLET_MANIFEST = "atlas_triplet_manifest.json"
PRIMARY_ARTIFACTS = (STATIC_JSON, STATIC_JS, INDEX_GZ, NEIGHBORHOOD_GZ)
GENERATED_ARTIFACTS = (*PRIMARY_ARTIFACTS, INDEX_MANIFEST)
SQLITE_INPUT_ROLES = frozenset({"miniapp", "v2", "serving", "bioServing"})
UPSTREAM_GENERATION_MARKER_KEYS = (
    "upstream_generation_id",
    "source_generation_id",
    "generation_id",
    "release_id",
    "dataset_id",
    "build_id",
)
UPSTREAM_GENERATION_MARKER_TABLES = ("build_metadata", "metadata")
BUILDER_FILES = {
    "tripletOrchestrator": Path(__file__).resolve(),
    "miniappStarmapExporter": HERE / "export_mp_starmap_from_miniapp.py",
    "v2StarmapExporter": HERE / "export_mp_starmap_bundle.py",
    "miniappIndexExporter": STAGE7_SCRIPTS / "export_atlas_core_to_miniapp_index.py",
    "v2IndexExporter": HERE / "export_v2_miniapp_index.py",
    "miniappNeighborhoodBridge": HERE / "build_neighbor_bundle_from_miniapp.py",
    "neighborhoodExporter": HERE / "export_miniapp_neighborhood_bundle.py",
    "v2ReadmodelBuilder": HERE / "build_v2_serving_readmodel.py",
    "datasetIdentity": HERE / "atlas_dataset_identity.py",
}
V2_SCHEMA = {
    "subject": {
        "subject_id", "subject_type", "display_name", "normalized_name",
        "aliases_json", "city_primary", "event_count", "relation_count",
        "source_count", "first_seen_at", "last_seen_at",
    },
    "relation": {"src_subject_id", "dst_subject_id", "relation_type", "weight"},
    "dj_profile": {"subject_id", "social_json", "bio_snippet", "venue_count"},
}
SERVING_SCHEMA = {
    "evidence_ref": {
        "source_ref_id", "source_hash", "source_account", "source_title",
        "post_date", "source_kind",
    },
    "dj_event": {
        "dj_id", "event_id", "starts_at", "event_title", "venue_id",
        "venue_name", "city", "source_ref_id",
    },
    "dj_venue_rollup": {"dj_id", "venue_id", "venue_name", "city", "event_count"},
    "dj_relation_rollup": {
        "src_dj_id", "dst_dj_id", "same_event_count", "relation_score",
    },
}
MINIAPP_SCHEMA = {
    "subject": {
        "subject_id", "subject_type", "display_name", "normalized_name",
        "aliases_json", "city_primary", "event_count", "relation_count",
    },
    "dj_profile": {
        "dj_id", "display_name", "normalized_name", "aliases_json",
        "city_primary", "event_count", "venue_count", "collaborator_count",
        "first_seen_at", "last_seen_at", "bio", "bio_source",
    },
    "dj_event": {
        "dj_id", "event_id", "starts_at", "event_title", "venue_id",
        "venue_name", "city", "source_ref_id",
    },
    "dj_collaborator": {
        "src_dj_id", "dst_dj_id", "relation_label_zh", "relation_score",
    },
    "dj_venue": {"dj_id", "venue_id", "event_count"},
    "source_ref": {
        "source_ref_id", "source_hash", "source_account", "source_title",
        "post_date", "source_kind",
    },
}
class TripletValidationError(ValueError):
    """The generated artifacts cannot be released as one coherent dataset."""


def _is_within(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def validate_external_output_dir(path: Path) -> Path:
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise ValueError("out-dir must be an absolute caller-selected external path")
    selected = raw.resolve(strict=False)
    if _is_within(selected, REPO_ROOT):
        raise ValueError("out-dir must be outside the repository and its production data directories")
    for ancestor in (selected.parent, *selected.parents):
        if (ancestor / ".git").exists():
            raise ValueError("out-dir must be outside every Git worktree")
    folded_parts = [part.casefold() for part in selected.parts]
    if any(
        folded_parts[index] == "weekly_activity_cloudrun"
        and folded_parts[index + 1] == "data"
        for index in range(len(folded_parts) - 1)
    ):
        raise ValueError("out-dir must not target a weekly_activity_cloudrun runtime data directory")
    if any(part.casefold() == "current_release" for part in selected.parts):
        raise ValueError("out-dir must not target a current_release directory")
    if selected.exists():
        raise FileExistsError(f"out-dir must not already exist: {selected}")
    return selected


def _require_file(path: Path, label: str) -> Path:
    selected = Path(path).expanduser().resolve(strict=False)
    if not selected.is_file():
        raise FileNotFoundError(f"{label} not found: {selected}")
    return selected


def _connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _validate_sqlite_role(
    con: sqlite3.Connection,
    role: str,
    contract: dict[str, set[str]],
) -> dict[str, Any]:
    tables = {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing_tables = sorted(set(contract) - tables)
    if missing_tables:
        raise TripletValidationError(
            f"{role} database missing required table(s): {', '.join(missing_tables)}"
        )
    counts: dict[str, int] = {}
    for table, required_columns in contract.items():
        columns = {
            str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')
        }
        missing_columns = sorted(required_columns - columns)
        if missing_columns:
            raise TripletValidationError(
                f"{role}.{table} missing required column(s): "
                + ", ".join(missing_columns)
            )
        counts[table] = int(
            con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        )
    return {"tables": counts}


def _column_values(
    con: sqlite3.Connection,
    queries: Iterable[str],
) -> set[str]:
    values: set[str] = set()
    for query in queries:
        for row in con.execute(query):
            for value in row:
                text = str(value or "").strip()
                if text:
                    values.add(text)
    return values


def _raise_identity_drift(label: str, unknown: set[str]) -> None:
    if not unknown:
        return
    sample = ", ".join(sorted(unknown)[:5])
    raise TripletValidationError(
        f"{label}: count={len(unknown)} sample={sample}"
    )


def preflight_inputs(*, v2: Path, serving: Path, miniapp_db: Path) -> dict[str, Any]:
    """Prove schema and subject-identity compatibility without writing anything."""
    selected_v2 = _require_file(v2, "v2 database")
    selected_serving = _require_file(serving, "serving database")
    selected_miniapp = _require_file(miniapp_db, "miniapp database")
    v2_con = _connect_ro(selected_v2)
    serving_con = _connect_ro(selected_serving)
    mini_con = _connect_ro(selected_miniapp)
    try:
        roles = {
            "v2": _validate_sqlite_role(v2_con, "v2", V2_SCHEMA),
            "serving": _validate_sqlite_role(serving_con, "serving", SERVING_SCHEMA),
            "miniapp": _validate_sqlite_role(mini_con, "miniapp", MINIAPP_SCHEMA),
        }
        v2_ids = _column_values(v2_con, ["SELECT subject_id FROM subject"])
        mini_ids = _column_values(mini_con, ["SELECT subject_id FROM subject"])
        if v2_ids != mini_ids:
            raise TripletValidationError(
                "v2/miniapp subject identity mismatch: "
                f"v2={len(v2_ids)} miniapp={len(mini_ids)} "
                f"intersection={len(v2_ids & mini_ids)} "
                f"v2_only={len(v2_ids - mini_ids)} miniapp_only={len(mini_ids - v2_ids)}"
            )

        v2_relation_ids = _column_values(
            v2_con,
            ["SELECT src_subject_id, dst_subject_id FROM relation"],
        )
        _raise_identity_drift(
            "v2 relation references unknown subject ids",
            v2_relation_ids - v2_ids,
        )
        mini_reference_ids = _column_values(
            mini_con,
            [
                "SELECT src_dj_id, dst_dj_id FROM dj_collaborator",
                "SELECT dj_id, venue_id FROM dj_venue",
            ],
        )
        _raise_identity_drift(
            "miniapp relations reference unknown subject ids",
            mini_reference_ids - mini_ids,
        )
        serving_reference_ids = _column_values(
            serving_con,
            [
                "SELECT dj_id, venue_id FROM dj_event",
                "SELECT dj_id, venue_id FROM dj_venue_rollup",
                "SELECT src_dj_id, dst_dj_id FROM dj_relation_rollup",
            ],
        )
        serving_unknown = serving_reference_ids - v2_ids
        _raise_identity_drift(
            "serving read model references subjects absent from v2",
            serving_unknown,
        )
        return {
            "decision": "atlas_serving_triplet_inputs_compatible",
            "roles": roles,
            "identity": {
                "v2SubjectCount": len(v2_ids),
                "miniappSubjectCount": len(mini_ids),
                "subjectIntersectionCount": len(v2_ids & mini_ids),
                "v2RelationReferencedSubjectCount": len(v2_relation_ids),
                "miniappReferencedSubjectCount": len(mini_reference_ids),
                "servingReferencedSubjectCount": len(serving_reference_ids),
                "v2RelationUnknownSubjectCount": 0,
                "miniappUnknownSubjectCount": 0,
                "servingUnknownSubjectCount": len(serving_unknown),
            },
        }
    finally:
        v2_con.close()
        serving_con.close()
        mini_con.close()


def preflight_miniapp_input(*, miniapp_db: Path) -> dict[str, Any]:
    """Validate the current single-source miniapp serving generation."""
    selected_miniapp = _require_file(miniapp_db, "miniapp database")
    con = _connect_ro(selected_miniapp)
    try:
        role = _validate_sqlite_role(con, "miniapp", MINIAPP_SCHEMA)
        subject_ids = _column_values(con, ["SELECT subject_id FROM subject"])
        profile_ids = _column_values(con, ["SELECT dj_id FROM dj_profile"])
        graph_reference_ids = _column_values(
            con,
            [
                "SELECT src_dj_id, dst_dj_id FROM dj_collaborator",
                "SELECT dj_id, venue_id FROM dj_venue",
            ],
        )
        event_dj_ids = _column_values(con, ["SELECT dj_id FROM dj_event"])
        _raise_identity_drift(
            "miniapp profiles reference unknown subject ids",
            profile_ids - subject_ids,
        )
        _raise_identity_drift(
            "miniapp graph references unknown subject ids",
            graph_reference_ids - subject_ids,
        )
        _raise_identity_drift(
            "miniapp events reference unknown DJ subject ids",
            event_dj_ids - subject_ids,
        )
        known_source_refs = _column_values(
            con,
            ["SELECT source_ref_id FROM source_ref"],
        )
        event_source_refs = _column_values(
            con,
            ["SELECT source_ref_id FROM dj_event WHERE COALESCE(source_ref_id,'')<>''"],
        )
        _raise_identity_drift(
            "miniapp events reference unknown source_ref ids",
            event_source_refs - known_source_refs,
        )
        event_venue_ids = _column_values(
            con,
            ["SELECT venue_id FROM dj_event WHERE COALESCE(venue_id,'')<>''"],
        )
        return {
            "decision": "atlas_serving_triplet_miniapp_input_compatible",
            "roles": {"miniapp": role},
            "identity": {
                "miniappSubjectCount": len(subject_ids),
                "profileSubjectCount": len(profile_ids),
                "graphReferencedSubjectCount": len(graph_reference_ids),
                "eventDjSubjectCount": len(event_dj_ids),
                "graphUnknownSubjectCount": 0,
                "eventUnknownDjSubjectCount": 0,
                "eventUnknownSourceRefCount": 0,
                # Legacy venue aliases can appear in historical event rows but
                # are not graph endpoints; preserve and report rather than
                # silently pretending they are canonical subjects.
                "eventVenueOutsideSubjectCount": len(event_venue_ids - subject_ids),
            },
        }
    finally:
        con.close()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TripletValidationError(f"invalid JSON artifact {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise TripletValidationError(f"artifact root must be an object: {path.name}")
    return value


def _read_gzip_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TripletValidationError(f"invalid gzip JSON artifact {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise TripletValidationError(f"artifact root must be an object: {path.name}")
    return value


def _read_static_js(path: Path) -> dict[str, Any]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TripletValidationError(f"invalid static JS artifact {path.name}: {exc}") from exc
    prefix = "module.exports = "
    stripped = source.strip()
    if not stripped.startswith(prefix) or not stripped.endswith(";"):
        raise TripletValidationError(f"invalid CommonJS wrapper: {path.name}")
    try:
        value = json.loads(stripped[len(prefix) : -1])
    except json.JSONDecodeError as exc:
        raise TripletValidationError(f"invalid CommonJS payload {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise TripletValidationError(f"static JS payload root must be an object: {path.name}")
    return value


def _walk_strings(value: Any, key_path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield key_path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield f"{key_path}.<key>", str(key)
            yield from _walk_strings(item, f"{key_path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{key_path}[{index}]")


def _path_markers(paths: Iterable[Path]) -> set[str]:
    markers: set[str] = set()
    for path in paths:
        text = str(Path(path).resolve(strict=False)).strip()
        if len(text) < 4:
            continue
        markers.update({text.casefold(), text.replace("\\", "/").casefold()})
    return markers


def find_local_path_leaks(
    named_payloads: dict[str, dict[str, Any]],
    forbidden_paths: Iterable[Path] = (),
) -> list[dict[str, str]]:
    markers = _path_markers(forbidden_paths)
    findings: list[dict[str, str]] = []
    for artifact, payload in named_payloads.items():
        for key_path, value in _walk_strings(payload):
            folded = value.casefold()
            normalized = value.replace("\\", "/").casefold()
            marker = next(
                (item for item in markers if item in folded or item in normalized),
                "",
            )
            path_reason = local_path_reason(value)
            if marker or path_reason:
                findings.append(
                    {
                        "artifact": artifact,
                        "field": key_path,
                        "reason": "known_local_path" if marker else path_reason,
                    }
                )
    return findings


def _require_dict_list(payload: dict[str, Any], key: str, artifact: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TripletValidationError(f"{artifact} requires an object array at {key}")
    return value


def verify_triplet(
    candidate_dir: Path,
    expected_dataset_id: str,
    *,
    forbidden_paths: Iterable[Path] = (),
    require_manifest: bool = False,
) -> dict[str, Any]:
    root = Path(candidate_dir)
    expected_id = validate_dataset_id(expected_dataset_id)
    for name in PRIMARY_ARTIFACTS:
        if not (root / name).is_file():
            raise TripletValidationError(f"missing artifact: {name}")

    static_payload = _read_json(root / STATIC_JSON)
    static_js_payload = _read_static_js(root / STATIC_JS)
    index_payload = _read_gzip_json(root / INDEX_GZ)
    neighborhood_payload = _read_gzip_json(root / NEIGHBORHOOD_GZ)
    if static_payload != static_js_payload:
        raise TripletValidationError("static JSON/CommonJS payload mismatch")

    named_payloads = {
        STATIC_JSON: static_payload,
        STATIC_JS: static_js_payload,
        INDEX_GZ: index_payload,
        NEIGHBORHOOD_GZ: neighborhood_payload,
    }
    if (root / INDEX_MANIFEST).is_file():
        named_payloads[INDEX_MANIFEST] = _read_json(root / INDEX_MANIFEST)

    identities = {
        name: str(payload.get("datasetId") or "").strip()
        for name, payload in named_payloads.items()
    }
    mismatched = {
        name: value for name, value in identities.items() if value != expected_id
    }
    if mismatched:
        detail = ", ".join(f"{name}={value or '<missing>'}" for name, value in sorted(mismatched.items()))
        raise TripletValidationError(
            f"datasetId mismatch; expected {expected_id}: {detail}"
        )

    if static_payload.get("schemaVersion") != "atlas.mp.starmap.v2":
        raise TripletValidationError("unsupported static star-map schemaVersion")
    if neighborhood_payload.get("schemaVersion") != "atlas.miniapp.neighborhood_bundle.v1":
        raise TripletValidationError("unsupported neighborhood schemaVersion")
    if not isinstance(index_payload.get("v"), int) or int(index_payload["v"]) < 5:
        raise TripletValidationError("atlas_index requires schema v5 or newer")

    static_nodes = _require_dict_list(static_payload, "nodes", STATIC_JSON)
    static_edges = static_payload.get("edges")
    if not isinstance(static_edges, list):
        raise TripletValidationError(f"{STATIC_JSON} requires an edges array")
    if not static_nodes:
        raise TripletValidationError("static star map contains no nodes")
    static_counts = static_payload.get("counts")
    if not isinstance(static_counts, dict) or static_counts.get("nodes") != len(static_nodes) or static_counts.get("edges") != len(static_edges):
        raise TripletValidationError("static star-map counts do not match its payload")

    index_subjects = _require_dict_list(index_payload, "subjects", INDEX_GZ)
    index_ids = [str(item.get("i") or "").strip() for item in index_subjects]
    if not index_ids or any(not item for item in index_ids):
        raise TripletValidationError("atlas_index contains no subjects or an empty subject id")
    if len(index_ids) != len(set(index_ids)):
        raise TripletValidationError("atlas_index contains duplicate subject ids")
    index_id_set = set(index_ids)

    static_ids = {str(item.get("u") or "").strip() for item in static_nodes}
    if "" in static_ids:
        raise TripletValidationError("static star map contains an empty subject id")
    static_unknown = sorted(static_ids - index_id_set)
    if static_unknown:
        raise TripletValidationError(
            "static star map references subjects absent from atlas_index: "
            + ", ".join(static_unknown[:5])
        )

    by_node = neighborhood_payload.get("byNode")
    if not isinstance(by_node, dict) or not by_node:
        raise TripletValidationError("neighborhood bundle contains no byNode entries")
    neighborhood_ids: set[str] = set()
    emitted_edges = 0
    for subject_id, rows in by_node.items():
        sid = str(subject_id or "").strip()
        if not sid or not isinstance(rows, list):
            raise TripletValidationError("neighborhood byNode has an invalid subject or edge list")
        neighborhood_ids.add(sid)
        for row in rows:
            if not isinstance(row, dict):
                raise TripletValidationError("neighborhood edge must be an object")
            neighbor_id = str(row.get("u") or "").strip()
            if not neighbor_id:
                raise TripletValidationError("neighborhood edge has an empty neighbor id")
            neighborhood_ids.add(neighbor_id)
            emitted_edges += 1

    unknown_neighborhood_ids = sorted(neighborhood_ids - index_id_set)
    if unknown_neighborhood_ids:
        raise TripletValidationError(
            "neighborhood references subjects absent from atlas_index: "
            + ", ".join(unknown_neighborhood_ids[:5])
        )
    generation = neighborhood_payload.get("generation")
    if not isinstance(generation, dict):
        raise TripletValidationError("neighborhood generation object is missing")
    if generation.get("subjectCount") != len(by_node) or generation.get("edgeCount") != emitted_edges:
        raise TripletValidationError("neighborhood generation counts do not match its payload")
    if generation.get("nodeCount") != len(index_id_set):
        raise TripletValidationError(
            "neighborhood nodeCount does not match atlas_index subject count"
        )

    leaks = find_local_path_leaks(named_payloads, forbidden_paths)
    if leaks:
        finding = leaks[0]
        raise TripletValidationError(
            "local path leak detected in "
            f"{finding['artifact']} at {finding['field']} ({finding['reason']})"
        )

    report = {
        "datasetIds": identities,
        "staticNodeCount": len(static_nodes),
        "staticEdgeCount": len(static_edges),
        "indexSubjectCount": len(index_id_set),
        "neighborhoodSubjectCount": len(by_node),
        "neighborhoodEdgeCount": emitted_edges,
        "neighborhoodUnknownSubjectCount": len(unknown_neighborhood_ids),
        "pathLeakCount": len(leaks),
    }

    if require_manifest:
        manifest_path = root / TRIPLET_MANIFEST
        if not manifest_path.is_file():
            raise TripletValidationError(f"missing artifact: {TRIPLET_MANIFEST}")
        manifest = _read_json(manifest_path)
        if manifest.get("datasetId") != expected_id:
            raise TripletValidationError("triplet manifest datasetId mismatch")
        if manifest.get("decision") != "atlas_serving_triplet_candidate_ready":
            raise TripletValidationError("triplet manifest is not candidate-ready")
        if manifest.get("productionWriteExecuted") is not False or manifest.get("deployExecuted") is not False:
            raise TripletValidationError("triplet manifest violates the candidate-only boundary")
        artifact_rows = manifest.get("artifacts")
        if not isinstance(artifact_rows, dict) or set(artifact_rows) != set(GENERATED_ARTIFACTS):
            raise TripletValidationError("triplet manifest artifact set is incomplete")
        for name in GENERATED_ARTIFACTS:
            row = artifact_rows.get(name)
            artifact = root / name
            if not isinstance(row, dict) or not artifact.is_file():
                raise TripletValidationError(f"triplet manifest artifact missing: {name}")
            if row.get("sha256") != file_sha256(artifact) or row.get("size") != artifact.stat().st_size:
                raise TripletValidationError(f"triplet manifest digest mismatch: {name}")
        manifest_leaks = find_local_path_leaks({TRIPLET_MANIFEST: manifest}, forbidden_paths)
        if manifest_leaks:
            finding = manifest_leaks[0]
            raise TripletValidationError(
                f"local path leak detected in {TRIPLET_MANIFEST} at {finding['field']}"
            )
    return report


def _source_digests(paths: dict[str, Path | None]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for label, path in paths.items():
        if path is None:
            continue
        rows[label] = {"sha256": file_sha256(path), "size": path.stat().st_size}
    return rows


def _sqlite_online_snapshot(source: Path, destination: Path) -> Path:
    """Freeze one WAL-aware, point-in-time SQLite image with the online backup API."""
    selected_source = _require_file(source, "SQLite source")
    selected_destination = Path(destination).resolve(strict=False)
    selected_destination.parent.mkdir(parents=True, exist_ok=True)
    if selected_destination.exists():
        raise FileExistsError(f"snapshot destination already exists: {selected_destination}")
    source_con = _connect_ro(selected_source)
    destination_con = sqlite3.connect(str(selected_destination))
    try:
        source_con.backup(destination_con)
        destination_con.commit()
        result = destination_con.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise TripletValidationError(
                f"SQLite online snapshot failed quick_check: {selected_source.name}"
            )
    finally:
        destination_con.close()
        source_con.close()
    # Windows rejects fsync on a read-only descriptor. Open without modifying
    # bytes solely to flush the completed backup before exporters consume it.
    with selected_destination.open("r+b") as handle:
        os.fsync(handle.fileno())
    return selected_destination


def _read_upstream_generation_marker(con: sqlite3.Connection, role: str) -> str | None:
    tables = {
        str(row[0])
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    discovered: list[tuple[str, str, str]] = []
    for table in UPSTREAM_GENERATION_MARKER_TABLES:
        if table not in tables:
            continue
        columns = {
            str(row[1]).casefold()
            for row in con.execute(f'PRAGMA table_info("{table}")')
        }
        if not {"key", "value"}.issubset(columns):
            continue
        rows = con.execute(
            f'SELECT "key", "value" FROM "{table}" WHERE "key" IN ({",".join("?" for _ in UPSTREAM_GENERATION_MARKER_KEYS)})',
            UPSTREAM_GENERATION_MARKER_KEYS,
        ).fetchall()
        for row in rows:
            value = str(row[1] or "").strip()
            if value:
                discovered.append((table, str(row[0]), validate_dataset_id(value)))
    values = {row[2] for row in discovered}
    if len(values) > 1:
        raise TripletValidationError(
            f"{role} database has conflicting upstream generation markers"
        )
    return next(iter(values), None)


def _guard_state(con: sqlite3.Connection, role: str) -> dict[str, Any]:
    row = con.execute("PRAGMA data_version").fetchone()
    if not row:
        raise TripletValidationError(f"{role} database has no SQLite data_version")
    return {
        "dataVersion": int(row[0]),
        "upstreamGeneration": _read_upstream_generation_marker(con, role),
    }


def _assert_snapshot_guards_unchanged(
    guards: dict[str, sqlite3.Connection],
    baseline: dict[str, dict[str, Any]],
    phase: str,
) -> None:
    for role, con in guards.items():
        current = _guard_state(con, role)
        if current != baseline[role]:
            raise TripletValidationError(
                f"{role} database changed during multi-role snapshot ({phase})"
            )


def _resolve_multi_role_release_identity(
    baseline: dict[str, dict[str, Any]],
    frozen_release_identity: str | None,
) -> tuple[str, str]:
    explicit = validate_dataset_id(frozen_release_identity) if frozen_release_identity else None
    markers = {
        role: str(row.get("upstreamGeneration") or "")
        for role, row in baseline.items()
    }
    present_values = {value for value in markers.values() if value}
    if len(present_values) > 1:
        raise TripletValidationError(
            "multi-role SQLite inputs do not share one upstream generation marker"
        )
    if explicit:
        if present_values and present_values != {explicit}:
            raise TripletValidationError(
                "explicit frozen release identity disagrees with an upstream generation marker"
            )
        return explicit, (
            "shared_upstream_generation_marker"
            if len(markers) == sum(bool(value) for value in markers.values())
            else "explicit_frozen_release_identity"
        )
    if not markers or any(not value for value in markers.values()):
        missing = ", ".join(sorted(role for role, value in markers.items() if not value))
        raise TripletValidationError(
            "multi-role SQLite inputs require one shared upstream generation marker "
            f"or --frozen-release-id; missing marker roles: {missing}"
        )
    return next(iter(present_values)), "shared_upstream_generation_marker"


def _snapshot_sqlite_inputs(
    inputs: dict[str, Path | None],
    snapshot_dir: Path,
    frozen_release_identity: str | None = None,
) -> tuple[dict[str, Path | None], list[str], dict[str, Any]]:
    frozen = dict(inputs)
    roles = [
        role for role in sorted(SQLITE_INPUT_ROLES)
        if inputs.get(role) is not None
    ]
    if len(roles) <= 1:
        for role in roles:
            source = inputs[role]
            frozen[role] = _sqlite_online_snapshot(
                source,
                Path(snapshot_dir) / f"{role}.snapshot.sqlite",
            )
        return frozen, roles, {
            "mode": "single_source",
            "releaseIdentity": (
                validate_dataset_id(frozen_release_identity)
                if frozen_release_identity else None
            ),
            "roles": roles,
            "beforeAndAfterEachRoleVerified": True,
        }

    guards: dict[str, sqlite3.Connection] = {}
    try:
        guards = {
            role: _connect_ro(inputs[role])
            for role in roles
        }
        baseline = {
            role: _guard_state(con, role)
            for role, con in guards.items()
        }
        release_identity, mode = _resolve_multi_role_release_identity(
            baseline,
            frozen_release_identity,
        )
        snapshot_marker_presence: dict[str, bool] = {}
        for role in roles:
            _assert_snapshot_guards_unchanged(guards, baseline, f"before {role} backup")
            source = inputs[role]
            snapshot = _sqlite_online_snapshot(
                source,
                Path(snapshot_dir) / f"{role}.snapshot.sqlite",
            )
            frozen[role] = snapshot
            snapshot_con = _connect_ro(snapshot)
            try:
                snapshot_marker = _read_upstream_generation_marker(snapshot_con, role)
            finally:
                snapshot_con.close()
            expected_marker = baseline[role]["upstreamGeneration"]
            if snapshot_marker != expected_marker:
                raise TripletValidationError(
                    f"{role} upstream generation marker changed during multi-role snapshot"
                )
            snapshot_marker_presence[role] = bool(snapshot_marker)
            _assert_snapshot_guards_unchanged(guards, baseline, f"after {role} backup")
        _assert_snapshot_guards_unchanged(guards, baseline, "final verification")
        return frozen, roles, {
            "mode": mode,
            "releaseIdentity": release_identity,
            "roles": roles,
            "markerPresent": snapshot_marker_presence,
            "sqliteDataVersionGuarded": True,
            "beforeAndAfterEachRoleVerified": True,
        }
    finally:
        for con in guards.values():
            con.close()


def _snapshot_dataset_id(
    source_mode: str,
    source_digests: dict[str, dict[str, Any]],
) -> str:
    if source_mode == "miniapp_single_source":
        miniapp_digest = str(source_digests.get("miniapp", {}).get("sha256") or "")
        if len(miniapp_digest) != 64:
            raise TripletValidationError("miniapp snapshot has no stable SHA256 identity")
        return validate_dataset_id(f"atlas-miniapp-sha256-{miniapp_digest}")
    identity_payload = {
        role: {
            "sha256": str(row.get("sha256") or ""),
            "size": int(row.get("size") or 0),
        }
        for role, row in sorted(source_digests.items())
    }
    serialized = json.dumps(
        identity_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return validate_dataset_id(f"atlas-triplet-sha256-{digest}")


def _builder_digests() -> dict[str, dict[str, Any]]:
    return {
        label: {"sha256": file_sha256(path), "size": path.stat().st_size}
        for label, path in BUILDER_FILES.items()
    }


def build_triplet(
    *,
    miniapp_db: Path,
    dataset_id: str | None = None,
    out_dir: Path,
    v2: Path | None = None,
    serving: Path | None = None,
    frozen_release_identity: str | None = None,
    bio_serving: Path | None = None,
    bio_candidate: Path | None = None,
    links_candidate: Path | None = None,
    venue_merge_map: Path | None = None,
    column_json: Path | None = None,
    max_nodes: int = 240,
    max_edges: int = 640,
    neighbor_cap: int = 60,
) -> dict[str, Any]:
    expected_id = validate_dataset_id(dataset_id) if dataset_id else None
    selected_out = validate_external_output_dir(out_dir)
    if max_nodes < 1 or max_edges < 0:
        raise ValueError("max-nodes must be positive and max-edges must be non-negative")
    if neighbor_cap < 1 or neighbor_cap > 100:
        raise ValueError("neighbor-cap must be between 1 and 100")

    if (v2 is None) != (serving is None):
        raise ValueError("--v2 and --serving must be supplied together or both omitted")
    v2_mode = v2 is not None
    optional_v2_inputs = {
        "bioServing": bio_serving,
        "bioCandidate": bio_candidate,
        "linksCandidate": links_candidate,
        "venueMergeMap": venue_merge_map,
        "columnJson": column_json,
    }
    if not v2_mode and any(value is not None for value in optional_v2_inputs.values()):
        raise ValueError(
            "bio/links/venue-map/column enrichment inputs require the explicit --v2/--serving mode"
        )
    original_inputs: dict[str, Path | None] = {
        "miniapp": _require_file(miniapp_db, "miniapp database"),
    }
    if v2_mode:
        original_inputs.update(
            {
                "v2": _require_file(v2, "v2 database"),
                "serving": _require_file(serving, "serving database"),
                "bioServing": _require_file(bio_serving, "bio serving database") if bio_serving else None,
                "bioCandidate": _require_file(bio_candidate, "bio candidate") if bio_candidate else None,
                "linksCandidate": _require_file(links_candidate, "links candidate") if links_candidate else None,
                "venueMergeMap": _require_file(venue_merge_map, "venue merge map") if venue_merge_map else None,
                "columnJson": _require_file(column_json, "column JSON") if column_json else None,
            }
        )
        source_mode = "v2_plus_serving_with_identity_gate"
    else:
        source_mode = "miniapp_single_source"
    builder_digests_before = _builder_digests()
    selected_out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{selected_out.name}.building-",
        dir=selected_out.parent,
    ) as temporary:
        work_root = Path(temporary)
        staging = work_root / "candidate"
        snapshot_dir = work_root / "sqlite-snapshots"
        staging.mkdir()
        snapshot_dir.mkdir()
        inputs, snapshot_roles, release_identity_guard = _snapshot_sqlite_inputs(
            original_inputs,
            snapshot_dir,
            frozen_release_identity=frozen_release_identity,
        )
        if v2_mode:
            input_preflight = preflight_inputs(
                v2=inputs["v2"],
                serving=inputs["serving"],
                miniapp_db=inputs["miniapp"],
            )
        else:
            input_preflight = preflight_miniapp_input(miniapp_db=inputs["miniapp"])
        source_digests_before = _source_digests(inputs)
        selected_id = _snapshot_dataset_id(source_mode, source_digests_before)
        if expected_id and expected_id != selected_id:
            raise TripletValidationError(
                "explicit datasetId does not match the immutable SQLite snapshot: "
                f"expected {selected_id}"
            )
        if v2_mode:
            build_starmap(
                inputs["v2"],
                staging / STATIC_JSON,
                max_nodes=max_nodes,
                max_edges=max_edges,
                out_js_path=staging / STATIC_JS,
                dataset_id=selected_id,
            )
            export_index(
                inputs["v2"],
                inputs["serving"],
                staging / INDEX_GZ,
                inputs["columnJson"],
                inputs["bioServing"],
                inputs["bioCandidate"],
                inputs["linksCandidate"],
                inputs["venueMergeMap"],
                selected_id,
            )
        else:
            build_starmap_from_miniapp(
                inputs["miniapp"],
                staging / STATIC_JSON,
                max_nodes=max_nodes,
                max_edges=max_edges,
                out_js_path=staging / STATIC_JS,
                dataset_id=selected_id,
            )
            export_index_from_miniapp(
                inputs["miniapp"],
                staging / INDEX_GZ,
                selected_id,
            )
        build_neighborhood(
            inputs["miniapp"],
            staging / NEIGHBORHOOD_GZ,
            cap=neighbor_cap,
            dataset_id=selected_id,
        )
        source_digests_after = _source_digests(inputs)
        if source_digests_after != source_digests_before:
            raise TripletValidationError(
                "source input changed during generation; refusing a mixed-snapshot candidate"
            )
        if _builder_digests() != builder_digests_before:
            raise TripletValidationError(
                "builder code changed during generation; refusing an untraceable candidate"
            )

        forbidden_paths = [
            path for path in (*original_inputs.values(), *inputs.values()) if path is not None
        ] + [work_root, staging, snapshot_dir, selected_out, selected_out.parent]
        verification = verify_triplet(
            staging,
            selected_id,
            forbidden_paths=forbidden_paths,
        )
        artifacts = {
            name: {
                "sha256": file_sha256(staging / name),
                "size": (staging / name).stat().st_size,
            }
            for name in GENERATED_ARTIFACTS
        }
        manifest = {
            "schemaVersion": "atlas.serving.triplet.candidate.v1",
            "decision": "atlas_serving_triplet_candidate_ready",
            "datasetId": selected_id,
            "sourceMode": source_mode,
            "boundary": "external_candidate_only_no_pointer_change",
            "productionWriteExecuted": False,
            "deployExecuted": False,
            "sourceDigests": source_digests_before,
            "sourceSnapshot": {
                "method": "sqlite3.Connection.backup",
                "sqliteRoles": snapshot_roles,
                "exportersReadFrozenCopies": True,
                "temporarySnapshotsRetained": False,
                "releaseIdentityGuard": release_identity_guard,
            },
            "builderDigests": builder_digests_before,
            "inputPreflight": input_preflight,
            "artifacts": artifacts,
            "verification": verification,
        }
        (staging / TRIPLET_MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify_triplet(
            staging,
            selected_id,
            forbidden_paths=forbidden_paths,
            require_manifest=True,
        )
        os.replace(staging, selected_out)

    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2", type=Path, help="Optional read-only atlas_serving_v2.sqlite; requires --serving")
    parser.add_argument("--serving", type=Path, help="Optional accepted Stage4 serving SQLite; requires --v2")
    parser.add_argument(
        "--frozen-release-id",
        help=(
            "Explicit identity for operator-frozen multi-role SQLite inputs; "
            "required only when the databases do not share an embedded generation marker"
        ),
    )
    parser.add_argument("--miniapp-db", type=Path, required=True, help="Read-only atlas_miniapp.sqlite")
    parser.add_argument(
        "--dataset-id",
        help="Optional expected snapshot-derived dataset id; mismatches fail closed",
    )
    parser.add_argument("--out-dir", type=Path, required=True, help="New absolute candidate directory outside this repository")
    parser.add_argument("--bio-serving", type=Path)
    parser.add_argument("--bio-candidate", type=Path)
    parser.add_argument("--links-candidate", type=Path)
    parser.add_argument("--venue-merge-map", type=Path)
    parser.add_argument("--column-json", type=Path, help="Optional explicit column enrichment; no production default is used")
    parser.add_argument("--max-nodes", type=int, default=240)
    parser.add_argument("--max-edges", type=int, default=640)
    parser.add_argument("--neighbor-cap", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = build_triplet(
            v2=args.v2,
            serving=args.serving,
            frozen_release_identity=args.frozen_release_id,
            miniapp_db=args.miniapp_db,
            dataset_id=args.dataset_id,
            out_dir=args.out_dir,
            bio_serving=args.bio_serving,
            bio_candidate=args.bio_candidate,
            links_candidate=args.links_candidate,
            venue_merge_map=args.venue_merge_map,
            column_json=args.column_json,
            max_nodes=args.max_nodes,
            max_edges=args.max_edges,
            neighbor_cap=args.neighbor_cap,
        )
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
