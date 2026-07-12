#!/usr/bin/env python3
"""Build a read-only DJ identity classification sidecar for Atlas serving."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "atlas_serving_identity_redirect.v1"
HASH_DJ_ID = re.compile(r"^dj:[0-9a-f]{16}$", re.IGNORECASE)
ROLE_LABEL_RE = re.compile(r"^(?:dj|aka)(?:\s+|[:/_.-]+)(.+)$", re.IGNORECASE)
SELF_ANNOTATION_RE = re.compile(r"^(.+?)\s*\((.+)\)\s*$")
IDENTITY_NOISE_CORES = {"artist", "dj", "music", "艺人", "嘉宾", "音乐人"}


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
        (table,),
    ).fetchone() is not None


def _city_key(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _is_synthetic_dj_id(value: str) -> bool:
    return value.startswith("dj:") and len(value) > 3 and HASH_DJ_ID.fullmatch(value) is None


def _identity_name(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _role_label_core(value: str | None) -> tuple[str, str] | None:
    normalized = _identity_name(value)
    match = ROLE_LABEL_RE.fullmatch(normalized)
    if match:
        core = match.group(1).strip()
        if core and core not in IDENTITY_NOISE_CORES:
            return core, "role_label_exact"
    annotation = SELF_ANNOTATION_RE.fullmatch(normalized)
    if not annotation:
        return None
    outer = annotation.group(1).strip()
    inner = annotation.group(2).strip()
    inner_role = ROLE_LABEL_RE.fullmatch(inner)
    inner_core = inner_role.group(1).strip() if inner_role else inner
    if outer and outer == inner_core and outer not in IDENTITY_NOISE_CORES:
        return outer, "self_annotation_exact"
    return None


def _load_dj_evidence(
    source_path: Path,
    dj_ids: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    sources: dict[str, set[str]] = defaultdict(set)
    timeline: dict[str, set[str]] = defaultdict(set)
    if not dj_ids:
        return sources, timeline
    source = _open_read_only(source_path)
    try:
        if not _table_exists(source, "dj_event"):
            return sources, timeline
        ordered = sorted(dj_ids)
        for offset in range(0, len(ordered), 400):
            chunk = ordered[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            for row in source.execute(
                f"""SELECT dj_id,event_id,starts_at,venue_id,source_ref_id
                      FROM dj_event WHERE dj_id IN ({placeholders})""",
                chunk,
            ):
                dj_id = str(row["dj_id"])
                event_id = str(row["event_id"] or "").strip()
                starts_at = str(row["starts_at"] or "").strip()
                venue_id = str(row["venue_id"] or "").strip()
                source_ref_id = str(row["source_ref_id"] or "").strip()
                if source_ref_id:
                    sources[dj_id].add(source_ref_id)
                if event_id:
                    timeline[dj_id].add(f"event:{event_id}")
                if starts_at and venue_id:
                    timeline[dj_id].add(f"timeline:{starts_at}|{venue_id}")
    finally:
        source.close()
    return sources, timeline


def _canonical_role_label_redirects(
    source_path: Path,
    canonical: list[dict],
    profiles_by_id: dict[str, dict],
    canonical_by_name: dict[str, list[dict]],
    decisions: dict[str, dict],
    decided_at: str,
) -> list[dict]:
    proposed: list[tuple[str, str, str]] = []
    for row in canonical:
        source_id = row["subject_id"]
        if source_id in decisions:
            continue
        parsed = _role_label_core(row["normalized_name"])
        if not parsed:
            continue
        core, rule = parsed
        candidates = canonical_by_name.get(core, [])
        if len(candidates) != 1 or candidates[0]["subject_id"] == source_id:
            continue
        proposed.append((source_id, candidates[0]["subject_id"], rule))

    evidence_ids = {dj_id for source_id, target_id, _ in proposed for dj_id in (source_id, target_id)}
    sources, timeline = _load_dj_evidence(source_path, evidence_ids)
    accepted: list[tuple[str, str, str, int, int]] = []
    for source_id, target_id, rule in proposed:
        shared_sources = len(sources[source_id] & sources[target_id])
        shared_timeline = len(timeline[source_id] & timeline[target_id])
        if shared_sources or shared_timeline:
            accepted.append((source_id, target_id, rule, shared_sources, shared_timeline))

    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for source_id, target_id, *_ in accepted:
        union(source_id, target_id)

    components: dict[str, set[str]] = defaultdict(set)
    for dj_id in parent:
        components[find(dj_id)].add(dj_id)

    def rank(dj_id: str) -> tuple[int, int, int, int, str]:
        normalized_name = profiles_by_id[dj_id]["normalized_name"]
        undecorated = int(_role_label_core(normalized_name) is None)
        return (
            len(sources[dj_id]),
            len(timeline[dj_id]),
            undecorated,
            -len(_identity_name(normalized_name)),
            dj_id,
        )

    redirects: list[dict] = []
    for members in components.values():
        root = max(members, key=rank)
        component_edges = [edge for edge in accepted if edge[0] in members and edge[1] in members]
        for source_id in sorted(members - {root}):
            direct_edges = [
                edge
                for edge in component_edges
                if {edge[0], edge[1]} == {source_id, root}
            ]
            evidence_edges = direct_edges or component_edges
            shared_sources = max((edge[3] for edge in evidence_edges), default=0)
            shared_timeline = max((edge[4] for edge in evidence_edges), default=0)
            rules = sorted({edge[2] for edge in evidence_edges})
            redirects.append(
                {
                    "source_dj_id": source_id,
                    "canonical_dj_id": root,
                    "decision_method": "role_label_evidence",
                    "decision_reason": (
                        f"{'/'.join(rules)}; shared_sources={shared_sources}; "
                        f"shared_timeline_keys={shared_timeline}"
                    ),
                    "confidence": 0.98,
                    "decided_at": decided_at,
                }
            )
    return redirects


def _digest(rows: list[dict]) -> str:
    hasher = hashlib.sha256()
    for row in rows:
        hasher.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def _accepted_decisions(path: Path | None) -> tuple[dict[str, dict], list[dict]]:
    if path is None:
        return {}, []
    if not path.is_file():
        raise FileNotFoundError(path)

    raw_rows = _read_jsonl(path)
    decisions: dict[str, dict] = {}
    for row in raw_rows:
        source_id = str(row.get("source_dj_id") or row.get("merged_id") or "").strip()
        canonical_id = str(row.get("canonical_dj_id") or row.get("canonical_id") or "").strip()
        action = str(row.get("action") or row.get("decision") or row.get("review_state") or "").strip().casefold()
        planner_flag = row.get("apply_allowed_by_planner")
        is_redirect = bool(
            source_id
            and canonical_id
            and (
                planner_flag is True
                or (
                    planner_flag is None
                    and action in {"merge", "merge_candidate", "redirect", "accept", "accepted"}
                )
            )
        )
        is_keep_separate = bool(source_id and action in {"keep_separate", "keep-separate", "separate", "reject_merge"})
        if not is_redirect and not is_keep_separate:
            continue
        decision = {
            "source_dj_id": source_id,
            "canonical_dj_id": canonical_id if is_redirect else None,
            "action": "redirect" if is_redirect else "keep_separate",
            "reason": str(row.get("decision_reason") or row.get("reason") or action or "accepted_plan"),
        }
        previous = decisions.get(source_id)
        if previous and previous != decision:
            raise ValueError(f"Conflicting accepted decisions for {source_id}")
        decisions[source_id] = decision
    return decisions, raw_rows


def _deterministic_timestamp(source_db: Path, accepted_plan: Path | None) -> str:
    mtimes = [source_db.stat().st_mtime]
    if accepted_plan is not None:
        mtimes.append(accepted_plan.stat().st_mtime)
    return datetime.fromtimestamp(max(mtimes), timezone.utc).replace(microsecond=0).isoformat()


def _create_output(
    out_db: Path,
    redirects: list[dict],
    reviews: list[dict],
    metadata: dict[str, str],
) -> None:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = out_db.with_name(f"{out_db.name}.tmp")
    if tmp_db.exists():
        tmp_db.unlink()

    con = sqlite3.connect(tmp_db)
    try:
        con.executescript(
            """
            PRAGMA journal_mode=DELETE;
            CREATE TABLE dj_identity_redirect (
              source_dj_id TEXT PRIMARY KEY,
              canonical_dj_id TEXT NOT NULL,
              decision_method TEXT NOT NULL CHECK(decision_method IN ('identity','synthetic_exact','role_label_evidence','accepted_plan','human')),
              decision_reason TEXT NOT NULL,
              confidence REAL NOT NULL,
              decided_at TEXT NOT NULL
            );
            CREATE INDEX idx_dj_identity_redirect_canonical
              ON dj_identity_redirect(canonical_dj_id);
            CREATE TABLE dj_identity_review_candidate (
              source_dj_id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              normalized_name TEXT NOT NULL,
              city_primary TEXT,
              candidate_dj_id TEXT,
              candidate_city TEXT,
              reason TEXT NOT NULL,
              review_state TEXT NOT NULL CHECK(review_state IN ('needs_review','new_canonical','keep_separate'))
            );
            CREATE INDEX idx_dj_identity_review_state
              ON dj_identity_review_candidate(review_state, normalized_name);
            CREATE TABLE identity_build_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        con.executemany(
            """
            INSERT INTO dj_identity_redirect
              (source_dj_id,canonical_dj_id,decision_method,decision_reason,confidence,decided_at)
            VALUES
              (:source_dj_id,:canonical_dj_id,:decision_method,:decision_reason,:confidence,:decided_at)
            """,
            redirects,
        )
        con.executemany(
            """
            INSERT INTO dj_identity_review_candidate
              (source_dj_id,display_name,normalized_name,city_primary,candidate_dj_id,candidate_city,reason,review_state)
            VALUES
              (:source_dj_id,:display_name,:normalized_name,:city_primary,:candidate_dj_id,:candidate_city,:reason,:review_state)
            """,
            reviews,
        )
        con.executemany(
            "INSERT INTO identity_build_metadata(key,value) VALUES (?,?)",
            sorted(metadata.items()),
        )
        con.commit()
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Generated identity sidecar failed PRAGMA quick_check")
    except Exception:
        con.close()
        if tmp_db.exists():
            tmp_db.unlink()
        raise
    else:
        con.close()
    os.replace(tmp_db, out_db)


def build_redirects(
    source_serving_db: Path | str,
    out_db: Path | str,
    accepted_entity_plan: Path | str | None = None,
    report_path: Path | str | None = None,
) -> dict:
    source_path = Path(source_serving_db).resolve()
    output_path = Path(out_db).resolve()
    accepted_path = Path(accepted_entity_plan).resolve() if accepted_entity_plan else None
    if source_path == output_path:
        raise ValueError("Identity sidecar output must not overwrite the source serving DB")

    decisions, accepted_rows = _accepted_decisions(accepted_path)
    source = _open_read_only(source_path)
    try:
        missing = [table for table in ("dj_profile", "canonical_subject") if not _table_exists(source, table)]
        if missing:
            raise ValueError(f"Source serving DB is missing required tables: {', '.join(missing)}")
        quick_check = source.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"Source serving DB failed PRAGMA quick_check: {quick_check}")

        profiles = [
            dict(row)
            for row in source.execute(
                "SELECT dj_id,display_name,normalized_name,COALESCE(city_primary,'') AS city_primary FROM dj_profile ORDER BY dj_id"
            )
        ]
        canonical = [
            dict(row)
            for row in source.execute(
                """
                SELECT subject_id,display_name,normalized_name,COALESCE(city_primary,'') AS city_primary
                  FROM canonical_subject
                 WHERE subject_type='dj'
                 ORDER BY subject_id
                """
            )
        ]
    finally:
        source.close()

    profiles_by_id = {row["dj_id"]: row for row in profiles}
    canonical_by_id = {row["subject_id"]: row for row in canonical}
    canonical_by_name: dict[str, list[dict]] = {}
    for row in canonical:
        canonical_by_name.setdefault(row["normalized_name"], []).append(row)
    missing_profiles = sorted(set(canonical_by_id) - set(profiles_by_id))
    if missing_profiles:
        raise ValueError(f"Canonical subjects missing from dj_profile: {len(missing_profiles)}")

    unknown_decisions = sorted(set(decisions) - set(profiles_by_id))
    if unknown_decisions:
        raise ValueError(f"Accepted plan references unknown source DJs: {unknown_decisions[:5]}")

    decided_at = _deterministic_timestamp(source_path, accepted_path)
    redirects = _canonical_role_label_redirects(
        source_path,
        canonical,
        profiles_by_id,
        canonical_by_name,
        decisions,
        decided_at,
    )
    canonical_role_label_redirects = len(redirects)
    for source_id, accepted in sorted(decisions.items()):
        if source_id not in canonical_by_id or accepted["action"] != "redirect":
            continue
        target_id = accepted["canonical_dj_id"]
        if target_id not in canonical_by_id:
            raise ValueError(f"Accepted redirect target is not canonical: {source_id} -> {target_id}")
        if source_id == target_id:
            raise ValueError(f"Accepted redirect cannot target itself: {source_id}")
        redirects.append(
            {
                "source_dj_id": source_id,
                "canonical_dj_id": target_id,
                "decision_method": "accepted_plan",
                "decision_reason": accepted["reason"],
                "confidence": 1.0,
                "decided_at": decided_at,
            }
        )
    reviews: list[dict] = []
    non_canonical = [row for row in profiles if row["dj_id"] not in canonical_by_id]
    for profile in non_canonical:
        source_id = profile["dj_id"]
        accepted = decisions.get(source_id)
        if accepted and accepted["action"] == "keep_separate":
            reviews.append(
                {
                    "source_dj_id": source_id,
                    "display_name": profile["display_name"],
                    "normalized_name": profile["normalized_name"],
                    "city_primary": profile["city_primary"],
                    "candidate_dj_id": None,
                    "candidate_city": None,
                    "reason": accepted["reason"],
                    "review_state": "keep_separate",
                }
            )
            continue
        if accepted and accepted["action"] == "redirect":
            target_id = accepted["canonical_dj_id"]
            if target_id not in canonical_by_id:
                raise ValueError(f"Accepted redirect target is not canonical: {source_id} -> {target_id}")
            redirects.append(
                {
                    "source_dj_id": source_id,
                    "canonical_dj_id": target_id,
                    "decision_method": "accepted_plan",
                    "decision_reason": accepted["reason"],
                    "confidence": 1.0,
                    "decided_at": decided_at,
                }
            )
            continue

        candidates = canonical_by_name.get(profile["normalized_name"], [])
        candidate = candidates[0] if len(candidates) == 1 else None
        source_city = _city_key(profile["city_primary"])
        candidate_city = _city_key(candidate["city_primary"]) if candidate else ""
        city_compatible = not source_city or source_city == candidate_city
        if _is_synthetic_dj_id(source_id) and candidate and city_compatible:
            redirects.append(
                {
                    "source_dj_id": source_id,
                    "canonical_dj_id": candidate["subject_id"],
                    "decision_method": "synthetic_exact",
                    "decision_reason": "unique_normalized_name_and_city_compatible",
                    "confidence": 0.99,
                    "decided_at": decided_at,
                }
            )
            continue

        if not candidates and _is_synthetic_dj_id(source_id):
            state = "new_canonical"
            reason = "no_canonical_normalized_name_match"
        elif len(candidates) > 1:
            state = "needs_review"
            reason = "ambiguous_canonical_normalized_name_match"
        elif candidate and not city_compatible:
            state = "needs_review"
            reason = "city_conflict"
        else:
            state = "needs_review"
            reason = "noncanonical_id_outside_synthetic_contract"
        reviews.append(
            {
                "source_dj_id": source_id,
                "display_name": profile["display_name"],
                "normalized_name": profile["normalized_name"],
                "city_primary": profile["city_primary"],
                "candidate_dj_id": candidate["subject_id"] if candidate else None,
                "candidate_city": candidate["city_primary"] if candidate else None,
                "reason": reason,
                "review_state": state,
            }
        )

    redirects.sort(key=lambda row: row["source_dj_id"])
    reviews.sort(key=lambda row: row["source_dj_id"])
    review_candidates = sum(row["review_state"] != "new_canonical" for row in reviews)
    new_canonical = sum(row["review_state"] == "new_canonical" for row in reviews)
    keep_separate = sum(row["review_state"] == "keep_separate" for row in reviews)
    non_canonical_ids = {row["dj_id"] for row in non_canonical}
    classified_profiles = sum(row["source_dj_id"] in non_canonical_ids for row in redirects) + len(reviews)
    if classified_profiles != len(non_canonical):
        raise RuntimeError(
            f"Identity classification coverage mismatch: {classified_profiles} != {len(non_canonical)}"
        )

    digest_input = [
        {"kind": "profile", **row} for row in profiles
    ] + [
        {"kind": "canonical", **row} for row in canonical
    ] + [
        {"kind": "accepted_plan", **row} for row in accepted_rows
    ]
    classification_rows = [
        {key: value for key, value in row.items() if key != "decided_at"} for row in redirects
    ] + reviews
    input_digest = _digest(digest_input)
    classification_digest = _digest(classification_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "decision": "READY" if quick_check == "ok" else "HOLD",
        "source_serving_db": str(source_path),
        "out_db": str(output_path),
        "accepted_entity_plan": str(accepted_path) if accepted_path else None,
        "quick_check": quick_check,
        "dj_profiles": len(profiles),
        "canonical_djs": len(canonical),
        "non_canonical_profiles": len(non_canonical),
        "auto_redirects": len(redirects),
        "canonical_role_label_redirects": canonical_role_label_redirects,
        "synthetic_exact_redirects": sum(row["decision_method"] == "synthetic_exact" for row in redirects),
        "accepted_plan_redirects": sum(row["decision_method"] == "accepted_plan" for row in redirects),
        "review_candidates": review_candidates,
        "new_canonical": new_canonical,
        "keep_separate": keep_separate,
        "classified_profiles": classified_profiles,
        "coverage_ok": classified_profiles == len(non_canonical),
        "input_digest": input_digest,
        "classification_digest": classification_digest,
        "safety": {
            "source_opened_read_only": True,
            "source_mutated": False,
            "candidate_only": True,
        },
    }
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "source_serving_db": str(source_path),
        "accepted_entity_plan": str(accepted_path) if accepted_path else "",
        "input_digest": input_digest,
        "classification_digest": classification_digest,
        "counts_json": json.dumps(
            {
                "dj_profiles": len(profiles),
                "canonical_djs": len(canonical),
                "non_canonical_profiles": len(non_canonical),
                "canonical_role_label_redirects": canonical_role_label_redirects,
                "redirects": len(redirects),
                "reviews": len(reviews),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "decided_at": decided_at,
    }
    _create_output(output_path, redirects, reviews, metadata)

    if report_path is not None:
        report_file = Path(report_path).resolve()
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _self_check() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_identity_selfcheck_") as tmp:
        root = Path(tmp)
        source = root / "source.sqlite"
        con = sqlite3.connect(source)
        con.executescript(
            """
            CREATE TABLE dj_profile(dj_id TEXT PRIMARY KEY,display_name TEXT NOT NULL,normalized_name TEXT NOT NULL,city_primary TEXT);
            CREATE TABLE canonical_subject(subject_id TEXT PRIMARY KEY,subject_type TEXT NOT NULL,display_name TEXT NOT NULL,normalized_name TEXT NOT NULL,city_primary TEXT);
            INSERT INTO dj_profile VALUES('dj:1111111111111111','MAXXI','maxxi','昆明');
            INSERT INTO dj_profile VALUES('dj:maxxi','MAXXI','maxxi','');
            INSERT INTO canonical_subject VALUES('dj:1111111111111111','dj','MAXXI','maxxi','昆明');
            """
        )
        con.close()
        out = root / "identity.sqlite"
        report = build_redirects(source, out)
        assert report["auto_redirects"] == 1, report
        assert report["coverage_ok"], report
        check = sqlite3.connect(out)
        try:
            assert check.execute("SELECT canonical_dj_id FROM dj_identity_redirect").fetchone()[0] == "dj:1111111111111111"
        finally:
            check.close()
    print("self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-serving-db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--accepted-entity-plan", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return
    if args.source_serving_db is None or args.out is None:
        parser.error("--source-serving-db and --out are required unless --self-check is used")
    report = build_redirects(
        args.source_serving_db,
        args.out,
        accepted_entity_plan=args.accepted_entity_plan,
        report_path=args.report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["decision"] == "READY" and report["coverage_ok"] else 2)


if __name__ == "__main__":
    main()
