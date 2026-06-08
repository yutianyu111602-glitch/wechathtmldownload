<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Hermes 7-Day Execution Plan

**Timezone:** Asia/Singapore / +08
**Day 0:** 2026-04-28
**Day 1-7:** 2026-04-29 to 2026-05-05
**Strategy:** Day 0-1 setup, Day 2-3 dry-run/smoke, Day 4-6 full batch, Day 7 handoff

---

## General Principles

1. Prove safety before scale
2. Every long task: checkpoint + run log + monitor summary
3. Full batch: recoverable progress over "blind completion"
4. No destructive actions while user away
5. mem0 saves learnings after every story

---

## Day 0 — 2026-04-28: WSL2 Setup & Preflight

**Goal:** Hermes ready to run, no large tasks started

| Step | Action | Output | Gate |
|---|---|---|---|
| D0-1 | Read this pack + reference | `reports/HERMES_READ_CONFIRMATION.md` | Required |
| D0-2 | Verify WSL2: `wsl --status` | Console OK | Required |
| D0-3 | Verify Hermes: `hermes --version` | Version printed | Required |
| D0-4 | Configure deepseek-v4-pro: `hermes model` | `config/hermes.config.yaml` | Required |
| D0-5 | Preflight script | `reports/preflight-*.md` | GREEN to continue |
| D0-6 | Initialize run state | `state/run-state.json` | Required |
| D0-7 | Write Day 0 checkpoint | `reports/checkpoint-day0.md` | Required |

Commands:
```bash
# WSL2
wsl --status
hermes --version
hermes doctor

# In WSL2
cd ~/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack
bash scripts/start-hermes-7day.sh preflight
bash scripts/start-hermes-7day.sh init
```

---

## Day 1 — 2026-04-29: Baseline Freeze + Context Gate

**Goal:** Freeze existing data, build capture queue

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D1-1 | Baseline freeze | `baseline/baseline-snapshot.json` | Manifest/index/checksum verifiable |
| D1-2 | Analyze existing 93K | `reports/existing-coverage.md` | Count per club/公众号 |
| D1-3 | Build capture queue | `queues/capture_queue.jsonl` | URLs not in existing release |
| D1-4 | WeChat window check | `reports/wechat-status.md` | Window accessible |
| D1-5 | Day 1 handoff | `reports/day1-handoff.md` | Next steps clear |

Commands:
```bash
bash scripts/start-hermes-7day.sh baseline
bash scripts/start-hermes-7day.sh context-gate
```

---

## Day 2 — 2026-04-30: Capture Dry-run 50

**Goal:** Verify WeChat capture with smallest scale

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D2-1 | Generate capture command | `reports/command-US-004.sh` | Params explicit |
| D2-2 | Run capture 50 | `output/capture-dryrun-50/manifest.jsonl` | 50 entries |
| D2-3 | Verify PDF outputs | `reports/dryrun-verification.md` | PDF valid, non-empty |
| D2-4 | Failure analysis | `reports/dryrun-failures.md` | Reasons categorized |
| D2-5 | Day 2 handoff | `reports/day2-handoff.md` | Smoke 500 decision |

Success criteria:
- >= 40/50 success (80%)
- No WeChat login interruption
- PDF files non-empty
- manifest.jsonl parseable

---

## Day 3 — 2026-05-01: Capture Smoke 500 + Resume Test

**Goal:** Verify medium-scale stability and resume

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D3-1 | Run capture 500 | `output/capture-smoke-500/manifest.jsonl` | 500 entries |
| D3-2 | Interrupt and resume test | `reports/resume-test.md` | No duplicates, no gaps |
| D3-3 | Throughput estimate | `reports/throughput-estimate.md` | >= 30/hr = GREEN |
| D3-4 | Failure budget check | `reports/failure-budget.md` | < 15% to proceed |
| D3-5 | Day 3 handoff | `reports/day3-handoff.md` | Full batch decision |

---

## Day 4 — 2026-05-02: Full Capture Batch + Loopy Start

**Goal:** Enter main longrun, start loopy processing

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D4-1 | Full batch start | `output/capture-full/manifest.jsonl` | Growing |
| D4-2 | Checkpoint every 50 | `state/checkpoints/` | Every 30min |
| D4-3 | Trigger loopy on new captures | `reports/loopy-trigger.md` | Pipeline started |
| D4-4 | 4-hour progress report | `reports/full-batch-progress-day4.md` | Coverage/speed/failures |
| D4-5 | Day 4 handoff | `reports/day4-handoff.md` | Recovery commands |

---

## Day 5 — 2026-05-03: Full Batch Continue + mem0 Learning

**Goal:** Continue capture, save learnings to mem0

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D5-1 | Continue capture | checkpoint | Success rate stable |
| D5-2 | mem0 save session learnings | mem0 records | Verified retrievable |
| D5-3 | Per-account stats | `reports/per-account-progress.md` | Identify problem accounts |
| D5-4 | Day 5 handoff | `reports/day5-handoff.md` | Remaining + ETA |

---

## Day 6 — 2026-05-04: Quality + Downstream + Graph Prep

**Goal:** Process captured articles, generate reports

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D6-1 | Capture continue/finish | checkpoint | Recoverable |
| D6-2 | Qwen3.6 downstream extract | `output/downstream/*.jsonl` | JSON valid >= 90% |
| D6-3 | Quality report draft | `reports/quality-report-draft.md` | Metrics complete |
| D6-4 | Graph dry-run prep | `reports/graph-dry-run-plan.md` | No production write |
| D6-5 | Safety audit | `reports/safety-audit-day6.md` | No boundary violations |
| D6-6 | Day 6 handoff | `reports/day6-handoff.md` | Day 7 items clear |

---

## Day 7 — 2026-05-05: Final Handoff

**Goal:** Stop new tasks, consolidate evidence, handoff

| Step | Action | Output | Acceptance |
|---|---|---|---|
| D7-1 | Stop new capture batches | State update | Don't kill safe checkpoint |
| D7-2 | Final quality report | `reports/quality-report-final.md` | Coverage/failures/samples |
| D7-3 | Graph candidate dry-run | `output/graph-candidate-pack/` | Dry-run only |
| D7-4 | mem0 final save | mem0 records | Session summary |
| D7-5 | OBSIDIAN update | `reports/obsidian-update.md` | Knowledge synced |
| D7-6 | Cleanup dry-run plan | `reports/cleanup-dry-run-plan.md` | No delete executed |
| D7-7 | Final handoff | `FINAL_HANDOFF_2026-05-05.md` | User-resumable |
| D7-8 | Next phase plan | `NEXT_PHASE_PLAN.md` | Remaining work + commands |

---

## Daily Fixed Actions

**Day start (WSL2):**
```bash
bash scripts/start-hermes-7day.sh monitor
bash scripts/start-hermes-7day.sh status
```

**Day end:**
```bash
bash scripts/start-hermes-7day.sh checkpoint --label dayN --state GREEN
```

---

## Gate Conditions

- Day 1 incomplete context gate -> Block Day 2
- Dry-run 50 success < 70% -> Block smoke 500, fix first
- Smoke 500 failure >= 15% or resume fails -> Block full batch
- Full batch failure > 20% -> RED, stop new tasks
- Checkpoint > 60 min stale -> RED
- WeChat window inaccessible 3x -> RED

---

## 7-Day Success Definition

**Best case:** >= 1000 new articles captured, loopy processed, quality report complete
**Acceptable:** Capture incomplete but checkpoint/resume/progress/failures documented
**Failure:** No evidence, no checkpoint, no recovery path, or boundary violation

---

**Next: Read `docs/03_RUNBOOK.md` for operational procedures.**
