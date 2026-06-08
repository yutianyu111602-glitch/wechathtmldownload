<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PRD: WeChat Article Pipeline Week Run

## Introduction

This week-run coordinates the old raw WeChat HTML MarkItDown conversion and the new article-release extraction artifacts into a safe, resumable, evidence-driven pipeline while the user is away for one week.

## Goals

- Recover the stale `D:\rawwechat_md` MarkItDown batch without losing the existing 3146 Markdown files.
- Complete and validate the current L2/Qwen extraction pilot.
- Produce clean reports and handoffs that let a future agent resume without rereading the whole workspace.
- Only start downstream rawwechat LLM artifact export after upstream gates pass.
- Keep every action verifiable and reversible.

## User Stories

### US-001: Freeze baseline evidence

**Description:** As an operator, I need a fresh baseline of docs, directories, status files, and processes before any long-running write starts.

**Acceptance Criteria:**
- [ ] Record counts for `D:\rawwechat`, `D:\rawwechat_md`, `D:\DDownload\_llm_release\articles`, and next-stage artifacts.
- [ ] Record MarkItDown status distribution and current file.
- [ ] Record whether conflicting rawwechat/markitdown/llama processes are active.
- [ ] Write `loops/loop-001-handoff.md`.
- [ ] No production data is modified.
- [ ] If code changed, `npm run build` passes; otherwise no code diff is recorded.

### US-002: Repair stale MarkItDown running state safely

**Description:** As an operator, I need the stale running item changed into a resumable state without losing existing outputs.

**Acceptance Criteria:**
- [ ] Create timestamped backup of `D:\rawwechat_md\markitdown-batch-status.json`.
- [ ] Change exactly one stale `running` item to `queued` or `failed`.
- [ ] Recompute top-level counters consistently.
- [ ] Parse the repaired JSON successfully.
- [ ] Verify recursive `.md` count remains at least `3146`.
- [ ] Write loop handoff with backup path.

### US-003: Resume MarkItDown conversion

**Description:** As an operator, I want to resume HTML to Markdown conversion so the remaining queued articles are processed.

**Acceptance Criteria:**
- [ ] Verify no conflicting process writes `D:\rawwechat_md`.
- [ ] Start `npm run export:rawwechat-md` with existing package script.
- [ ] Capture stdout/stderr to a timestamped log under this longrun directory.
- [ ] Observe at least one progress update or completed/failed terminal state.
- [ ] Write loop handoff with PID/log/status path.

### US-004: Verify MarkItDown completion and output quality

**Description:** As an operator, I need to know whether MarkItDown completed and whether the output tree is usable.

**Acceptance Criteria:**
- [ ] Status JSON parses.
- [ ] Counts are recorded: total, succeeded, failed, skipped, queued, running.
- [ ] Recursive `.md` count is recorded and compared with succeeded/skipped semantics.
- [ ] Sample at least 20 Markdown files across high-volume clubs for non-empty content.
- [ ] Produce `scorecards/markitdown-output-scorecard.md`.

### US-005: Clean current L2 JSONL

**Description:** As an operator, I need a clean `l2-results.jsonl` extracted from the partially dirty `l2-extracts.jsonl`.

**Acceptance Criteria:**
- [ ] Preserve original `l2-extracts.jsonl` before cleaning.
- [ ] Extract the last JSON object beginning with `content_type` per article.
- [ ] Produce parseable `l2-results.jsonl`.
- [ ] Count parsed, null, and failed rows.
- [ ] Write a quality scorecard.

### US-006: Finish L2 extraction

**Description:** As an operator, I want the selected 180 pilot articles processed by Qwen using `llama-completion.exe` only.

**Acceptance Criteria:**
- [ ] Do not start `llama-server.exe`.
- [ ] Continue from existing unique article IDs.
- [ ] Reach 180 unique selected articles or record explicit failures.
- [ ] Produce parseable clean L2 results.
- [ ] Record per-club counts for all 6 pilot clubs.

### US-007: Produce L2 quality report

**Description:** As a downstream consumer, I need a readable summary of L2 content types, events, DJs, genres, cities, and failure cases.

**Acceptance Criteria:**
- [ ] Generate report from parseable L2 results only.
- [ ] Include per-club counts and failure/null counts.
- [ ] Include top DJs, genres, venues, cities.
- [ ] Identify at least 20 candidates for L3.

### US-008: Run bounded L3 deep extraction

**Description:** As a downstream consumer, I want deeper extraction for the strongest L2 candidates without running unbounded LLM jobs.

**Acceptance Criteria:**
- [ ] Select at most 50 L3 articles with explicit scoring rules.
- [ ] Use `llama-completion.exe` only.
- [ ] Save raw calls and clean results separately.
- [ ] Stop if the same failure repeats 3 times.

### US-009: Audit L1 coverage gaps

**Description:** As an operator, I need to know which article-release directories were not included in the L1 facts.

**Acceptance Criteria:**
- [ ] Compare `D:\DDownload\_llm_release\articles` directory inventory against L1 JSONL article IDs.
- [ ] Produce missing-by-club report.
- [ ] Do not modify source article directories.

### US-010: Prepare rawwechat LLM artifact dry run

**Description:** As an operator, I need a small dry run before full rawwechat LLM artifact export.

**Acceptance Criteria:**
- [ ] Select a bounded sample from completed MarkItDown/raw HTML inputs.
- [ ] Run only into repo-local or timestamped temporary output.
- [ ] Verify expected artifact schema and sample quality.

### US-011: Run rawwechat LLM export if gates pass

**Description:** As an operator, I want full rawwechat LLM artifact export only after MarkItDown and dry-run gates pass.

**Acceptance Criteria:**
- [ ] Confirm MarkItDown is completed or consciously accepted as partial.
- [ ] Confirm dry-run artifact quality.
- [ ] Start `npm run export:rawwechat-llm` only if no conflicting process exists.
- [ ] Log output and status path.

### US-012: Mirror and validate LLM Markdown tree

**Description:** As a downstream user, I need a validated Markdown mirror if LLM artifacts are produced.

**Acceptance Criteria:**
- [ ] Use package script or documented mirror command only.
- [ ] Do not point mirror at hand-maintained directories.
- [ ] Count mirrored files and compare to artifact status.

### US-013: Build final operator report

**Description:** As the returning user, I need a single report of what ran, what passed, what failed, and what remains.

**Acceptance Criteria:**
- [ ] Include all production writes and backups.
- [ ] Include all status counts and final artifact paths.
- [ ] Include unresolved blockers and recommended next commands.

### US-014: Final SSOT and closeout

**Description:** As a future agent, I need the longrun state closed cleanly with one resume entry point.

**Acceptance Criteria:**
- [ ] Update manifest with final run_state.
- [ ] Update Ralph `prd.json` passes/notes.
- [ ] Write final handoff.
- [ ] State whether all stories passed, stopped, or remain queued.

## Functional Requirements

- FR-1: Every story must be resumable from manifest, latest loop handoff, and Ralph `prd.json`.
- FR-2: Every production status mutation must create a backup first.
- FR-3: Long-running commands must write logs under `docs/longrun/wechat-article-pipeline-week-run/logs` or `loops`.
- FR-4: LLM extraction must use `llama-completion.exe` only.
- FR-5: The runner must stop on dangerous operations or repeated verification failure.

## Non-Goals

- No UI work.
- No GitHub PR, commit, or push.
- No production deletion.
- No new paid API calls.
- No full rewrite of pipeline architecture during this week run.

## Success Metrics

- MarkItDown stale state recovered or safely blocked with backup evidence.
- L2 reaches 180 selected articles or has explicit failed-row accounting.
- All produced JSON/JSONL can be parsed by validation commands.
- At least one final handoff gives a fresh agent exact next steps.

## Open Questions

- If MarkItDown has many failed rows after resume, should failed rows be retried or accepted as a failure set? Default: accept and report, do not infinite retry.
- If rawwechat LLM export is long-running after one week, should it continue unattended? Default: continue only while logs and status advance.
