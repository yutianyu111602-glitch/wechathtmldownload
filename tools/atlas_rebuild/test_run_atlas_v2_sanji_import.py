"""Control-plane regression checks for the Sanji -> Atlas v2 orchestrator."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import run_atlas_v2_sanji_import as orchestrator
from merge_stage4_shard_into_base import merge

promote_seen_tokens_checkpoint = orchestrator.promote_seen_tokens_checkpoint

NIGHTLY_LAUNCHER = Path(os.environ.get("HERMES_HOME", r"F:\DevData\Hermes")) / (
    "scripts/huaidj/atlas_v2_sanji_import_nightly.py"
)


def test_canonical_pipeline_order_contract() -> None:
    expected = [
        "merge_shard",
        "build_dj_identity",
        "build_venue_identity",
        "phase2_repair",
        "phase3_canonical",
        "adjudicate_deterministic",
        "adjudicate_llm",
        "phase3_rebuild_with_decisions",
        "materialize_canonical_serving",
        "canonical_gate",
        "advance_checkpoint",
    ]

    assert orchestrator.CANONICAL_PIPELINE_ORDER == expected
    assert orchestrator.ordered_subset(orchestrator.CANONICAL_PIPELINE_ORDER, expected)


def test_optional_historical_geo_does_not_block_clean_clone() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_missing_geo_") as td:
        missing = Path(td) / "historical_venue_geo.json"
        assert orchestrator.optional_existing_path(missing) is None

        present = Path(td) / "historical_venue_geo.json"
        present.write_text("{}", encoding="utf-8")
        assert orchestrator.optional_existing_path(present) == present


def test_checkpoint_readiness_fails_closed_on_materialize_or_gate_failure() -> None:
    successful_steps = [
        {"name": name, "returncode": 0}
        for name in orchestrator.CANONICAL_PIPELINE_ORDER
        if name != "advance_checkpoint"
    ]

    assert orchestrator.canonical_pipeline_ready(successful_steps, {"pass": True})

    materialize_failed = [dict(step) for step in successful_steps]
    next(step for step in materialize_failed if step["name"] == "materialize_canonical_serving")[
        "returncode"
    ] = 2
    assert not orchestrator.canonical_pipeline_ready(materialize_failed, {"pass": True})

    gate_missing = [step for step in successful_steps if step["name"] != "canonical_gate"]
    assert not orchestrator.canonical_pipeline_ready(gate_missing, {"pass": True})
    assert not orchestrator.canonical_pipeline_ready(successful_steps, {"pass": False})


def test_default_base_fails_closed_without_cumulative_state() -> None:
    assert hasattr(orchestrator, "resolve_base_serving_db"), (
        "orchestrator must resolve the nightly base from cumulative state instead of a static snapshot"
    )
    with tempfile.TemporaryDirectory(prefix="atlas_cumulative_state_missing_") as td:
        root = Path(td)
        checkpoint = root / "seen_tokens.txt"
        checkpoint.write_text("token_a\n", encoding="utf-8")
        missing_state = root / "latest_cumulative_candidate.json"
        try:
            orchestrator.resolve_base_serving_db(None, missing_state, checkpoint)
        except SystemExit as exc:
            assert "cumulative candidate state not found" in str(exc)
        else:
            raise AssertionError("missing cumulative state must fail closed")


def test_default_base_loads_candidate_bound_to_current_checkpoint() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_cumulative_state_valid_") as td:
        root = Path(td)
        candidate = root / "candidate.sqlite"
        candidate.write_bytes(b"candidate")
        checkpoint = root / "seen_tokens.txt"
        checkpoint.write_text("token_a\n", encoding="utf-8")
        state_file = root / "latest_cumulative_candidate.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": "atlas_v2.cumulative_candidate_state.v1",
                    "candidate_db": str(candidate),
                    "checkpoint_path": str(checkpoint),
                    "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    "checkpoint_count": 1,
                }
            ),
            encoding="utf-8",
        )

        try:
            resolved = orchestrator.resolve_base_serving_db(None, state_file, checkpoint)
        except SystemExit as exc:
            raise AssertionError("valid cumulative state must resolve its candidate") from exc
        assert resolved == candidate


def test_default_base_rejects_checkpoint_sha_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_cumulative_state_drift_") as td:
        root = Path(td)
        candidate = root / "candidate.sqlite"
        candidate.write_bytes(b"candidate")
        checkpoint = root / "seen_tokens.txt"
        checkpoint.write_text("token_new\n", encoding="utf-8")
        state_file = root / "latest_cumulative_candidate.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": "atlas_v2.cumulative_candidate_state.v1",
                    "candidate_db": str(candidate),
                    "checkpoint_path": str(checkpoint),
                    "checkpoint_sha256": hashlib.sha256(b"token_old\n").hexdigest(),
                    "checkpoint_count": 1,
                }
            ),
            encoding="utf-8",
        )
        try:
            orchestrator.resolve_base_serving_db(None, state_file, checkpoint)
        except SystemExit as exc:
            assert "checkpoint SHA mismatch" in str(exc)
        else:
            raise AssertionError("checkpoint drift must fail closed")


def test_promote_cumulative_candidate_state_is_atomic_and_checkpoint_bound() -> None:
    assert hasattr(orchestrator, "promote_cumulative_candidate_state"), (
        "successful checkpointed runs must publish their cumulative candidate state"
    )
    with tempfile.TemporaryDirectory(prefix="atlas_cumulative_state_promote_") as td:
        root = Path(td)
        candidate = root / "run" / "merged_base.sqlite"
        candidate.parent.mkdir()
        candidate.write_bytes(b"candidate")
        checkpoint = root / "state" / "seen_tokens.txt"
        checkpoint.parent.mkdir()
        checkpoint.write_text("token_a\ntoken_b\n", encoding="utf-8")
        state_file = root / "state" / "latest_cumulative_candidate.json"

        state = orchestrator.promote_cumulative_candidate_state(
            candidate,
            checkpoint,
            state_file,
            candidate.parent,
        )

        readback = json.loads(state_file.read_text(encoding="utf-8"))
        assert readback == state
        assert readback["candidate_db"] == str(candidate)
        assert readback["checkpoint_count"] == 2
        assert readback["checkpoint_sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        assert candidate.read_bytes() == b"candidate"
        assert not list(state_file.parent.glob(".latest_cumulative_candidate.json.tmp-*"))


def test_checkpoint_and_candidate_state_promote_as_one_success_path() -> None:
    assert hasattr(orchestrator, "promote_checkpoint_and_candidate_state"), (
        "checkpoint promotion must also publish the matching cumulative candidate"
    )
    with tempfile.TemporaryDirectory(prefix="atlas_cumulative_finalize_") as td:
        root = Path(td)
        run_dir = root / "run"
        run_dir.mkdir()
        candidate = run_dir / "merged_base.sqlite"
        candidate.write_bytes(b"candidate")
        run_checkpoint = run_dir / "seen_tokens_updated.txt"
        run_checkpoint.write_text("token_a\ntoken_b\n", encoding="utf-8")
        shared_checkpoint = root / "shared" / "seen_tokens_latest.txt"
        shared_checkpoint.parent.mkdir()
        shared_checkpoint.write_text("token_a\n", encoding="utf-8")
        state_file = root / "latest_cumulative_candidate.json"

        state = orchestrator.promote_checkpoint_and_candidate_state(
            run_checkpoint,
            shared_checkpoint,
            candidate,
            state_file,
            run_dir,
        )

        assert shared_checkpoint.read_text(encoding="utf-8") == "token_a\ntoken_b\n"
        assert state["candidate_db"] == str(candidate)
        assert orchestrator.resolve_base_serving_db(None, state_file, shared_checkpoint) == candidate


def test_checkpoint_is_restored_when_candidate_state_promotion_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_cumulative_finalize_rollback_") as td:
        root = Path(td)
        run_dir = root / "run"
        run_dir.mkdir()
        candidate = run_dir / "canonical.sqlite"
        candidate.write_bytes(b"candidate")
        run_checkpoint = run_dir / "seen_tokens_updated.txt"
        run_checkpoint.write_text("token_a\ntoken_b\n", encoding="utf-8")
        shared_checkpoint = root / "seen_tokens_latest.txt"
        shared_checkpoint.write_text("token_a\n", encoding="utf-8")
        state_file = root / "latest_cumulative_candidate.json"
        state_file.write_text('{"previous":true}\n', encoding="utf-8")

        original = orchestrator.promote_cumulative_candidate_state

        def fail_state_promotion(*_args, **_kwargs):
            raise OSError("synthetic state write failure")

        orchestrator.promote_cumulative_candidate_state = fail_state_promotion
        try:
            try:
                orchestrator.promote_checkpoint_and_candidate_state(
                    run_checkpoint,
                    shared_checkpoint,
                    candidate,
                    state_file,
                    run_dir,
                )
            except OSError as exc:
                assert "synthetic state write failure" in str(exc)
            else:
                raise AssertionError("state promotion failure must propagate")
        finally:
            orchestrator.promote_cumulative_candidate_state = original

        assert shared_checkpoint.read_text(encoding="utf-8") == "token_a\n"
        assert state_file.read_text(encoding="utf-8") == '{"previous":true}\n'


def test_second_delta_merges_on_first_candidate_from_cumulative_state() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_two_delta_cumulative_") as td:
        root = Path(td)

        def create_db(path: Path, event_id: str | None = None, token: str | None = None) -> None:
            con = sqlite3.connect(path)
            con.executescript(
                """
                CREATE TABLE performance_event (event_id TEXT PRIMARY KEY, event_title TEXT, starts_at TEXT);
                CREATE TABLE dj_event (dj_id TEXT, event_id TEXT, starts_at TEXT, PRIMARY KEY (dj_id, event_id));
                CREATE TABLE evidence_ref (source_ref_id TEXT PRIMARY KEY, source_title TEXT);
                CREATE TABLE dj_profile (dj_id TEXT PRIMARY KEY, display_name TEXT);
                CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT);
                """
            )
            con.execute("INSERT INTO build_metadata VALUES ('generated_at', '2026-05-25T00:00:00')")
            if event_id and token:
                con.execute("INSERT INTO performance_event VALUES (?, ?, '2026-07-10')", (event_id, event_id))
                con.execute("INSERT INTO dj_event VALUES ('dj1', ?, '2026-07-10')", (event_id,))
                con.execute("INSERT INTO evidence_ref VALUES (?, ?)", (token, token))
                con.execute("INSERT OR IGNORE INTO dj_profile VALUES ('dj1', 'DJ One')")
            con.commit()
            con.close()

        base = root / "base.sqlite"
        shard_one = root / "shard_one.sqlite"
        shard_two = root / "shard_two.sqlite"
        create_db(base)
        create_db(shard_one, "evt1", "token_a")
        create_db(shard_two, "evt2", "token_b")

        candidate_one = root / "candidate_one.sqlite"
        merge(base, shard_one, candidate_one)
        checkpoint = root / "seen_tokens.txt"
        checkpoint.write_text("token_a\n", encoding="utf-8")
        state_file = root / "latest_cumulative_candidate.json"
        orchestrator.promote_cumulative_candidate_state(candidate_one, checkpoint, state_file, root / "run_one")

        candidate_two = root / "candidate_two.sqlite"
        cumulative_base = orchestrator.resolve_base_serving_db(None, state_file, checkpoint)
        merge(cumulative_base, shard_two, candidate_two)

        con = sqlite3.connect(candidate_two)
        tokens = {row[0] for row in con.execute("SELECT source_ref_id FROM evidence_ref")}
        events = {row[0] for row in con.execute("SELECT event_id FROM performance_event")}
        con.close()
        assert tokens == {"token_a", "token_b"}
        assert events == {"evt1", "evt2"}


def test_promote_seen_tokens_checkpoint_replaces_target_and_keeps_run_artifact() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_checkpoint_promote_") as td:
        root = Path(td)
        candidate = root / "run" / "seen_tokens_updated.txt"
        target = root / "state" / "seen_tokens_latest.txt"
        candidate.parent.mkdir()
        target.parent.mkdir()
        candidate.write_text("new_a\nnew_b\n", encoding="utf-8")
        target.write_text("old\n", encoding="utf-8")

        promote_seen_tokens_checkpoint(candidate, target)

        assert target.read_text(encoding="utf-8") == "new_a\nnew_b\n"
        assert candidate.read_text(encoding="utf-8") == "new_a\nnew_b\n"
        assert not list(target.parent.glob(".seen_tokens_latest.txt.tmp-*"))


def test_eight_hour_import_lock_remains_fail_closed() -> None:
    spec = importlib.util.spec_from_file_location("atlas_v2_sanji_import_nightly", NIGHTLY_LAUNCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory(prefix="atlas_import_lock_") as td:
        lock = Path(td) / ".atlas_v2_import.lock"
        lock.write_text("active-run\n", encoding="utf-8")
        eight_hours_ago = time.time() - (8 * 3600)
        os.utime(lock, (eight_hours_ago, eight_hours_ago))
        original_lock = module.LOCK_PATH
        module.LOCK_PATH = lock
        try:
            assert module._lock_is_stale() is False
        finally:
            module.LOCK_PATH = original_lock


def test_nightly_launcher_refreshes_primary_and_failure_only_fallback_credentials() -> None:
    source = NIGHTLY_LAUNCHER.read_text(encoding="utf-8")

    assert '"DEEPSEEK_API_KEY"' in source
    assert '"DASHSCOPE_API_KEY"' in source
    assert '"MIMO_API_KEY"' in source


def test_orchestrator_has_failure_only_online_vision_fallback() -> None:
    source = Path(orchestrator.__file__).read_text(encoding="utf-8")

    assert 'default="vl_direct_router"' in source
    assert 'default="qwen3.6-plus"' in source
    assert '"stage2_extract_vision_fallback"' in source
    assert '"--poster-candidate-fallback-count"' in source
    assert "if not extraction_gate[\"gate_pass\"]" in source


def test_extraction_completion_gate_rejects_missing_and_failed_rows() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_extraction_gate_") as td:
        root = Path(td)
        clean_db = root / "clean.sqlite"
        extraction_db = root / "extractions.sqlite"
        clean = sqlite3.connect(clean_db)
        clean.execute("CREATE TABLE clean (token TEXT PRIMARY KEY, route TEXT)")
        clean.executemany(
            "INSERT INTO clean VALUES (?, ?)",
            [("ok", "text_complete"), ("failed", "needs_vision"), ("missing", "needs_vision"), ("skip", "skip")],
        )
        clean.commit()
        clean.close()
        extracted = sqlite3.connect(extraction_db)
        extracted.execute("CREATE TABLE extractions (token TEXT PRIMARY KEY, status TEXT, valid INTEGER, error TEXT)")
        extracted.executemany(
            "INSERT INTO extractions VALUES (?, ?, ?, ?)",
            [("ok", "extracted", 1, ""), ("failed", "failed", 0, "ocr empty")],
        )
        extracted.commit()
        extracted.close()

        report = orchestrator.extraction_completion_report(clean_db, extraction_db)

        assert report["gate_pass"] is False
        assert report["expected_count"] == 3
        assert report["missing_count"] == 1
        assert report["invalid_count"] == 1
        assert report["invalid"][0]["status"] == "failed"


def test_extraction_completion_gate_accepts_valid_terminal_rows() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_extraction_gate_ok_") as td:
        root = Path(td)
        clean_db = root / "clean.sqlite"
        extraction_db = root / "extractions.sqlite"
        clean = sqlite3.connect(clean_db)
        clean.execute("CREATE TABLE clean (token TEXT PRIMARY KEY, route TEXT)")
        clean.executemany("INSERT INTO clean VALUES (?, ?)", [("a", "text_complete"), ("b", "needs_vision")])
        clean.commit()
        clean.close()
        extracted = sqlite3.connect(extraction_db)
        extracted.execute("CREATE TABLE extractions (token TEXT PRIMARY KEY, status TEXT, valid INTEGER, error TEXT)")
        extracted.executemany(
            "INSERT INTO extractions VALUES (?, ?, ?, ?)",
            [("a", "extracted", 1, ""), ("b", "classification_skip", 1, "")],
        )
        extracted.commit()
        extracted.close()

        report = orchestrator.extraction_completion_report(clean_db, extraction_db)

        assert report["gate_pass"] is True
        assert report["missing_count"] == 0
        assert report["invalid_count"] == 0


if __name__ == "__main__":
    test_canonical_pipeline_order_contract()
    test_checkpoint_readiness_fails_closed_on_materialize_or_gate_failure()
    test_default_base_fails_closed_without_cumulative_state()
    test_default_base_loads_candidate_bound_to_current_checkpoint()
    test_default_base_rejects_checkpoint_sha_drift()
    test_promote_cumulative_candidate_state_is_atomic_and_checkpoint_bound()
    test_checkpoint_and_candidate_state_promote_as_one_success_path()
    test_checkpoint_is_restored_when_candidate_state_promotion_fails()
    test_second_delta_merges_on_first_candidate_from_cumulative_state()
    test_promote_seen_tokens_checkpoint_replaces_target_and_keeps_run_artifact()
    test_eight_hour_import_lock_remains_fail_closed()
    print("checkpoint promotion regression test OK")
