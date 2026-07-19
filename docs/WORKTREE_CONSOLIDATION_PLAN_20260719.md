# HUAIDJ Git worktree consolidation plan — 2026-07-19

Status: planned, not executed.

This plan follows the full read-only audit at:

`F:\DevData\HuaidjRuntime\state\reports\git_worktree_audit_20260719\audit-20260719-165704`

No `prune`, `remove`, `reset`, `clean`, `checkout`, `switch`, branch deletion, or file move was performed during the audit.

## Target authority model

The repository should keep four explicit layers:

1. **Dirty discovery evidence** — `F:\code\githubstar\wechathtmldownload`. Preserve it in place; it is not a deploy source.
2. **Clean integration authority** — `F:\DevData\HuaidjRuntime\build\weekly-visibility-20260719` until the current recovery branch is superseded.
3. **Immutable release worktrees** — detached, clean, path prefix equal to actual commit, locked after runtime activation.
4. **Public-production/runtime tuple** — an explicit Hermes job/script/config tuple pointing to exactly one immutable release. Runtime authority must never be inferred from a folder name.

Atlas and DB2 feature branches remain protected donor/history worktrees until their changes are reconciled; they are not runtime authority.

## Non-negotiable gates

A worktree can be removed only when all of these are true:

- its exact current path, actual `HEAD`, branch/detached state, lock state, and clean state were re-audited;
- it has zero staged, unstaged, untracked, and conflicted paths;
- every commit is reachable from a verified remote ref, tag, or verified external Git bundle;
- no running process, Hermes job, scheduled task, launcher, registry tuple, service config, report pointer, or deployment script references its path;
- any generated runtime evidence was copied to an external evidence directory with hashes;
- the active runtime canary and rollback release remain available;
- the exact path is named individually and the user has approved the consolidation batch.

Never use a wildcard, computed broad root, `git clean`, or `git reset` for this work.

## Phase 1 — protect unique history

Do this before branch reconciliation or worktree removal.

1. Re-run the read-only inventory and compare it with `worktree_inventory.json`.
2. Create an external bundle containing all important local and rescue refs, then verify it. Example commands for a future approved run:

```powershell
$repo = 'F:\code\githubstar\wechathtmldownload'
$bundle = 'F:\DevData\HuaidjRuntime\state\backups\git\wechathtmldownload-worktrees-20260719.bundle'
git -C $repo bundle create $bundle --branches --tags
git -C $repo bundle verify $bundle
```

3. Protect the two commits on `wip/rescue-20260605-160743`, the 60-commit DB2 branch, the one-commit readiness branch, and both existing rescue refs on a verified remote or a second verified bundle.
4. Preserve dirty content independently before touching its worktree metadata. The main discovery tree and DB2 worktree must receive file-level inventories and backups; a Git bundle does not include untracked files.

Candidate future pushes, only after credential and secret-safe review:

```powershell
git -C 'F:\code\githubstar\wechathtmldownload' push origin wip/rescue-20260605-160743
git -C 'F:\code\githubstar\wechathtmldownload' push -u origin codex/wechathtmldownload-db2-weapons-containers
git -C 'F:\code\githubstar\wechathtmldownload' push -u origin local/sanji-readiness-fix-20260718
git -C 'F:\code\githubstar\wechathtmldownload' push origin refs/heads/rescue/orphan-cbm-ignore-20260719:refs/heads/rescue/orphan-cbm-ignore-20260719
git -C 'F:\code\githubstar\wechathtmldownload' push origin refs/heads/rescue/orphan-openclaw-loop-state-20260719:refs/heads/rescue/orphan-openclaw-loop-state-20260719
```

## Phase 2 — reconcile branch history

1. Finish and commit the current integration work before merging any donor history.
2. Reconcile `local/pipeline-recovery-20260718` into the active line. Its three exclusive commits are documentation-only:

   - `92f2aa31834b90061729bd5cc8fc2f552b4794d4` — clarify final recovery evidence
   - `bf1c97b4aa33c1ec655ebf5faa2eba912e66b14c` — record Hermes latest-main canary boundary
   - `744abf57e3ff18e227a9ede82a0cd39e9d384f83` — record final Hermes canary review

   Review their diff against current documentation, then cherry-pick or manually integrate them. Do not retire the worktree until the resulting content is verified.
3. Reconcile the readiness fix commit `2ba83f9a...` into the active pipeline or explicitly retain it as a protected maintenance branch.
4. Treat the DB2 branch as a separate project stream. Do not merge its 60 commits merely to reduce worktree count; first audit scope, tests, dependencies, and desired product boundary.
5. Treat `codex/atlas-canonical-serving` as a clean donor. Remove its worktree only after the active Atlas generation-handshake implementation is proven to contain every required change.

## Phase 3 — produce a correctly named immutable release

After the active integration branch is clean, reviewed, tested, committed, and pushed:

```powershell
$repo = 'F:\code\githubstar\wechathtmldownload'
$sha = git -C 'F:\DevData\HuaidjRuntime\build\weekly-visibility-20260719' rev-parse HEAD
$short = $sha.Substring(0, 12)
$release = "F:\DevData\HuaidjRuntime\releases\$short-weekly-visibility-20260719"
git -C $repo worktree add --detach $release $sha
git -C $release status --porcelain=v2
git -C $release rev-parse HEAD
```

Before executing, resolve and verify that `$release` is a new child of the exact releases directory. Do not overwrite an existing path. Run release tests from the detached release, not the dirty integration worktree.

After Hermes cutover and canaries prove that the new release is the active tuple, lock it:

```powershell
git -C 'F:\code\githubstar\wechathtmldownload' worktree lock --reason 'active Hermes immutable release' 'F:\DevData\HuaidjRuntime\releases\<exact-new-release>'
```

Keep `0cf5794-pipeline-20260718` as the rollback release until at least one later successful full cycle and an explicit retention decision.

## Phase 4 — prove runtime references are absent

For each candidate path, inspect references without printing secrets:

```powershell
git -C 'F:\code\githubstar\wechathtmldownload' worktree list --porcelain
git -C '<exact-candidate-path>' status --porcelain=v2 --branch --untracked-files=all
git -C 'F:\code\githubstar\wechathtmldownload' for-each-ref --contains='<exact-head>' '--format=%(refname)'
git -C 'F:\code\githubstar\wechathtmldownload' worktree prune --dry-run --verbose
```

Also check sanitized release-path basenames in Hermes jobs, gateway scripts/config, scheduled tasks, process command lines, service config, deployment scripts, and current/rollback pointers. Record only path matches and owners; do not copy tokens or environment values into the report.

## Phase 5 — handle dirty release evidence

`603775c-pipeline-20260718` is not a clean immutable release because it contains:

`tools/stage7_rewrite/reports/release_guard_current_package_quality_probe/release_package_quality_gate.json`

Hash and copy that file to the external report/evidence store, record its provenance, then re-audit the worktree. Do not delete or clean it in place.

## Phase 6 — exact-path consolidation candidates

Only after Phases 1–5, consider exact removals in this order:

1. `C:\code\.worktrees\wechathtmldownload\20260712-atlas-canonical-serving`, after Atlas reconciliation.
2. Clean intermediate detached releases whose paths are listed as `clean_redundant_candidate` in the inventory and have zero live references.
3. `c8196bdc-pipeline-20260718` only after its three documentation commits are integrated and its misleading path is no longer referenced.
4. `readiness-fix-20260718` only after its commit is remote/bundle protected and reconciled.

The main discovery tree, DB2 worktree, active integration worktree, active Hermes release, rollback release, and any dirty worktree are excluded.

For a future approved exact removal, use one literal path at a time and immediately re-audit:

```powershell
$repo = 'F:\code\githubstar\wechathtmldownload'
$candidate = '<one exact, pre-verified worktree path>'
git -C $candidate status --porcelain=v2 --branch --untracked-files=all
git -C $repo worktree remove -- $candidate
git -C $repo worktree list --porcelain
git -C $repo fsck --full
```

Never add `--force` to the removal command. If Git refuses, stop and investigate.

## Completion criteria

- The active integration branch is clean, reviewed, tested, pushed, and represented by one correctly named detached release.
- Hermes points only to that immutable release; the prior good release remains an explicit rollback.
- Every remaining dirty or unique-history worktree has an explicit owner and purpose.
- Every removed worktree passed all gates and has an evidence record containing path, HEAD, reachability, runtime-reference result, and removal time.
- `git worktree list --porcelain`, branch reachability, bundle verification, and `git fsck --full` are clean after the approved consolidation batch.
- No rescue ref was deleted or rewritten.
