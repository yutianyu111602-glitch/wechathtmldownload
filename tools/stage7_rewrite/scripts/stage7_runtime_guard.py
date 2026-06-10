"""Runtime guardrails for Stage7 native-heavy Python tasks.

The vector/embedding lane loads torch, sentence-transformers, CUDA, pyarrow,
or adjacent native packages. Python 3.13 has produced access violations on this
machine, so these tasks must fail before importing those native stacks unless
the operator explicitly overrides the guard for a bounded diagnostic run.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any


OVERRIDE_ENV_VARS = (
    "STAGE7_ALLOW_UNSAFE_NATIVE_HEAVY",
    "STAGE7_ALLOW_UNSAFE_GLOBAL_PY313",
)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "allow"}


def _version_tuple(value: Any) -> tuple[int, int, int]:
    return (
        int(getattr(value, "major", value[0] if len(value) > 0 else 0)),
        int(getattr(value, "minor", value[1] if len(value) > 1 else 0)),
        int(getattr(value, "micro", value[2] if len(value) > 2 else 0)),
    )


def runtime_context(
    *,
    env: Mapping[str, str] | None = None,
    version_info: Any | None = None,
    executable: str | None = None,
    prefix: str | None = None,
    base_prefix: str | None = None,
) -> dict[str, Any]:
    values = os.environ if env is None else env
    version = _version_tuple(sys.version_info if version_info is None else version_info)
    resolved_prefix = sys.prefix if prefix is None else prefix
    resolved_base_prefix = getattr(sys, "base_prefix", sys.prefix) if base_prefix is None else base_prefix
    virtual_env = values.get("VIRTUAL_ENV") or ""
    in_venv = bool(virtual_env) or resolved_prefix != resolved_base_prefix
    return {
        "python_version": ".".join(str(part) for part in version),
        "python_major": version[0],
        "python_minor": version[1],
        "python_micro": version[2],
        "python_executable": executable or sys.executable,
        "in_virtualenv": in_venv,
        "virtual_env": virtual_env,
        "prefix": resolved_prefix,
        "base_prefix": resolved_base_prefix,
        "override_enabled": any(_truthy(values.get(name)) for name in OVERRIDE_ENV_VARS),
    }


def enforce_native_heavy_python_guard(
    task_name: str,
    *,
    env: Mapping[str, str] | None = None,
    version_info: Any | None = None,
    executable: str | None = None,
    prefix: str | None = None,
    base_prefix: str | None = None,
) -> dict[str, Any]:
    """Refuse known-unsafe Python runtimes before importing native stacks."""
    context = runtime_context(
        env=env,
        version_info=version_info,
        executable=executable,
        prefix=prefix,
        base_prefix=base_prefix,
    )
    if context["override_enabled"]:
        return context

    reasons: list[str] = []
    if int(context["python_major"]) >= 3 and int(context["python_minor"]) >= 13:
        reasons.append("Python 3.13 is blocked for Stage7 native-heavy vector/embedding tasks")
    if not context["in_virtualenv"]:
        reasons.append("Stage7 native-heavy vector/embedding tasks must run inside a project virtualenv")

    if not reasons:
        return context

    detail = "; ".join(reasons)
    raise SystemExit(
        f"{task_name} refused by Stage7 runtime guard: {detail}. "
        "Use a project venv on Python 3.11/3.12 for torch/sentence-transformers/pyarrow workloads. "
        "For a bounded diagnostic only, set STAGE7_ALLOW_UNSAFE_NATIVE_HEAVY=1."
    )
