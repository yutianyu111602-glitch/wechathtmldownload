# DeepSeekTUI WSL2 Runbook

对象：运行在 WSL2 Ubuntu 的 DeepSeekTUI sidecar
角色：候选分析、优化建议、审批包草稿生成
禁止角色：生产写入、发布、部署、DB merge

## 路径映射

仓库：

| Surface | Path |
| --- | --- |
| Windows | `C:\code\githubstar\wechathtmldownload` |
| WSL | `/mnt/c/code/githubstar/wechathtmldownload` |

本接手包：

| Surface | Path |
| --- | --- |
| Windows | `C:\code\githubstar\wechathtmldownload\docs\handoffs\atlas-core-deepseektui-20260606` |
| WSL repo path | `/mnt/c/code/githubstar/wechathtmldownload/docs/handoffs/atlas-core-deepseektui-20260606` |
| WSL inbox main | `/home/pc/deepseektui-handoffs/atlas-core-20260606` |
| Windows UNC main | `\\wsl.localhost\Ubuntu\home\pc\deepseektui-handoffs\atlas-core-20260606` |
| WSL mirror | `/home/pc/deepseektui_handoffs/atlas-core-20260606` |
| Windows UNC mirror | `\\wsl.localhost\Ubuntu\home\pc\deepseektui_handoffs\atlas-core-20260606` |

最终候选：

| Surface | Path |
| --- | --- |
| Windows | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix` |
| WSL | `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix` |

## 开始前检查

在 WSL2：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
pwd
git rev-parse --show-toplevel
git branch --show-current
ls docs/handoffs/atlas-core-deepseektui-20260606
ls tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix
```

预期：

- repo top 为 `/mnt/c/code/githubstar/wechathtmldownload`
- 分支当前是 `wip/rescue-20260605-160743`，如果不同，先报告，不要自动切分支。
- 文档包存在。
- 最终候选目录存在。

## 只读验收复核

先读 summary，不要直接打开大 sqlite：

```bash
sed -n '1,180p' docs/handoffs/atlas-core-deepseektui-20260606/01_ACCEPTANCE_REPORT.md
sed -n '1,160p' tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md
python3 - <<'PY'
import json
from pathlib import Path
p = Path("tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json")
j = json.loads(p.read_text(encoding="utf-8"))
print(j["decision"])
print("blockers", j.get("blockers"))
print("report_local_output_only", j["safety"]["report_local_output_only"])
print("production_db_write_executed", j["safety"]["production_db_write_executed"])
print("source_db_write_executed", j["safety"]["source_db_write_executed"])
print("source_hashes_unchanged", j["source_hashes_unchanged"])
PY
```

预期：

- `atlas_core_safe_execution_passed`
- blockers 为空
- report local true
- production/source DB write false
- source hashes unchanged true

## 可选测试命令

如果 WSL2 环境有 Python/Node 依赖，可运行：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 -m pytest tools/stage7_rewrite/tests/test_atlas_core_candidate.py -q
node --check services/weekly_activity_cloudrun/scripts/atlasCoreApiShadowDiff.mjs
node --check services/weekly_activity_cloudrun/src/server.mjs
node --check services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs
```

如果 WSL2 依赖不完整，不要安装大依赖或改环境；回到 Windows PowerShell 执行同等命令，或把缺依赖作为 `environment_gap` 报告。

## Shadow diff 复跑

只在用户要求或需要 drift check 时运行：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
node services/weekly_activity_cloudrun/scripts/atlasCoreApiShadowDiff.mjs \
  --old-serving-db reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite \
  --core-serving-db tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_serving.sqlite \
  --out-dir tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix_deepseektui_check
```

停止门：

- regression finding > 0：停止，写 diff diagnosis，不要继续 promotion。
- leak finding > 0：停止，写 safety incident。
- source hash changed：停止，重新确认输入 snapshot。
- 脚本超过合理时间或卡住：停止，不要开第二个并发进程。

## Opt-in read model 环境变量

`ATLAS_CORE_SQLITE_DB` 指向的是 core 导出的 serving read model，不是直接指向 `atlas_core.sqlite`。

Windows PowerShell：

```powershell
$env:ATLAS_CORE_SQLITE_DB='C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite'
$env:ATLAS_SQLITE_READONLY='1'
```

WSL bash：

```bash
export ATLAS_CORE_SQLITE_DB=/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_serving.sqlite
export ATLAS_SQLITE_READONLY=1
```

默认行为仍应读取旧 `atlas_serving.sqlite`。只有 shadow/opt-in 才使用候选 read model。

## DeepSeekTUI 输出格式

建议 DeepSeekTUI 输出到自己的候选 outbox，不直接改仓库 authority：

```text
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_<slug>_candidate.md
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_<slug>_candidate.jsonl
```

JSONL 每条事实必须包含：

```json
{"codex_verification_needed": true, "evidence_paths": ["..."]}
```

允许 record type：

- `current_authority_candidate`
- `stale_doc_candidate`
- `conflict_candidate`
- `next_question`
- `cluster_summary`
- `safety_note`
- `optimization_candidate`
- `approval_packet_candidate`

## DeepSeekTUI 允许的任务

- 扩充 API shadow path matrix 草稿。
- 读取 `identity_resolution_cases.jsonl`，只生成 38 source-backed case 的 approval packet 草稿。
- 分析 `legacy_mapping_gaps.jsonl`，输出 DB2->DB3 join coverage gap 分类。
- 分析 external-link evidence 的状态流，确认 `candidate|blocked|accepted_for_graph` 规则。
- 识别旧脚本消费者依赖字段，补 compatibility contract 建议。
- 写候选优化报告，不直接写 DB。

## 禁止命令和动作

禁止：

```bash
rm -rf
git reset --hard
git clean
git checkout -- .
sqlite3 <production db> "update ..."
sqlite3 <production db> "delete ..."
sqlite3 <production db> "insert ..."
npm run weekly:deploy-upload:preflight
npm run weekly:deploy-upload
firebase deploy
gcloud run deploy
```

除非用户明确要求并经过单独 gate，否则也禁止：

- Docker/worker/crawler/avatar/outlink batch。
- CloudBase sync。
- WeChat upload/review/release。
- provider/geocode/model production job。
- 读取 secret/cookie/profile。
- 扫描 `/mnt/d`、`D:\DDownload`、`D:\aidata` 根目录。

## 接手后的第一批建议动作

1. 读本包 8 个文件和 `HANDOFF_ATLAS_CORE_CANDIDATE_20260605.md`。
2. 输出一个 `current_authority_candidate` packet，确认最终候选路径和安全边界。
3. 设计 P0 shadow matrix 扩充，不运行生产写。
4. 设计 P3 identity approval packet schema，只覆盖 38 source-backed case。
5. 等 Codex/用户选择一个 bounded batch，再执行。
