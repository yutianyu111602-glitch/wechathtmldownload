<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Backend-Facing UI Requirements

## Goal

Define the target desktop UI contract for the `wechathtmldownload` PCUI redesign so backend and pipeline work can expose stable projections, commands, and status models that the Electron renderer can consume without guessing business state.

This document is for backend and pipeline design first. It is not a visual style guide.

## Product Classification

- Product type: Windows 11 desktop `Operator Console + Pipeline Workbench + Artifact Manager`
- Runtime model: long-running local desktop sessions, minutes to hours
- Primary user: one power user operating archive, processing, and review flows repeatedly
- Error cost: medium to high because silent partial failure corrupts downstream artifact quality
- UI strategy: projection-driven workbench, not folder-scanning heuristics, not web dashboard

## Non-Goals

- Do not design a landing page, dashboard overview, or marketing shell.
- Do not expose secrets, auth files, cookies, or raw service config in UI.
- Do not let renderer infer readiness, retryability, or quality by scanning folders when a projection exists.
- Do not treat a successful command acceptance as proof that the underlying stage is complete.

## Shell Contract

The redesign should converge on this fixed shell:

```text
titlebar
commandbar
navigation rail + main workspace + right inspector
bottom run console
statusbar
```

### Shell Rules

- `titlebar`: product name, current workspace, global run light only
- `commandbar`: global actions, workspace actions, filter/search, compact counters
- `navigation rail`: fixed workspaces, no overview page
- `main workspace`: table-first workbench, one primary object type per workspace
- `right inspector`: current selection only
- `bottom run console`: activity, failures, system messages
- `statusbar`: one-line summary only

## Workspaces

The UI has five first-class workspaces. Each workspace must map to a stable business object, a stable data source, and explicit user commands.

### 1. Task Bus

Primary object:

- job or batch run

Purpose:

- show current and recent active work across discovery, archive, processing, export, and finalize
- allow stop, resume, open output, jump to failure context

Primary data source:

- live `batch:snapshot`
- `batch:get-latest-snapshot`

Required fields:

- `status`
- `inputRoot`
- `outRoot`
- `startedAt`
- `endedAt`
- `totalItems`
- `queuedCount`
- `runningCount`
- `succeededCount`
- `failedCount`
- `skippedCount`
- `cancelledCount`
- `completedCount`
- `progressRatio`
- `currentFile`
- `currentPhase`
- `items[]`

Renderer rule:

- the UI may format or filter these fields but must not invent additional lifecycle states from folder inspection

### 2. Collection & Accounts

Primary object:

- account

Purpose:

- show discovery health, queue readiness, estimated scale, and account-level failure states

Primary data source:

- `collect:get-state`

Required fields:

- `status`
- `sources.rootDir`
- `sources.prefetchStatusPath`
- `sources.queuePath`
- `summary.totalAccounts`
- `summary.completedAccounts`
- `summary.totalDiscovered`
- `summary.totalEnqueued`
- `summary.readyQueueCount`
- `accounts[].fakeid`
- `accounts[].nickname`
- `accounts[].status`
- `accounts[].estimatedSize`
- `accounts[].lastDiscoveredAt`
- `accounts[].discoveredCount`
- `accounts[].enqueuedCount`
- `accounts[].duplicateCount`
- `accounts[].errorMessage`

Renderer rule:

- if API or discovery state is unavailable, show unknown or unavailable, not fake success

### 3. Archive & Download

Primary object:

- archive bundle or article task

Purpose:

- show archive completeness, asset retention completeness, recoverable failures, and file presence

Primary data source:

- `archive:get-state`
- `audit:get-projection`

Required fields from `archive:get-state`:

- `summary.archive`
- `summary.assets`
- `summary.bundles`
- `items[].token`
- `items[].accountKey`
- `items[].sourceUrl`
- `items[].outDir`
- `items[].archiveStatus`
- `items[].assetStatus`
- `items[].captureComplete`
- `items[].mhtmlComplete`
- `items[].pdfComplete`
- `items[].assetsComplete`
- `items[].imageCount`
- `items[].mediaCount`
- `items[].lastError`
- `items[].files`

Required fields from `audit:get-projection`:

- `stages[].id`
- `stages[].label`
- `stages[].total`
- `stages[].succeeded`
- `stages[].failed`
- `stages[].skipped`
- `stages[].running`
- `stages[].recoverable`
- `stages[].latest_error`

Renderer rule:

- stage badges must reflect projection values only
- recoverability must come from projection, not UI inference

### 4. Process & Export

Primary object:

- article bundle

Purpose:

- show where each article bundle is in the processing chain and what outputs are missing or degraded

Primary data source:

- `process:get-state`
- live snapshot fallback only when the active batch matches the same `outRoot`

Required fields:

- `summary.totalItems`
- `summary.succeededCount`
- `summary.failedCount`
- `summary.partialCount`
- `summary.warningCount`
- `summary.downstreamReadyCount`
- `items[].articleId`
- `items[].token`
- `items[].title`
- `items[].accountName`
- `items[].sourceUrl`
- `items[].outDir`
- `items[].status`
- `items[].phase`
- `items[].qualityStatus`
- `items[].sidecarStatus`
- `items[].llmInputStatus`
- `items[].downstreamStatus`
- `items[].warningCount`
- `items[].errorMessage`
- `items[].files`

Renderer rule:

- UI should present the full chain state per article bundle, not only current file and current phase

LLM substate rule:

- LLM is a mode inside `Process & Export`, not a separate chat surface.
- It must be driven by `items[].files.llmInput`, `items[].llmInputStatus`, `items[].downstreamStatus`, `items[].qualityStatus`, `items[].errorMessage`, and the `llm-export` live snapshot when active.
- It should expose markdown mirror and downstream status as operational fields; do not invent provider readiness when the backend has not emitted it.

### 5. Artifacts & Review

Primary object:

- final pack article row

Purpose:

- show final pack readiness and support manual review of ready, review, and blocked outputs

Primary data source:

- `pack:get-projection`

Required fields:

- `generatedAt`
- `artifactRoot`
- `releaseRoot`
- `archiveRoot`
- `totalArticles`
- `copiedArticles`
- `qualityCounts.ready`
- `qualityCounts.review`
- `qualityCounts.blocked`
- `sources.manifestPath`
- `sources.indexPath`
- `indexRows[].token`
- `indexRows[].title`
- `indexRows[].account`
- `indexRows[].quality_grade`
- `indexRows[].warning_count`
- `indexRows[].local_image_count`
- `indexRows[].main_content_chars`
- `indexRows[].background_recall_chars`

Renderer rule:

- if `manifest.json` or `index.jsonl` is missing, show explicit empty or unavailable state
- do not preserve stale rows from a previous root after projection disappearance

## Command Contract

The UI may trigger only explicit commands through IPC or the main process. Renderer code must never run pipeline logic directly.

### Current command surface

- `dialog:pick-directory`
- `app:open-path`
- `batch:start`
- `batch:cancel`
- `audit:run`
- `pack:finalize`

### Current hidden or under-documented command surface that must be resolved before rebuild

The current renderer still depends on several flows that are not cleanly represented in the repo's documented contract. These must be either formalized or removed from redesign scope before implementation starts.

- background asset-download trigger and lock-state flow used by the archive workspace
- background download status polling
- mptext archive status polling
- mptext archive results polling

Backend decision required:

- either publish these as supported IPC contracts with explicit payloads and status semantics
- or remove them from the redesign target and keep them CLI-only

### Supported batch modes already visible in UI

- `pipeline="dual-track"`
- `pipeline="llm-export"`

### Read-only business capabilities that should influence future UI planning

- `prefetch-account-urls`
- `archive-batch`
- `download-archive-assets-batch`
- `run-downstream-llm`
- `run-keeper`

## Inspector Contract

All workspaces share the same inspector structure:

1. object summary
2. key state
3. latest error or warning
4. available actions

Backend implication:

- projections should expose compact current-object summaries and latest actionable error text
- UI should not have to parse long log streams to populate the inspector headline

## Global Status Model

The redesign uses two status layers.

### Job State

- `idle`
- `queued`
- `discovering`
- `archiving`
- `downloading-assets`
- `processing`
- `exporting`
- `downstream-running`
- `completed`
- `warning`
- `failed`
- `cancelled`
- `keeper-owned`

### Stage State

- `waiting`
- `running`
- `success`
- `warning`
- `error`
- `skipped`

Rules:

- row-level primary state should use `job-state`
- inspector stage details should use `stage-state`
- status bar should show only current primary state and compact progress
- the same business situation must not be phrased three different ways in different workspaces

Backend follow-up:

- current producer and renderer status vocabularies still drift; before UI rebuild, publish one canonical enum mapping for batch, collect, archive, process, and pack states

## Root And Identity Contract

Before implementation, backend and UI must freeze the exact meaning of these roots:

- `inputRoot`
- `archiveRoot`
- `outRoot`
- `artifactRoot`
- `releaseRoot`

Rules:

- each IPC payload must document which roots it accepts and which are optional
- renderer must not infer one root from another when the backend can provide an explicit value
- process rows and artifact rows must have stable unique identifiers that are safe across account-level collisions

Known risk:

- `token` alone may not be a stable row key if multiple accounts can collide; prefer a stable composite or emitted internal row id

### Current Freeze For Implementation

Until the full shell rebuild lands, freeze these concrete renderer-facing rules so the seam work does not drift again:

- `inputRoot`
  - primary meaning: discovery root used by collect and batch-start flows
  - renderer may use the current input field value as an explicit operator override
- `archiveRoot`
  - primary meaning: archive bundle root consumed by `archive:get-state`, `audit:get-projection`, `assets:run`, and archive open-path actions
  - renderer must not derive it from the generic output field
- `outRoot`
  - primary meaning: article bundle artifact root consumed by `process:get-state`
  - current task-bus output field maps here for process/export work
- `artifactRoot`
  - primary meaning: source artifact tree consumed by `pack:finalize`
  - current finalize flow uses the same operator-chosen output root unless a dedicated artifact root is later introduced
- `releaseRoot`
  - primary meaning: final pack release tree consumed by `pack:get-projection`
  - default contract for current implementation: `releaseRoot = artifactRoot/_release` when not explicitly supplied

Selection and identity freeze:

- artifact workspace selection must key rows by `rowKey` when present
- current fallback row key should be `source_artifact_dir`
- `token` may still be displayed, but it must not be the only selection key

## Security Boundary

The UI must never read, render, or expose:

- `.mptext-data`
- cookies
- auth keys
- raw service credentials
- private endpoint config
- secret local provider files

The UI may show:

- projection paths
- output paths
- release paths
- non-sensitive source URLs
- derived quality and warning counts

## Visual Direction Constraints For Backend Awareness

These constraints matter because projection shape and command placement should support a dense desktop workbench, not a card dashboard.

- no overview homepage
- no hero banner
- no statistics tile wall
- no placeholder-only workspaces that fake capability
- one stable object type per workspace
- compact counters belong in command bar or status bar
- main work surface is table-first
- right inspector follows selection only
- bottom console is persistent across workspaces

## Acceptance Criteria

### Data acceptance

- each workspace can render from its declared projection or IPC source without scanning unrelated folders for derived business truth
- missing projection data produces neutral empty or unknown states
- switching roots clears stale rows and stale inspector state

### Command acceptance

- every mutating action is delegated through the main process
- accepted commands return immediate acceptance state, not fake completion

### Security acceptance

- sensitive auth or token files never appear in UI

### Desktop workbench acceptance

- user can tell what is running now, what failed recently, what is selected, and what the next safe action is
- user does not need to visit a dashboard overview page to continue work

## Open Backend Follow-Ups

- freeze the real IPC surface for background download and mptext monitor flows, or explicitly remove them from redesign scope
- unify `job-state` naming across discovery, archive, process, and final pack producers where current wording diverges
- expose stable unique row keys for artifact rows if `token` collisions are possible across accounts
- consider projection support for `run-keeper` and downstream LLM so these can become first-class UI workspaces or submodes later
- keep projection shape backward-compatible once the redesigned PCUI starts consuming it
