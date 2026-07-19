# ATLAS static/online generation handshake

Date: 2026-07-19

## Decision

ATLAS artifacts that are mixed at runtime must carry the same top-level public
`datasetId`. The identifier is not a local path and is not a mutable pointer.

- Preferred release usage: let the triplet builder derive one immutable
  `datasetId` from its frozen SQLite snapshot. `--dataset-id` is only an
  optional expected-value guard; it cannot rename a snapshot.
- Standalone default: `atlas-sha256-<main database SHA256>`.
- `atlas_index.json.gz` and `atlas_neighborhood.json.gz` are compatible only
  when both identifiers are present and equal.
- Missing or mismatched identifiers fail closed. Index-only artist data remains
  available, but neighborhood-derived similar DJs, resident venues, paths, and
  neighborhood expansion are not mixed in.

## Public response contract

`artist`, `path`, and `neighborhood` responses expose only a whitelisted
generation object:

```json
{
  "datasetId": "atlas-sha256-...",
  "subjectCount": 0,
  "profileCount": 0,
  "nodeCount": 0,
  "relationCount": 0,
  "neighborhoodSubjectCount": 0,
  "edgeCount": 0,
  "perSubjectLimit": 0
}
```

Local database paths, temporary-directory paths, source filenames, and build
machine identity are never copied into this public object.

## Export and deployment flow

The following source tools participate in one handshake:

- `tools/atlas_rebuild/build_atlas_serving_triplet.py`
- `tools/atlas_rebuild/export_mp_starmap_from_miniapp.py`
- `tools/atlas_rebuild/export_mp_starmap_bundle.py`
- `tools/atlas_rebuild/export_v2_miniapp_index.py`
- `tools/atlas_rebuild/export_miniapp_neighborhood_bundle.py`
- `tools/atlas_rebuild/build_neighbor_bundle_from_miniapp.py`
- `tools/atlas_rebuild/build_v2_serving_readmodel.py`
- `tools/stage7_rewrite/scripts/export_atlas_core_to_miniapp_index.py`

The last four files were recovered from the dirty discovery tree because the
CloudRun bake script already referenced the miniapp neighborhood builder but the
clean branch did not contain it or its dependencies.

`services/weekly_activity_cloudrun/scripts/bake_and_deploy.py` reads the active
`atlas_index.json.gz` identifier and passes it explicitly to the neighborhood
builder. An absent or malformed identifier blocks the rebuild instead of
publishing a mixed generation.

The repository command that regenerates and verifies the three routes is now:

```powershell
python tools\atlas_rebuild\build_atlas_serving_triplet.py `
  --miniapp-db "<current-atlas_miniapp.sqlite>" `
  --out-dir "F:\DevData\HuaidjRuntime\state\candidates\atlas\<new-generation>"
```

An absolute, new, repository-external `--out-dir` is mandatory. An optional
`--dataset-id` must exactly equal the snapshot-derived identifier or the build
fails closed. There is no deploy or pointer-change mode. The command first checks
the SQLite table/column and internal identity contracts. The preferred current
route derives the static graph, v5 index, and neighborhood from the same
`atlas_miniapp.sqlite`; it does not mix in the separately managed AtlasV2
candidate. It generates all artifacts in a sibling temporary directory and
exposes the requested candidate directory only after dataset ID, schema,
JSON/CommonJS parity, subject referential integrity, counts, local-path leak
checks, and artifact SHA256 checks all pass. The final
`atlas_triplet_manifest.json` contains no local paths and records
`productionWriteExecuted=false` and `deployExecuted=false`.
Input files and generator source files are hashed before and after generation;
any concurrent change aborts the candidate. Gzip mtimes are fixed to zero so a
rebuild from the same immutable inputs is byte-reproducible.

The optional enriched route accepts `--v2` and `--serving` only as a pair. It
requires the v2 and miniapp subject-ID sets to be identical and verifies all
serving graph references before generation. Because those role databases are
backed up sequentially, every role must either expose the same embedded
upstream generation marker (`upstream_generation_id`, `source_generation_id`,
`generation_id`, `release_id`, `dataset_id`, or `build_id`) or the operator must
pass `--frozen-release-id <immutable-release>`. In both cases the builder keeps
one read-only connection open per role, checks SQLite `data_version` and the
marker before and after every role backup, and validates the marker inside each
snapshot. Any intervening commit or marker drift removes the temporary build
and exposes no candidate. The historical June V2 databases fail the identity
gate and cannot silently replace the current hash-ID index.

Relying on each exporter's SHA-derived default independently remains forbidden
because the static/index exports and the neighborhood export read different
database files.

The mini-program star map compares its bundled `datasetId` with every online
artist-inspector, neighborhood, and path response. Missing or mismatched online
identity is ignored and the bundled local graph remains authoritative.

## 2026-07-19 audit finding and release gate

The pre-existing live pair parsed successfully but had no `datasetId`; its
neighborhood generation also contained a Windows temporary SQLite path. These
legacy artifacts are discovery evidence, not acceptable release artifacts under
the new contract. They must be regenerated as one named generation before a
backend or mini-program release. The code change itself did not rewrite the live
pair, deploy CloudRun, upload the mini-program, or change a serving pointer.

## Verification

Passing focused checks:

```powershell
python tools/atlas_rebuild/export_mp_starmap_bundle.py --selftest
python tools/atlas_rebuild/export_miniapp_neighborhood_bundle.py --selftest
python tools/atlas_rebuild/export_v2_miniapp_index.py --selftest
python tools/atlas_rebuild/build_neighbor_bundle_from_miniapp.py --selftest
python -m pytest tools/atlas_rebuild/test_build_atlas_serving_triplet.py -q
python services/weekly_activity_cloudrun/tests/selftest_atlas_bake_dataset_handshake.py
node --test services/weekly_activity_cloudrun/tests/atlasDatasetHandshake.test.mjs
node --test services/weekly_activity_cloudrun/tests/atlasNeighborhood.test.mjs
node --test services/weekly_activity_cloudrun/tests/miniappAtlasApi.test.mjs
node --test apps/weekly_activity_miniprogram/tests/atlas-starmap-dataset-handshake.test.cjs
node --test apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs
```

The synthetic backend test covers matching, mismatching, and missing IDs across
both artist lookup forms, path, and neighborhood. It also injects a Windows Temp
source path into the raw neighborhood fixture and proves it is absent from the
public response.

The real single-source candidate built by this command is recorded in
`ATLAS_TRIPLET_INPUT_PREFLIGHT_20260719.md`. It remains an external candidate;
no CloudRun data path, mini-program source bundle, or serving pointer was
changed.
