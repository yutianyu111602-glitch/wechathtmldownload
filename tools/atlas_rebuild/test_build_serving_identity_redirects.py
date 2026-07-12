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
        CREATE TABLE dj_event (
          dj_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          starts_at TEXT,
          venue_id TEXT,
          source_ref_id TEXT
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
    def test_explicit_plan_can_merge_two_existing_canonical_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "MAXXI", "maxxi", "昆明"),
                incoming=("dj:newcomer", "Newcomer", "newcomer", "杭州"),
                extra=("dj:2222222222222222", "DAUER STATE aka MAXXI", "dauer state aka maxxi", "昆明"),
            )
            plan = root / "plan.jsonl"
            plan.write_text(
                json.dumps(
                    {
                        "action": "merge",
                        "source_dj_id": "dj:2222222222222222",
                        "canonical_dj_id": "dj:1111111111111111",
                        "reason": "source-backed alias",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            out = root / "identity.sqlite"

            report = build_redirects(source, out, accepted_entity_plan=plan)

            self.assertEqual(report["accepted_plan_redirects"], 1)
            self.assertEqual(read_redirect(out, "dj:2222222222222222"), "dj:1111111111111111")

    def test_role_label_pair_with_shared_evidence_collapses_canonical_roots(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "MAXXI", "maxxi", "昆明"),
                incoming=("dj:newcomer", "Newcomer", "newcomer", "杭州"),
                extra=("dj:2222222222222222", "DJ MAXXI", "dj maxxi", "昆明"),
            )
            con = sqlite3.connect(source)
            con.executemany(
                "INSERT INTO dj_event VALUES (?,?,?,?,?)",
                [
                    ("dj:1111111111111111", "event:a", "2026-05-02", "venue:vervo", "src:shared"),
                    ("dj:2222222222222222", "event:b", "2026-05-02", "venue:vervo", "src:shared"),
                ],
            )
            con.commit()
            con.close()
            out = root / "identity.sqlite"

            report = build_redirects(source, out)

            self.assertEqual(report["canonical_role_label_redirects"], 1)
            self.assertEqual(read_redirect(out, "dj:2222222222222222"), "dj:1111111111111111")

    def test_role_label_pair_without_shared_evidence_stays_separate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_identity_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                canonical=("dj:1111111111111111", "MAXXI", "maxxi", "昆明"),
                incoming=("dj:newcomer", "Newcomer", "newcomer", "杭州"),
                extra=("dj:2222222222222222", "DJ MAXXI", "dj maxxi", "昆明"),
            )
            out = root / "identity.sqlite"

            report = build_redirects(source, out)

            self.assertEqual(report["canonical_role_label_redirects"], 0)
            self.assertIsNone(read_redirect(out, "dj:2222222222222222"))

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
