# OpenClaw DeepSeek TUI Next Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move OpenClaw weekly Docker skill from Round87 handoff to a current-state full-incremental hard-gate decision, then only run a no-release candidate if the gate explicitly allows it.

**Architecture:** Keep DeepSeek TUI as the WSL2 controller. Reuse existing report-only gate scripts first, mutate skills only after prompt/test evidence, and keep Docker/CloudBase/DB/release execution behind hard gates.

**Tech Stack:** WSL2 Ubuntu, Windows PowerShell fallback, Python pytest, Node mini-program tests, OpenClaw skills, Darwin scorecard, Docker compose profile contracts.

---

## File Structure

- Read: `C:\code\githubstar\wechathtmldownload\docs\OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md`
- Read: `C:\code\githubstar\wechathtmldownload\docs\OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_nonllm_20260606_151557\current_release_quality_gate.json`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_nonllm_20260606_151557\nonllm_fallback_summary.json`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_source_material_recovery_controller_release_round87_20260606\source_material_recovery_controller_release.json`
- Create reports under: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_deepseek_round88_current_gate_refresh_20260606\`
- Potentially modify after tests only: `C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- Potentially modify after tests only: `C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`
- Sync if modified: `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- Sync if modified: `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`

## Task 1: Baseline Readback In WSL2

**Files:**
- Read: `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md`
- Read: `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json`

- [ ] **Step 1: Enter repo**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
pwd
```

Expected:

```text
/mnt/c/code/githubstar/wechathtmldownload
```

- [ ] **Step 2: Verify WSL handoff package exists**

Run:

```bash
ls -la /home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87
```

Expected files:

```text
OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md
OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.html
OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json
OPENCLAW_DOCKER_SKILL_HANDOFF_ROUND87_20260606.md
```

- [ ] **Step 3: Parse compass**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json')
data = json.loads(p.read_text(encoding='utf-8'))
assert data['schema_version'] == 'openclaw_deepseek_tui_compass.v1'
assert data['current_acceptance']['fallback_status'] == 'check_only_ok'
assert data['current_acceptance']['item_count'] == 155
assert data['current_acceptance']['poster_blocker_counts_zero'] is True
print('compass_ok')
PY
```

Expected:

```text
compass_ok
```

- [ ] **Step 4: Stop if baseline fails**

If any expected file or compass field is missing, stop and ask the controller to refresh the WSL handoff package. Do not run gates from incomplete handoff state.

## Task 2: Reconfirm Current Package Quality

**Files:**
- Read: `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/current_release_quality_gate.json`
- Read: `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/nonllm_fallback_summary.json`

- [ ] **Step 1: Print current quality summary**

Run:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Raw -LiteralPath 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_nonllm_20260606_151557\current_release_quality_gate.json' | ConvertFrom-Json | Select-Object ok,item_count,missing_internal_poster_count,invalid_internal_poster_file_id_count,invalid_poster_storage_count,public_wechat_or_qpic_poster_count,runtime_poster_state_count,missing_geo_count | Format-List"
```

Expected:

```text
ok                                    : True
item_count                            : 155
missing_internal_poster_count         : 0
invalid_internal_poster_file_id_count : 0
invalid_poster_storage_count          : 0
public_wechat_or_qpic_poster_count    : 0
runtime_poster_state_count            : 0
missing_geo_count                     : 6
```

- [ ] **Step 2: Print fallback summary**

Run:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Raw -LiteralPath 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_nonllm_20260606_151557\nonllm_fallback_summary.json' | ConvertFrom-Json | Select-Object status,ok,reason,current_release_quality_ok,docker_contract_ok | Format-List"
```

Expected:

```text
status                     : check_only_ok
ok                         : True
current_release_quality_ok : True
docker_contract_ok         : True
```

- [ ] **Step 3: Stop on drift**

If package quality is no longer green or poster blocker counts are nonzero, stop and write the changed counts into the next handoff before any full gate refresh.

## Task 3: Refresh Current Next-Action Packet

**Files:**
- Create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet/openclaw_weekly_next_action_packet.json`
- Create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet/openclaw_weekly_next_action_packet.md`

- [ ] **Step 1: Create output directory**

Run:

```bash
mkdir -p tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet
```

Expected:

```text
directory exists
```

- [ ] **Step 2: Build next-action packet from current quality**

Run:

```bash
python tools/stage7_rewrite/scripts/build_openclaw_weekly_next_action_packet.py \
  --runtime-quality tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/current_release_quality_gate.json \
  --source-material-controller tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_recovery/source_material_recovery_controller_packet.json \
  --out-dir tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet
```

Expected:

- command exits `0`;
- JSON packet exists;
- markdown packet exists.

- [ ] **Step 3: Inspect decision fields**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet/openclaw_weekly_next_action_packet.json')
data = json.loads(p.read_text(encoding='utf-8'))
print('decision=', data.get('decision'))
print('task_count=', data.get('task_count'))
print('source_refresh_allowed_now=', data.get('source_refresh_allowed_now'))
print('full_incremental_run_allowed_now=', data.get('full_incremental_run_allowed_now'))
print('leak_count=', data.get('raw_url_private_path_secret_leak_count'))
PY
```

Expected:

- `leak_count=0`;
- exact decision may be ready or blocked;
- do not infer execution from this packet alone.

## Task 4: Refresh Darwin Scorecard

**Files:**
- Create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_darwin_scorecard/openclaw_weekly_darwin_scorecard.json`
- Create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_darwin_scorecard/openclaw_weekly_darwin_scorecard.md`

- [ ] **Step 1: Build Darwin scorecard**

Run:

```bash
python tools/stage7_rewrite/scripts/build_openclaw_weekly_darwin_scorecard.py \
  --daily-skill C:/Users/pc/.openclaw/skills/openclaw-weekly-daily-run/SKILL.md \
  --docker-skill C:/Users/pc/.openclaw/skills/openclaw-docker-arsenal/SKILL.md \
  --next-action-packet tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet/openclaw_weekly_next_action_packet.json \
  --source-material-controller tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_recovery/source_material_recovery_controller_packet.json \
  --source-material-runtime-preflight tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_recovery/source_material_recovery_runtime_release_preflight.json \
  --source-material-controller-release tools/stage7_rewrite/reports/weekly_source_material_recovery_controller_release_round87_20260606/source_material_recovery_controller_release.json \
  --current-release-quality-recovery-packet tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_recovery/openclaw_current_release_quality_recovery_packet.json \
  --out-dir tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_darwin_scorecard
```

Expected:

- command exits `0`;
- JSON and markdown scorecards exist;
- scorecard contains prompt `source-material-controller-release-does-not-mean-runtime-executed`.

- [ ] **Step 2: Inspect key blockers**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_darwin_scorecard/openclaw_weekly_darwin_scorecard.json')
data = json.loads(p.read_text(encoding='utf-8'))
print('score_total=', data.get('score_total'))
print('leak_count=', data.get('raw_url_private_path_secret_leak_count'))
print('controller_release_runtime_executed=', data.get('current_blockers', {}).get('source_material_controller_release_runtime_executed'))
PY
```

Expected:

- leak count is `0`;
- runtime executed remains false unless a separate runtime was actually run.

## Task 5: Refresh Full-Incremental Hard Gate

**Files:**
- Create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.json`
- Create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.md`

- [ ] **Step 1: Build hard gate**

Run:

```bash
python tools/stage7_rewrite/scripts/build_openclaw_weekly_full_incremental_preflight_gate.py \
  --next-action-packet tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_next_action_packet/openclaw_weekly_next_action_packet.json \
  --darwin-scorecard tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_darwin_scorecard/openclaw_weekly_darwin_scorecard.json \
  --report tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.json \
  --scorecard tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.md
```

Expected:

- command exits `0`;
- report and scorecard exist;
- no source refresh, Docker worker, model call, CloudBase write, DB write, deploy, upload, review, or release occurs.

- [ ] **Step 2: Read gate decision**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.json')
data = json.loads(p.read_text(encoding='utf-8'))
for k in ['decision','full_incremental_candidate_run_allowed_now','source_refresh_allowed_now','docker_worker_allowed_now','release_actions_allowed_now','raw_url_private_path_secret_leak_count']:
    print(f'{k}={data.get(k)}')
print('failed=', data.get('failed_required_check_ids'))
PY
```

Expected branch A:

- if all of `full_incremental_candidate_run_allowed_now`, `source_refresh_allowed_now`, and `docker_worker_allowed_now` are `true`, proceed to Task 6.

Expected branch B:

- if any are `false`, do not run a candidate. Write the failed checks into the handoff and proceed to Task 8.

## Task 6: Candidate Run Decision

**Files:**
- Read: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.json`
- Potential run wrapper: `tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1`

- [ ] **Step 1: Confirm gate allows candidate**

Run:

```bash
python - <<'PY'
import json, sys
from pathlib import Path
p = Path('tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/openclaw_weekly_full_incremental_preflight_gate.json')
data = json.loads(p.read_text(encoding='utf-8'))
required = [
    data.get('full_incremental_candidate_run_allowed_now') is True,
    data.get('source_refresh_allowed_now') is True,
    data.get('docker_worker_allowed_now') is True,
    data.get('release_actions_allowed_now') is False,
    data.get('raw_url_private_path_secret_leak_count') == 0,
]
print(required)
sys.exit(0 if all(required) else 2)
PY
```

Expected:

- exit `0` only if no-release candidate run is allowed.

- [ ] **Step 2: If exit is 2, stop**

Do not run the wrapper. Write the failed checks into:

- `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/NEXT_BLOCKERS.md`

Content:

```markdown
# Round88 Next Blockers

- hard_gate_decision: <copy from JSON>
- failed_required_check_ids: <copy from JSON>
- full_incremental_candidate_run_allowed_now: false
- source_refresh_allowed_now: <copy from JSON>
- docker_worker_allowed_now: <copy from JSON>
- release_actions_allowed_now: false

No candidate run was executed.
```

- [ ] **Step 3: If exit is 0, run no-release candidate only**

Run from Windows PowerShell or through `powershell.exe` in WSL2:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1' -RequireFullIncrementalPreflightGate
```

Expected:

- candidate path runs under existing wrapper controls;
- no WeChat review;
- no public release;
- if wrapper exposes deploy/upload switches, do not pass them.

If this command behavior is unclear, stop and inspect wrapper help/text before running.

## Task 7: Verify Candidate Or Blocked State

**Files:**
- Read candidate reports created by Task 6 if any.
- Read blocked gate report if Task 6 stopped.

- [ ] **Step 1: Rerun Python focused tests**

Run:

```bash
python -m pytest \
  tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_controller_release.py \
  tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_runtime_release_preflight.py \
  tools/stage7_rewrite/tests/test_build_openclaw_weekly_next_action_packet.py \
  tools/stage7_rewrite/tests/test_build_openclaw_weekly_darwin_scorecard.py \
  tools/stage7_rewrite/tests/test_build_openclaw_weekly_full_incremental_preflight_gate.py \
  tools/stage7_rewrite/tests/test_openclaw_full_incremental_runner_gate.py \
  tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py \
  -q
```

Expected:

- all pass.

- [ ] **Step 2: Rerun frontend contract tests**

Run:

```bash
node apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs
node apps/weekly_activity_miniprogram/tests/cloud-poster-url.test.cjs
```

Expected:

- production data-source test passes;
- CloudBase poster URL adapter test passes.

- [ ] **Step 3: Parse fallback script**

Run:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $script = Get-Content -Raw -LiteralPath 'C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1'; $null = [scriptblock]::Create($script); 'parse_ok'"
```

Expected:

```text
parse_ok
```

## Task 8: Skill Mutation Only If Behavior Gap Is Proven

**Files:**
- Modify only if needed: `C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- Modify only if needed: `C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`
- Mirror only after tests: `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- Mirror only after tests: `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`

- [ ] **Step 1: Run four Darwin prompt dry-runs**

Use the prompts in:

```text
docs/OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md
```

Expected answer properties:

- cites current quality gate;
- cites current hard gate;
- never treats temp URL as backend package truth;
- never treats controller-release as runtime execution;
- never treats check-only fallback as completed full run.

- [ ] **Step 2: If a prompt fails, add one regression row**

Add a single row to the Darwin regression prompt table in:

```text
C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md
```

Use this row shape:

```markdown
| round88_current_gate_refresh | `当前包 quality 绿了，Round87 controller-release ready，可以直接跑全量增量吗？` | No. First read the current next-action, Darwin, and full-incremental hard gate generated under `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/`. If the hard gate does not set `full_incremental_candidate_run_allowed_now=true`, `source_refresh_allowed_now=true`, and `docker_worker_allowed_now=true`, stop and report failed checks. Do not run source refresh, Docker worker, StepFun/MiMo, CloudBase, package patch, DB2/DB3, deploy, upload, review, or release. |
```

- [ ] **Step 3: Sync WSL mirrors after mutation**

Run:

```powershell
$pairs = @(
  @('C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md','\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md'),
  @('C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md','\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md')
)
foreach ($p in $pairs) {
  Copy-Item -LiteralPath $p[0] -Destination $p[1] -Force
  $src=(Get-FileHash -Algorithm SHA256 -LiteralPath $p[0]).Hash
  $dst=(Get-FileHash -Algorithm SHA256 -LiteralPath $p[1]).Hash
  if ($src -ne $dst) { throw "skill sync failed: $($p[0])" }
}
"skill_sync_ok"
```

Expected:

```text
skill_sync_ok
```

## Task 9: StepFun/MiMo Vision Work Is A Separate Later Plan

**Files:**
- Do not modify in this task.

- [ ] **Step 1: Record deferral**

Write in the handoff:

```markdown
StepFun/MiMo comparison intentionally deferred until current hard gate and source-material readiness are refreshed. API keys must stay in environment variables and must not be written into docs or reports.
```

- [ ] **Step 2: Do not call APIs**

Expected:

- no StepFun request;
- no MiMo request;
- no API key printed;
- no `.env` read.

## Task 10: Final Handoff Update

**Files:**
- Modify: `docs/current-runtime.md`
- Modify: `tools/stage7_rewrite/SSOT.md`
- Modify or create: `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/HANDOFF.md`
- Copy: `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/ROUND88_NEXT_STATUS.md`

- [ ] **Step 1: Write round status**

Create `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/HANDOFF.md` with this structure:

```markdown
# OpenClaw DeepSeek Round88 Status

## Confirmed

- current_quality_ok:
- next_action_decision:
- darwin_score_total:
- hard_gate_decision:
- full_incremental_candidate_run_allowed_now:
- source_refresh_allowed_now:
- docker_worker_allowed_now:
- release_actions_allowed_now:

## Executed

- full_incremental_candidate_run_executed:
- docker_worker_executed:
- StepFun_or_MiMo_executed:
- CloudBase_write_executed:
- DB2_DB3_write_executed:
- deploy_upload_review_release_executed:

## Next

- next_best_entry:
- blocker:
```

Fill every field from actual reports. If a value is unknown, write `unverified`, not a guess.

- [ ] **Step 2: Copy to WSL**

Run:

```powershell
Copy-Item -LiteralPath 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_deepseek_round88_current_gate_refresh_20260606\HANDOFF.md' -Destination '\\wsl.localhost\Ubuntu\home\pc\.deepseek\handoffs\openclaw-weekly-skill-round87\ROUND88_NEXT_STATUS.md' -Force
```

Expected:

- WSL status file exists.

- [ ] **Step 3: Final verification**

Run:

```bash
git diff --check -- docs/current-runtime.md tools/stage7_rewrite/SSOT.md
```

Expected:

- no whitespace errors;
- LF/CRLF warnings may appear and are not a blocker.

## Self-Review

Spec coverage:

- Baseline readback: Task 1.
- Current package verification: Task 2.
- Next-action/Darwin/full-gate refresh: Tasks 3-5.
- Candidate decision: Task 6.
- Verification: Task 7.
- Skill mutation ratchet: Task 8.
- StepFun/MiMo deferral: Task 9.
- Handoff update: Task 10.

Placeholder scan:

- No placeholder markers or unspecified commands are intentionally left.

Type/path consistency:

- All WSL and Windows paths match the DeepSeek TUI acceptance package.
- The plan uses existing scripts and CLI arguments verified with `--help`.
