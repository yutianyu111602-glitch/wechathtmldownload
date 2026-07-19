#!/usr/bin/env python3
"""Deterministically promote Atlas bio atoms inside an explicit data root.

This module has no checkout-data default.  Production callers must first copy
``atlas_index.json.gz`` and ``atlas_miniapp.sqlite`` into an isolated publish
transaction and pass those staged paths here.  A missing/invalid database is a
hard failure.  The returned report records the selected, matched, and changed
row counts plus byte digests for both artifacts.

The CLI is useful for an isolated candidate directory only::

    python promote_dj_bio_atoms.py --data-root X:/candidate --write \
        --report X:/candidate/dj_bio_promotion.json

It must not be pointed at a checkout or the authoritative runtime baseline by
the weekly publish wrapper; ``bake_and_deploy.py`` owns that transaction.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any


REPORT_SCHEMA_VERSION = "dj_bio_promotion_transaction.v1"
INDEX_NAME = "atlas_index.json.gz"
DB_NAME = "atlas_miniapp.sqlite"

STRONG_BIO_CUE = re.compile(
    r"bio|biography|about|artist|producer|selector|resident|founder|"
    r"based|born|from|released|played|known for|started|member of|"
    r"简介|介绍|来自|现居|生于|制作人|选择器|主理|创始|成员|"
    r"厂牌|风格|常驻|活跃|发行|涉猎|擅长",
    re.IGNORECASE,
)
WEAK_BIO_CUE = re.compile(
    r"购票|票价|预售|早鸟|全价|门票|地址|时间|日期|扫码|二维码|"
    r"开票|入场|酒水|卡座|dress code|ticket|tickets|venue|date|time|address|"
    r"今晚|明天|本周|当晚|现场|不见不散|等你来|欢迎|期待",
    re.IGNORECASE,
)
MIN_BIO_LENGTH = 30
MAX_BIO_LENGTH = 500


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required Atlas promotion artifact missing: {path}")
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_index(index_path: Path) -> dict[str, Any]:
    if not index_path.is_file():
        raise FileNotFoundError(f"required Atlas index missing: {index_path}")
    try:
        with gzip.open(index_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Atlas index is not valid gzip JSON: {index_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Atlas index root must be an object")
    if not isinstance(payload.get("profiles", {}), dict):
        raise ValueError("Atlas index profiles must be an object")
    if not isinstance(payload.get("bio_atoms", {}), dict):
        raise ValueError("Atlas index bio_atoms must be an object")
    return payload


def encode_index(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return gzip.compress(encoded, compresslevel=6, mtime=0)


def score_bio_atom(atom: dict[str, Any]) -> tuple[int, float]:
    text = str(atom.get("t") or "").strip()
    if len(text) < MIN_BIO_LENGTH:
        return (-1, 0.0)
    text = text[:MAX_BIO_LENGTH]
    length = len(text)
    score = 0.0
    if 40 <= length <= 200:
        score += 2.0
    elif 200 < length <= 400:
        score += 1.0
    elif length > 400:
        score += 0.3
    score += min(len(STRONG_BIO_CUE.findall(text)) * 0.5, 2.0)
    score -= len(WEAK_BIO_CUE.findall(text)) * 1.0
    confidence = atom.get("cf", 0.5)
    if isinstance(confidence, (int, float)):
        score += confidence * 2.0
    if atom.get("sr"):
        score += 1.0
    if atom.get("lang") == "zh":
        score += 0.5
    return (0, score) if score > 0 else (-1, score)


def select_best_bio(atoms: list[Any]) -> dict[str, Any] | None:
    candidates = [atom for atom in atoms if isinstance(atom, dict)]
    if not candidates:
        return None
    scored = [(score_bio_atom(atom), atom) for atom in candidates]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_atom = scored[0]
    return best_atom if best_score[0] >= 0 else None


def build_promotion_plan(index: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    bio_atoms = index.get("bio_atoms") or {}
    profiles = index.get("profiles") or {}
    counters = {
        "djs_with_atoms": len(bio_atoms),
        "selected_count": 0,
        "skipped_already_has_bio": 0,
        "skipped_no_good_atom": 0,
        "skipped_not_in_profiles": 0,
    }
    plan: list[dict[str, Any]] = []
    for raw_key, atoms in sorted(bio_atoms.items(), key=lambda item: str(item[0]).casefold()):
        dj_key = str(raw_key)
        dj_name = dj_key[3:] if dj_key.startswith("dj:") else dj_key
        profile_key = dj_key if isinstance(profiles.get(dj_key), dict) else dj_name
        profile = profiles.get(profile_key)
        if not isinstance(profile, dict):
            counters["skipped_not_in_profiles"] += 1
            continue
        if str(profile.get("b") or "").strip():
            counters["skipped_already_has_bio"] += 1
            continue
        best = select_best_bio(atoms if isinstance(atoms, list) else [])
        if best is None:
            counters["skipped_no_good_atom"] += 1
            continue
        bio = str(best.get("t") or "").strip()[:MAX_BIO_LENGTH]
        source_parts = [str(best.get(name) or "").strip() for name in ("sr", "st")]
        bio_source = " | ".join(part for part in source_parts if part) or "atlas_bio_atom"
        plan.append(
            {
                "dj_name": dj_name,
                "profile_key": profile_key,
                "bio": bio,
                "bio_source": bio_source,
                "bio_length": len(bio),
                "score": score_bio_atom(best)[1],
            }
        )
    counters["selected_count"] = len(plan)
    return plan, counters


def _normalized_lookup_values(value: str) -> list[str]:
    normalized = value.casefold().strip()
    values = [normalized, normalized.lstrip("$"), f"${normalized.lstrip('$')}"]
    return list(dict.fromkeys(item for item in values if item))


def _resolve_database_matches(
    connection: sqlite3.Connection,
    plan: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    try:
        rows = list(
            connection.execute(
                "SELECT dj_id, display_name, normalized_name, bio, bio_source FROM dj_profile"
            )
        )
    except sqlite3.Error as exc:
        raise ValueError("atlas_miniapp.sqlite lacks the required dj_profile schema") from exc
    lookup: dict[str, set[str]] = {}
    by_id: dict[str, tuple[Any, ...]] = {}
    for row in rows:
        dj_id = str(row[0])
        by_id[dj_id] = row
        for value in (dj_id, row[1], row[2]):
            if value is None:
                continue
            for key in _normalized_lookup_values(str(value)):
                lookup.setdefault(key, set()).add(dj_id)

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, str]] = []
    for item in plan:
        candidate_ids: set[str] = set()
        for key in _normalized_lookup_values(item["dj_name"]):
            candidate_ids.update(lookup.get(key, set()))
        if len(candidate_ids) != 1:
            unmatched.append(
                {
                    "dj_name": item["dj_name"],
                    "reason": "not_found" if not candidate_ids else "ambiguous",
                }
            )
            continue
        dj_id = next(iter(candidate_ids))
        row = by_id[dj_id]
        matched.append(
            {
                **item,
                "db_dj_id": dj_id,
                "existing_bio": str(row[3] or ""),
                "existing_bio_source": str(row[4] or ""),
            }
        )
    return matched, unmatched


def promote_dj_bio_atoms(
    *,
    index_path: Path,
    db_path: Path,
    write: bool,
    transaction_id: str = "",
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Plan or apply a promotion against explicit candidate artifacts."""

    index_path = Path(index_path).resolve()
    db_path = Path(db_path).resolve()
    if index_path == db_path:
        raise ValueError("Atlas index and database paths must be different")
    before = {
        INDEX_NAME: artifact_snapshot(index_path),
        DB_NAME: artifact_snapshot(db_path),
    }
    index = load_index(index_path)
    plan, counters = build_promotion_plan(index)

    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=rw", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"cannot open Atlas database read-write: {db_path}") from exc
    connection.row_factory = sqlite3.Row
    temporary_index = index_path.with_name(f".{index_path.name}.tmp-{os.getpid()}")
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]).lower() != "ok":
            raise ValueError("atlas_miniapp.sqlite PRAGMA quick_check failed")
        matched, unmatched = _resolve_database_matches(connection, plan)
        if plan and not matched:
            raise ValueError("DJ bio promotion selected candidates but matched zero database profiles")

        db_update_count = sum(
            1
            for item in matched
            if item["existing_bio"] != item["bio"]
            or item["existing_bio_source"] != item["bio_source"]
        )
        profiles = index.get("profiles") or {}
        index_update_count = sum(
            1
            for item in matched
            if str((profiles.get(item["profile_key"]) or {}).get("b") or "") != item["bio"]
            or str((profiles.get(item["profile_key"]) or {}).get("bs") or "") != item["bio_source"]
        )

        committed = False
        if write and matched:
            connection.execute("BEGIN IMMEDIATE")
            for item in matched:
                if (
                    item["existing_bio"] != item["bio"]
                    or item["existing_bio_source"] != item["bio_source"]
                ):
                    cursor = connection.execute(
                        "UPDATE dj_profile SET bio=?, bio_source=? WHERE dj_id=?",
                        (item["bio"], item["bio_source"], item["db_dj_id"]),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            f"Atlas bio update did not affect exactly one row: {item['db_dj_id']}"
                        )
                profile = profiles[item["profile_key"]]
                profile["b"] = item["bio"]
                profile["bs"] = item["bio_source"]
            temporary_index.write_bytes(encode_index(index))
            connection.commit()
            connection.close()
            os.replace(temporary_index, index_path)
            committed = True
        else:
            connection.close()

        after = {
            INDEX_NAME: artifact_snapshot(index_path),
            DB_NAME: artifact_snapshot(db_path),
        }
        changed = any(
            before[name]["sha256"] != after[name]["sha256"]
            for name in (INDEX_NAME, DB_NAME)
        )
        if write and bool(matched) and not committed:
            raise RuntimeError("DJ bio promotion matched rows but did not commit")
        report: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "mode": "write" if write else "dry_run",
            "write_applied": bool(write and committed),
            "committed": committed,
            "changed": changed,
            **counters,
            "matched_count": len(matched),
            "unmatched_count": len(unmatched),
            "db_update_count": db_update_count,
            "index_update_count": index_update_count,
            "before": before,
            "after": after,
            "database_quick_check": "ok",
            "unmatched": unmatched,
            "details": [
                {
                    "dj_name": item["dj_name"],
                    "db_dj_id": item["db_dj_id"],
                    "bio_length": item["bio_length"],
                    "source": item["bio_source"],
                    "score": item["score"],
                }
                for item in matched
            ],
        }
        if report_path is not None:
            write_json_atomic(Path(report_path), report)
        return report
    except Exception:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        try:
            connection.close()
        except sqlite3.Error:
            pass
        if temporary_index.exists():
            temporary_index.unlink()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote DJ bio atoms in an explicit isolated Atlas data root"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Isolated candidate data root containing atlas_index.json.gz and atlas_miniapp.sqlite.",
    )
    parser.add_argument("--write", action="store_true", help="Apply candidate writes")
    parser.add_argument("--transaction-id", default="", help="Owning publish transaction ID")
    parser.add_argument("--report", type=Path, default=None, help="Optional JSON evidence path")
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    try:
        report = promote_dj_bio_atoms(
            index_path=data_root / INDEX_NAME,
            db_path=data_root / DB_NAME,
            write=args.write,
            transaction_id=args.transaction_id,
            report_path=args.report,
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"ERROR: DJ bio promotion failed: {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
