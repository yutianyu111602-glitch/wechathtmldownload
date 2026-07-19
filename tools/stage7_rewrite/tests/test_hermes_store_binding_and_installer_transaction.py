from __future__ import annotations

import contextlib
import copy
import json
import os
import runpy
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"
AUDIT = ROOT / "scripts" / "audit_huaidj_sanji_hermes_contract.py"


@contextlib.contextmanager
def _kernel_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _fake_cron(
    monkeypatch,
    tmp_path: Path,
    *,
    mismatch: bool = False,
    save_failure_after_write: bool = False,
):
    agent = tmp_path / "hermes-runtime"
    module_path = agent / "cron" / "jobs.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# fake cron module\n", encoding="utf-8")

    state = {
        "home": None,
        "jobs": [],
        "save_count": 0,
        "seen_homes": [],
        "lock_count": 0,
    }
    module = types.ModuleType("cron.jobs")
    module.__file__ = str(module_path)

    @contextlib.contextmanager
    def use_cron_store(home):
        previous = state["home"]
        state["home"] = Path(home)
        try:
            yield
        finally:
            state["home"] = previous

    def current_store():
        home = tmp_path / "wrong-home" if mismatch else state["home"]
        return types.SimpleNamespace(jobs_file=Path(home) / "cron" / "jobs.json")

    def load_jobs():
        state["seen_homes"].append(os.environ.get("HERMES_HOME"))
        return copy.deepcopy(state["jobs"])

    @contextlib.contextmanager
    def jobs_lock():
        state["lock_count"] += 1
        lock_path = Path(state["home"]) / "cron" / ".jobs.lock"
        with _kernel_file_lock(lock_path):
            yield

    def save_jobs_unlocked(jobs):
        state["seen_homes"].append(os.environ.get("HERMES_HOME"))
        state["save_count"] += 1
        state["jobs"] = copy.deepcopy(jobs)
        if save_failure_after_write:
            jobs_file = Path(state["home"]) / "cron" / "jobs.json"
            jobs_file.parent.mkdir(parents=True, exist_ok=True)
            jobs_file.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
            raise OSError("injected jobs save failure after write")

    module.use_cron_store = use_cron_store
    module._current_cron_store = current_store
    module.load_jobs = load_jobs
    module._jobs_lock = jobs_lock
    module._save_jobs_unlocked = save_jobs_unlocked
    module.create_job = lambda **kwargs: kwargs
    module.update_job = lambda job_id, changes: {"id": job_id, **changes}
    module.parse_schedule = lambda expr: {"kind": "cron", "expr": expr, "display": expr}
    module.compute_next_run = lambda schedule: f"next:{schedule['expr']}"

    package = types.ModuleType("cron")
    package.__path__ = [str(agent / "cron")]
    monkeypatch.setitem(sys.modules, "cron", package)
    monkeypatch.setitem(sys.modules, "cron.jobs", module)
    return agent, module, state


def test_explicit_home_overrides_stale_parent_and_is_restored(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    agent, _module, state = _fake_cron(monkeypatch, tmp_path)
    stale = tmp_path / "stale-c-home"
    requested = tmp_path / "authoritative-f-home"
    monkeypatch.setenv("HERMES_HOME", str(stale))

    api = namespace["load_api"](requested, agent)
    assert os.environ["HERMES_HOME"] == str(stale)
    assert api.load_jobs() == []
    assert state["seen_homes"] == [str(requested.resolve())]
    assert os.environ["HERMES_HOME"] == str(stale)


def test_store_mismatch_fails_closed_and_restores_parent_env(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    agent, _module, _state = _fake_cron(monkeypatch, tmp_path, mismatch=True)
    stale = tmp_path / "stale-c-home"
    monkeypatch.setenv("HERMES_HOME", str(stale))

    with pytest.raises(RuntimeError, match="cron store mismatch"):
        namespace["load_api"](tmp_path / "authoritative-f-home", agent)
    assert os.environ["HERMES_HOME"] == str(stale)


def test_reconcile_is_one_write_and_second_apply_is_true_noop(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    agent, _module, state = _fake_cron(monkeypatch, tmp_path)
    requested = tmp_path / "authoritative-f-home"
    api = namespace["load_api"](requested, agent)

    first = api.reconcile(namespace["_plan_jobs"], apply=True)
    assert state["save_count"] == 1
    assert state["lock_count"] == 1
    assert len(state["jobs"]) == len(namespace["JOBS"])
    assert all(action["action"] == "create" for action in first)

    saved = copy.deepcopy(state["jobs"])
    second = api.reconcile(namespace["_plan_jobs"], apply=True)
    assert state["save_count"] == 1
    assert state["lock_count"] == 2
    assert state["jobs"] == saved
    assert all(action["action"] == "noop" for action in second)


def test_backup_manifest_contains_verified_hashes_and_restore_actions(tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    home = tmp_path / "hermes"
    jobs_file = home / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text('{"jobs": []}\n', encoding="utf-8")
    one_script = home / "scripts" / "huaidj" / "health_check.py"
    one_script.parent.mkdir(parents=True)
    one_script.write_text("print('old')\n", encoding="utf-8")

    snapshot = namespace["create_backup_snapshot"](home, tmp_path / "backups")
    manifest_path = Path(snapshot["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs_entry = next(row for row in manifest["entries"] if row["target"] == str(jobs_file.resolve()))
    assert jobs_entry["sha256_before"] == jobs_entry["backup_sha256"]
    assert Path(jobs_entry["backup"]).read_bytes() == jobs_file.read_bytes()
    assert jobs_entry["restore_action"] == "copy_backup_to_target"
    missing = next(row for row in manifest["entries"] if not row["existed"])
    assert missing["restore_action"] == "remove_target_if_created"
    assert manifest["requires_gateway_stopped_for_restore"] is True


def _managed_file_state(namespace, home: Path) -> dict[str, bytes | None]:
    return {
        str(path): path.read_bytes() if path.is_file() else None
        for path in namespace["_managed_target_paths"](home)
    }


def test_launcher_write_failure_restores_every_managed_target(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    agent, _module, state = _fake_cron(monkeypatch, tmp_path)
    home = tmp_path / "hermes"
    jobs_file = home / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text('{"jobs": [{"id": "old-job"}]}\n', encoding="utf-8")

    rendered = list(namespace["render_script_templates"](home))
    for index, rel in enumerate(rendered):
        if index == 1:
            continue
        path = home / "scripts" / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"old launcher {index}\n", encoding="utf-8")
    before = _managed_file_state(namespace, home)

    original_write = namespace["_atomic_write_text"]
    launcher_writes = 0

    def fail_third_launcher(path, text):
        nonlocal launcher_writes
        selected = Path(path)
        if home / "scripts" in selected.parents:
            launcher_writes += 1
            if launcher_writes == 3:
                raise OSError("injected third launcher write failure")
        return original_write(selected, text)

    monkeypatch.setitem(namespace["write_scripts"].__globals__, "_atomic_write_text", fail_third_launcher)
    with pytest.raises(namespace["InstallerTransactionError"]) as raised:
        namespace["apply_installation_transaction"](
            hermes_home=home,
            hermes_agent=agent,
            backup_root=tmp_path / "backups",
        )

    assert launcher_writes == 3
    assert raised.value.rollback["ok"] is True, raised.value.rollback
    assert raised.value.rollback["manifest_sha256_verified"] is True
    assert raised.value.rollback["baseline_restored"] is True
    assert state["lock_count"] == 1
    assert _managed_file_state(namespace, home) == before


def test_gateway_update_after_snapshot_waits_until_failed_transaction_restores(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    agent, _module, state = _fake_cron(monkeypatch, tmp_path)
    home = tmp_path / "authoritative-home"
    jobs_file = home / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text(
        json.dumps({"jobs": [{"id": "canonical", "last_run": "old", "next_run": "old-next"}]}),
        encoding="utf-8",
    )
    first_launcher = next(iter(namespace["render_script_templates"](home)))
    launcher_path = home / "scripts" / Path(first_launcher)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text("old launcher\n", encoding="utf-8")

    lock_path = home / "cron" / ".jobs.lock"
    attempting = tmp_path / "gateway-attempting"
    acquired = tmp_path / "gateway-acquired"
    child_code = r"""
import json
import os
import sys
from pathlib import Path
lock_path, jobs_file, attempting, acquired = map(Path, sys.argv[1:])
lock_path.parent.mkdir(parents=True, exist_ok=True)
handle = lock_path.open("a+b")
handle.seek(0, os.SEEK_END)
if handle.tell() == 0:
    handle.write(b"\0")
    handle.flush()
handle.seek(0)
attempting.write_text("1", encoding="utf-8")
if os.name == "nt":
    import msvcrt
    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
else:
    import fcntl
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
try:
    acquired.write_text("1", encoding="utf-8")
    jobs_file.write_text(json.dumps({"jobs": [{"id": "canonical", "last_run": "gateway", "next_run": "gateway-next"}]}), encoding="utf-8")
finally:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()
"""
    holder: dict[str, subprocess.Popen] = {}
    original_backup = namespace["create_backup_snapshot"]
    original_write = namespace["_atomic_write_text"]
    observed = {"gateway_acquired_before_launcher_failure": None}

    def backup_then_start_gateway(hermes_home, backup_root):
        backup = original_backup(hermes_home, backup_root)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child_code,
                str(lock_path),
                str(jobs_file),
                str(attempting),
                str(acquired),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        holder["process"] = process
        deadline = time.monotonic() + 5
        while not attempting.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert attempting.exists(), "gateway fixture did not reach the shared jobs lock"
        time.sleep(0.15)
        return backup

    def fail_first_launcher(path, text):
        selected = Path(path)
        if home / "scripts" in selected.parents:
            observed["gateway_acquired_before_launcher_failure"] = acquired.exists()
            raise OSError("injected launcher failure after snapshot")
        return original_write(selected, text)

    transaction_globals = namespace["apply_installation_transaction"].__globals__
    monkeypatch.setitem(transaction_globals, "create_backup_snapshot", backup_then_start_gateway)
    monkeypatch.setitem(transaction_globals, "_atomic_write_text", fail_first_launcher)
    try:
        with pytest.raises(namespace["InstallerTransactionError"]):
            namespace["apply_installation_transaction"](
                hermes_home=home,
                hermes_agent=agent,
                backup_root=tmp_path / "backups",
            )
        process = holder["process"]
        process.wait(timeout=10)
        assert process.returncode == 0, process.stderr.read() if process.stderr else ""
    finally:
        process = holder.get("process")
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    assert observed["gateway_acquired_before_launcher_failure"] is False
    assert state["lock_count"] == 1
    jobs = json.loads(jobs_file.read_text(encoding="utf-8"))["jobs"]
    assert jobs[0]["last_run"] == "gateway"
    assert jobs[0]["next_run"] == "gateway-next"


def test_jobs_save_failure_restores_launchers_and_jobs(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(INSTALLER), run_name="__test__")
    agent, _module, state = _fake_cron(
        monkeypatch,
        tmp_path,
        save_failure_after_write=True,
    )
    home = tmp_path / "authoritative-f-home"
    jobs_file = home / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True)
    jobs_file.write_text('{"jobs": [{"id": "old-job"}]}\n', encoding="utf-8")
    for index, rel in enumerate(namespace["render_script_templates"](home)):
        path = home / "scripts" / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"old launcher {index}\n", encoding="utf-8")
    before = _managed_file_state(namespace, home)

    with pytest.raises(namespace["InstallerTransactionError"]) as raised:
        namespace["apply_installation_transaction"](
            hermes_home=home,
            hermes_agent=agent,
            backup_root=tmp_path / "backups",
        )

    assert "injected jobs save failure" in str(raised.value.cause)
    assert raised.value.rollback["ok"] is True, raised.value.rollback
    assert raised.value.rollback["manifest_sha256_verified"] is True
    assert raised.value.rollback["baseline_restored"] is True
    assert state["lock_count"] == 1
    assert _managed_file_state(namespace, home) == before


def test_audit_forces_requested_home_and_rejects_wrong_store(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(AUDIT), run_name="__test__")
    agent, _module, state = _fake_cron(monkeypatch, tmp_path)
    requested = tmp_path / "authoritative-f-home"
    stale = tmp_path / "stale-c-home"
    monkeypatch.setenv("HERMES_HOME", str(stale))

    jobs, error = namespace["load_hermes_jobs"](requested, agent)
    assert jobs == []
    assert error == ""
    assert state["seen_homes"] == [str(requested.resolve())]
    assert os.environ["HERMES_HOME"] == str(stale)

    _agent, _module, _state = _fake_cron(monkeypatch, tmp_path / "mismatch", mismatch=True)
    jobs, error = namespace["load_hermes_jobs"](requested, _agent)
    assert jobs == []
    assert "cron store mismatch" in error
    assert os.environ["HERMES_HOME"] == str(stale)
