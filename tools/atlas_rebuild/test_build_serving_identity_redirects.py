#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_serving_identity_redirects import build_redirects


def build_fixture(
    root: Path,
    *,
    canonical: tuple[str, str, str, str],
    incoming: tuple[str, str, str, str],
    extra: tuple[str, str, str, str] | None = None,
) -> Path:
    db_path = root / "source.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE dj_profile (
          dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          city_primary TEXT
        );
        CREATE TABLE canonical_subject (
          subject_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          city_primary TEXT
        );
        """
    )
    con.execute("INSERT INTO dj_profile VALUES (?,?,?,?)", canonical)
    con.execute("INSERT INTO canonical_subject VALUES (?,?,?,?,?)", (canonical[0], "dj", *canonical[1:]))
    con.execute("INSERT INTO dj_profile VALUES (?,?,?,?)", incoming)
    if extra:
        con.execute("INSERT INTO dj_profile VALUES (?,?,?,?)", extra)
        con.execute("INSERT INTO canonical_subject VALUES (?,?,?,?,?)", (extra[0], "dj", *extra[1:]))
    con.commit()
    con.close()
    return db_path


def read_redirect(db_path: Path, source_dj_id: str) -> str | None:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT canonical_dj_id FROM dj_identity_redirect WHERE source_dj_id=?",
            (source_dj_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def read_review_state(db_path: Path, source_dj_id: str) -> str | None:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT review_state FROM dj_identity_review_candidate WHERE source_dj_id=?",
            (source_dj_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


class ServingIdentityRedirectTests(unittest.TestCase):
    def test_synthetic_exact_name_maps_to_unique_canonical(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "MAXXI", "maxxi", "昆明"),
                incoming=("dj:maxxi", "MAXXI", "maxxi", ""),
            )
            out = root / "identity.sqlite"

            report = build_redirects(source, out)

            self.assertEqual(report["auto_redirects"], 1)
            self.assertEqual(read_redirect(out, "dj:maxxi"), "dj:1111111111111111")
            self.assertEqual(report["classified_profiles"], report["non_canonical_profiles"])

    def test_same_name_city_conflict_stays_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "NOVA", "nova", "上海"),
                incoming=("dj:nova", "NOVA", "nova", "成都"),
            )
            out = root / "identity.sqlite"

            report = build_redirects(source, out)

            self.assertEqual(report["auto_redirects"], 0)
            self.assertEqual(read_review_state(out, "dj:nova"), "needs_review")
            self.assertEqual(report["review_candidates"], 1)

    def test_unmatched_profile_remains_new_canonical_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "MAXXI", "maxxi", "昆明"),
                incoming=("dj:newcomer", "Newcomer", "newcomer", "杭州"),
            )
            out = root / "identity.sqlite"

            report = build_redirects(source, out)

            self.assertEqual(report["new_canonical"], 1)
            self.assertEqual(read_review_state(out, "dj:newcomer"), "new_canonical")
            self.assertEqual(report["classified_profiles"], 1)

    def test_repeated_build_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "MAXXI", "maxxi", "昆明"),
                incoming=("dj:maxxi", "MAXXI", "maxxi", ""),
                extra=("dj:2222222222222222", "Solo", "solo", "北京"),
            )
            out = root / "identity.sqlite"

            first = build_redirects(source, out)
            second = build_redirects(source, out)

            self.assertEqual(first["classification_digest"], second["classification_digest"])
            self.assertEqual(first["input_digest"], second["input_digest"])
            self.assertEqual(read_redirect(out, "dj:maxxi"), "dj:1111111111111111")

    def test_only_explicitly_approved_plan_overrides_city_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "NOVA", "nova", "上海"),
                incoming=("dj:nova", "NOVA", "nova", "成都"),
            )
            plan = root / "plan.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "action": "merge_candidate",
                        "canonical_id": "dj:1111111111111111",
                        "merged_id": "dj:nova",
                        "apply_allowed_by_planner": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rejected = root / "rejected.sqlite"
            build_redirects(source, rejected, accepted_entity_plan=plan)
            self.assertIsNone(read_redirect(rejected, "dj:nova"))
            self.assertEqual(read_review_state(rejected, "dj:nova"), "needs_review")

            plan.write_text(
                json.dumps(
                    {
                        "action": "merge_candidate",
                        "canonical_id": "dj:1111111111111111",
                        "merged_id": "dj:nova",
                        "apply_allowed_by_planner": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            accepted = root / "accepted.sqlite"
            report = build_redirects(source, accepted, accepted_entity_plan=plan)
            self.assertEqual(read_redirect(accepted, "dj:nova"), "dj:1111111111111111")
            self.assertEqual(report["accepted_plan_redirects"], 1)


if __name__ == "__main__":
    unittest.main()
