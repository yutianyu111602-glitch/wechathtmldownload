#!/usr/bin/env python3
"""Stable, public identity for one coherent ATLAS serving generation."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def validate_dataset_id(value: str) -> str:
    dataset_id = str(value or "").strip()
    if not DATASET_ID_RE.fullmatch(dataset_id):
        raise ValueError(
            "dataset_id must be 8-128 public ASCII characters "
            "using letters, digits, dot, underscore, colon, or hyphen"
        )
    return dataset_id


def file_sha256(path: Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_dataset_id(main_db_path: Path, explicit: str | None = None) -> str:
    if explicit:
        return validate_dataset_id(explicit)
    return validate_dataset_id(f"atlas-sha256-{file_sha256(Path(main_db_path))}")
