# START HERE: Atlas Core DeepSeekTUI

你是 WSL2 DeepSeekTUI sidecar。先读这个文件，再读同目录的编号文档。

## 当前目录

Linux 主入口：

```bash
/home/pc/deepseektui-handoffs/atlas-core-20260606
```

仓库入口：

```bash
/mnt/c/code/githubstar/wechathtmldownload
```

## 三条红线

1. 本任务只允许 report-local/shadow/候选分析。
2. 不允许写 DB1/DB2/DB3，不允许 S232D-4，不允许 production pointer 切换。
3. 不允许部署、CloudBase sync、小程序上传/提审/发布、读取 secret/cookie/.env/profile。

## 第一条命令

```bash
cd /home/pc/deepseektui-handoffs/atlas-core-20260606
sed -n '1,120p' 00_README_FOR_DEEPSEEKTUI.md
```

## 第二条命令

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 - <<'PY'
import json
from pathlib import Path
p = Path("tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json")
j = json.loads(p.read_text(encoding="utf-8"))
print("decision=", j["decision"])
print("blockers=", j.get("blockers"))
print("report_local_output_only=", j["safety"]["report_local_output_only"])
print("production_db_write_executed=", j["safety"]["production_db_write_executed"])
print("source_db_write_executed=", j["safety"]["source_db_write_executed"])
print("source_hashes_unchanged=", j["source_hashes_unchanged"])
PY
```

预期：

- `decision= atlas_core_safe_execution_passed`
- `blockers= []`
- `report_local_output_only= True`
- `production_db_write_executed= False`
- `source_db_write_executed= False`
- `source_hashes_unchanged= True`

## 读文档顺序

1. `00_README_FOR_DEEPSEEKTUI.md`
2. `01_ACCEPTANCE_REPORT.md`
3. `02_EXECUTION_LOG.md`
4. `03_NEXT_OPTIMIZATION_PLAN.md`
5. `04_DEEPSEEKTUI_RUNBOOK.md`
6. `05_WEAPONS_SKILLS_TOOLS.md`
7. `06_HIGHLIGHTS_PITFALLS.md`
8. `07_COMPASS_PROMPT_FOR_DEEPSEEK.md`
9. `08_DEEPSEEK_NEXT_PLAN_DESIGNED_BY_CODEX.md`
10. `/mnt/c/code/githubstar/wechathtmldownload/docs/superpowers/specs/2026-06-06-atlas-core-deepseektui-next-optimization-design.md`
11. `/mnt/c/code/githubstar/wechathtmldownload/docs/superpowers/plans/2026-06-06-atlas-core-deepseektui-next-optimization.md`

## 下一轮执行计划

Codex 已设计 DeepSeekTUI 下一轮计划。第一批只执行 plan 的 Tasks 1-3：

```text
Task 1: Current Authority Packet
Task 2: Shadow Matrix Expansion Candidate
Task 3: Legacy Compatibility Contract Candidate
```

不要执行 Tasks 4-7，直到 Codex review 第一批 packet。

## 接手后的第一个产出

不要修改仓库。先输出一个候选包到 `/home/pc/deepseek-dream/outbox/`：

```text
YYYYMMDD_HHMMSS_atlas_core_handoff_current_authority_candidate.md
YYYYMMDD_HHMMSS_atlas_core_handoff_current_authority_candidate.jsonl
```

内容必须包含：

- 当前 authority path。
- 最终候选路径。
- 已验收事实。
- 未验收/禁止动作。
- 下一步 P0 shadow matrix 扩充建议。
- 每条事实都带 `evidence_paths`。
- JSONL 每条都带 `codex_verification_needed=true`。

第一批结束后，必须停止并等待 Codex review。
