# ATLAS triplet input preflight — 2026-07-19

## Outcome

The unsafe June-V2 plus July-serving mix is correctly blocked. The current
miniapp authority was then used through the identity-preserving single-source
route, producing a verified external three-route candidate. No production data
write, deploy, mini-program source rewrite, or serving-pointer change was made.

## Discovered current-side inputs

| Role | Path | Bytes | Last write UTC | SHA256 | Contract evidence |
|---|---|---:|---|---|---|
| miniapp | `F:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\atlas_miniapp.sqlite` | 414224384 | 2026-07-11T05:28:59.8293748Z | `10bcede6da38552cb3abc3d6b374ea66b56df4e16f813f9b9e664bc35991772f` | `subject=86589`, `dj_profile=57266`, `dj_collaborator=478526`, `dj_venue=137101` |
| canonical serving candidate | `E:\atlas_v2_import_runs\run_20260718_200513_post_weekly\canonical_serving_candidate.sqlite` | 2609250304 | 2026-07-18T12:12:15.5790295Z | `4e70f214f1eacb6bff57604249007f9fef264e777847163831006cdd71167d7d` | `evidence_ref=135888`, `dj_event=1297511`, `dj_venue_rollup=137101`, `dj_relation_rollup=699800` |

The canonical file is the newest candidate discovered by path/mtime; this
preflight does not promote it or claim that a serving pointer already accepts
it.

## Historical V2 files discovered

| Path | Last write UTC | SHA256 | Subjects | Relations | miniapp overlap | miniapp-only |
|---|---|---|---:|---:|---:|---:|
| `F:\code\githubstar\wechathtmldownload\tools\atlas_rebuild\_sandbox_v2_semantic_filtered_20260621\atlas_serving_v2.sqlite` | 2026-06-21T15:13:46.3270264Z | `243bd8c49e4aa4787112e3778e08b6d2894052e641c4ff2366b7a80fe184ac74` | 77022 | 818167 | 3021 | 83568 |
| `F:\code\githubstar\wechathtmldownload\tools\atlas_rebuild\_sandbox_v2_reconciled_20260621\atlas_serving_v2.sqlite` | 2026-06-21T13:59:41.6399905Z | `a6a971bae89721b11fef32aaba828bc891aa7336e3eda71915bd991d6cae9207` | 77165 | 822602 | 3021 | 83568 |
| `F:\code\githubstar\wechathtmldownload\tools\atlas_rebuild\_serve_20260623\atlas_serving_v2.sqlite` | 2026-06-23T12:43:10.3530929Z | `0c315048978fc1018efafcb0cfe7b20bfd5d37d4609398d32e87eb3a36ce3bb9` | 75304 | 808413 | 3010 | 83579 |

All three files contain the required `subject`, `relation`, and `dj_profile`
tables, but their subject identifiers are overwhelmingly incompatible with the
current miniapp hash-ID generation. They are historical discovery evidence and
must not be used for this release.

## Reproduced fail-closed gate

The newest discovered V2 file was tested with the current-side inputs:

```text
ERROR: v2/miniapp subject identity mismatch: v2=75304 miniapp=86589
intersection=3010 v2_only=72294 miniapp_only=83579
```

The requested candidate path
`F:\DevData\HuaidjRuntime\state\candidates\atlas\preflight-blocked-20260719`
and its parent were both absent after the failure.

## Verified current single-source candidate

Candidate directory:

`F:\DevData\HuaidjRuntime\state\candidates\atlas\triplet-miniapp-10bcede6-20260719-guarded`

Public dataset ID:

`atlas-miniapp-sha256-10bcede6da38552cb3abc3d6b374ea66b56df4e16f813f9b9e664bc35991772f`

The source digest exactly matches the audited current miniapp DB. The generated
manifest reports:

- `sourceMode=miniapp_single_source`;
- index subjects `86589`;
- static graph `240` nodes / `640` edges;
- neighborhood `57676` subjects / `759039` edges;
- neighborhood unknown subjects `0`;
- path leaks `0`;
- `productionWriteExecuted=false` and `deployExecuted=false`.

Primary artifact SHA256 values:

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `atlas_starmap.json` | 57834 | `7246b89f18eefd734913301433557c815eb12b66bca8eb372226d311e19c3a00` |
| `atlas_starmap.js` | 57852 | `d88c17409363fe71ade88606ef323c7d4f29715fbc3945554fb9e8c3ab278380` |
| `atlas_index.json.gz` | 44138519 | `c30e7510702eb53f504cc5d8b7666a159090567368e06aa516540178ac39b157` |
| `atlas_neighborhood.json.gz` | 11305471 | `0fda006eb3a12d903eeb6fa0a4626cc732fc9b88b7ff58e499dbd186b5dbc800` |

The guarded build hashes all inputs and generator source files before and after
generation and aborts if either changes. Gzip mtimes are fixed to zero for
byte-reproducible output. The earlier unguarded smoke candidate at the same
parent with no `-guarded` suffix is retained only as audit evidence and is not
the release input.

For future multi-role V2 builds, sequential SQLite backups are not accepted on
file hashes alone. All role databases must carry one common upstream generation
marker, or the caller must provide an explicit `--frozen-release-id`. Long-lived
read-only guard connections verify `PRAGMA data_version` and generation markers
before and after every backup, so a WAL commit or marker change between role
snapshots fails closed. The preferred current miniapp-only route remains
compatible without this multi-role declaration because all three artifacts are
derived from one SQLite snapshot.

Preflight also records 687 historical event venue IDs that are not canonical
subject IDs. They are retained as event-level legacy aliases and are not graph
endpoints; all `dj_collaborator` and `dj_venue` graph references are canonical.

An independent post-build manifest/digest verifier passed, followed by the real
CloudRun Atlas path test against the external candidate: the index loaded all
`86589` subjects, the neighborhood loaded all `57676` subject buckets, and the
known bidirectional shortest-path cases passed. These are candidate tests, not a
deploy or production-serving claim.

## Required trusted input before enabling the optional V2-enriched route

Provide or regenerate one current, identity-preserving
`atlas_serving_v2.sqlite` that:

- contains the full exporter contract for `subject`, `relation`, and
  `dj_profile`;
- uses exactly the current miniapp subject-ID generation rather than the old
  name-slug IDs;
- has relation endpoints contained in that subject set; and
- is traceable to the accepted canonical/Atlas generation through an immutable
  build report or digest.

The current single-source serving triplet does not require that missing V2
input. A future adapter that mixes `atlas_miniapp.sqlite` with the canonical
AtlasV2 candidate still requires an explicit, audited identity mapping; it was
not improvised here because that would hide an identity migration rather than
repair it.
