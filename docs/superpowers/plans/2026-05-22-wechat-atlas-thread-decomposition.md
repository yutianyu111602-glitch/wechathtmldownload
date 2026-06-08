# WeChat Atlas Thread Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish durable thread-level ownership documents for the WeChat weekly, Atlas, and DeepSeekTUI project family, then route current SSOT docs to those threads.

**Architecture:** Create one canonical thread index and seven thread documents under `docs/threads/`. Update current runtime and documentation indexes to make the thread model the first operating layer without changing production runtime state.

**Tech Stack:** Markdown, MkDocs, existing `wechathtmldownload` docs, PowerShell validation, existing Git backup workflow.

---

### Task 1: Create Thread Documentation Pack

**Files:**
- Create: `docs/threads/THREADS_INDEX_20260522.md`
- Create: `docs/threads/T1_source_intake_docker_exporter_20260522.md`
- Create: `docs/threads/T2_weekly_backend_release_20260522.md`
- Create: `docs/threads/T3_mini_program_frontend_20260522.md`
- Create: `docs/threads/T4_atlas_activity_candidate_20260522.md`
- Create: `docs/threads/T5_atlas_dj_serving_graph_20260522.md`
- Create: `docs/threads/T6_deepseektui_ldr_sidecar_20260522.md`
- Create: `docs/threads/T7_docs_ssot_control_20260522.md`

- [ ] **Step 1: Create the docs directory**

Run:

```powershell
New-Item -ItemType Directory -Force -Path C:\code\githubstar\wechathtmldownload\docs\threads
```

Expected: directory exists.

- [ ] **Step 2: Write the thread index**

Write a current-authority index that lists each thread, owner scope, current status, outputs, verification gates, and forbidden actions.

- [ ] **Step 3: Write each thread document**

Each thread document must include:

- purpose
- current state
- source documents
- scripts and runtime surfaces
- outputs it owns
- gates and forbidden actions
- copy/paste prompt for a future agent
- next bounded tasks

### Task 2: Route Current SSOT To Threads

**Files:**
- Modify: `docs/current-runtime.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`
- Modify: `docs/weekly-miniprogram-handoff-20260519/INDEX.md`
- Modify: `C:\code\PROJECT_DOCS_ROUTER.md`

- [ ] **Step 1: Add current-runtime thread entry**

Add a timestamped entry explaining that the project is now decomposed into seven threads and that no production tasks were run in this slice.

- [ ] **Step 2: Add thread docs to documentation index**

Add `docs/threads/THREADS_INDEX_20260522.md` as `CURRENT_AUTHORITY`, and list the seven thread files as active current routing surfaces.

- [ ] **Step 3: Update weekly mini-program handoff index**

Add the thread index as the operating map before the older plan table. Preserve weekly-specific current facts.

- [ ] **Step 4: Update top-level project router**

Point the China underground electronic music graph / weekly mini-program mixed topic to the new thread index.

### Task 3: Verify Documentation State

**Files:**
- Read/check only; no production runtime mutation.

- [ ] **Step 1: Confirm files exist**

Run:

```powershell
Test-Path C:\code\githubstar\wechathtmldownload\docs\threads\THREADS_INDEX_20260522.md
```

Expected: `True`.

- [ ] **Step 2: Search for new thread routes**

Run:

```powershell
Select-String -Path C:\code\githubstar\wechathtmldownload\docs\current-runtime.md,C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md -Pattern "THREADS_INDEX_20260522"
```

Expected: at least one hit in each file.

- [ ] **Step 3: Run docs build if practical**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\scripts\docs-build.ps1 -SkipRefresh
```

Expected: build succeeds. If it fails for unrelated pre-existing doc noise, record exact failure.

### Task 4: Closeout

**Files:**
- Read/check only unless the docs closeout script writes generated inventory.

- [ ] **Step 1: Report changed files**

Run:

```powershell
git -C C:\code\githubstar\wechathtmldownload status --short -- docs current-runtime.md
```

Expected: new thread docs and updated indexes are visible.

- [ ] **Step 2: Keep state boundaries explicit**

Final report must separately state local docs changed, CloudRun state unchanged, mini-program review unchanged, Atlas production unchanged, and Git backup path.
