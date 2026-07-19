#!/usr/bin/env python3
"""No-network self-test for the bake-time ATLAS generation gate."""

from __future__ import annotations

import gzip
import importlib.util
import json
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bake_and_deploy.py"


def _load_bake_module():
    spec = importlib.util.spec_from_file_location("weekly_bake_dataset_selftest", SCRIPT)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {SCRIPT.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_artifact(path: Path, dataset_id: str | None) -> None:
    payload = {"schemaVersion": "atlas.selftest.v1"}
    if dataset_id:
        payload["datasetId"] = dataset_id
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)


def main() -> None:
    bake = _load_bake_module()
    dataset_id = "atlas-selftest-shared-generation-0001"
    other_id = "atlas-selftest-other-generation-0002"
    previous_data_root = bake.DATA_ROOT
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-bake-handshake-") as tmp:
            root = Path(tmp)
            bake.DATA_ROOT = root
            _write_artifact(root / "atlas_index.json.gz", dataset_id)
            _write_artifact(root / "atlas_neighborhood.json.gz", dataset_id)
            assert bake.regenerate_neighborhood_bundle(False) is True

            _write_artifact(root / "atlas_neighborhood.json.gz", other_id)
            assert bake.regenerate_neighborhood_bundle(False) is False

            _write_artifact(root / "atlas_neighborhood.json.gz", None)
            assert bake.regenerate_neighborhood_bundle(False) is False
    finally:
        bake.DATA_ROOT = previous_data_root
    print("SELFTEST PASS atlas bake dataset handshake")


if __name__ == "__main__":
    main()
