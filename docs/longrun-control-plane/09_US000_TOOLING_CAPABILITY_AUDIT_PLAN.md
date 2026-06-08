<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# US-000 Tooling Capability Audit Plan

**Created:** 2026-04-27
**Status:** PLAN ONLY (not executed)

## Scope

US-000 audits all tooling capabilities needed before entering US-001 (Baseline Freeze). This is a gate: no US-001 until US-000 passes.

## Audit Items

### 1. OpenCode Tool Audit
- [ ] bash: file ops, git, npm scripts
- [ ] read: file reading (text, binary, directory)
- [ ] write: file creation
- [ ] edit: targeted string replacement
- [ ] glob: file pattern search
- [ ] grep: content search
- [ ] task: subagent launch
- [ ] webfetch: URL content retrieval
- [ ] skill: skill loading

### 2. Context-Mode Tool Audit
- [ ] ctx_execute: JavaScript/Python/shell sandbox
- [ ] ctx_execute_file: file processing without context load
- [ ] ctx_batch_execute: multi-command + search
- [ ] ctx_fetch_and_index: web fetch → index
- [ ] ctx_search: knowledge base search
- [ ] ctx_index: content indexing
- [ ] ctx_stats: context consumption stats

### 3. File Access Audit
- [ ] Read: project files, D:\DDownload\_llm_release_v2\manifest.json
- [ ] Read: D:\rawwechat_md\markitdown-batch-status.json
- [ ] Write: docs/ and artifacts/ only (not data dirs)
- [ ] No access: D:\DDownload recursive
- [ ] No access: D:\aidata recursive

### 4. Local Model Audit
- [ ] Qwen3.6-27B available at localhost:11434
- [ ] Model responds to /v1/models
- [ ] Model responds to /v1/chat/completions (smoke test, 1 short prompt)

### 5. GA Monitor Audit
- [ ] Can read manifest.md
- [ ] Can read run log
- [ ] Can check disk/GPU
- [ ] Can detect suspicious processes
- [ ] Cannot write to data dirs
- [ ] Cannot kill processes

### 6. CLI Command Audit
- [ ] `node dist/cli.js --help` returns
- [ ] run-downstream-llm-batch registered
- [ ] build-graph-candidate-pack registered
- [ ] Missing commands documented: create-baseline-snapshot, generate-quality-report, context-gate

## Output

```
docs/longrun-control-plane/reports/US000_TOOLING_AUDIT_REPORT.md
```

## Gate

US-000 must pass ALL items before US-001 can start.
Failed items → document in implementation-needed.md.
