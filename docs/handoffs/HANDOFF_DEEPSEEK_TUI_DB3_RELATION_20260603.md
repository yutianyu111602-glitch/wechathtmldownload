# WSL2 DeepSeek TUI 接手报告 - DB3 关系身份门禁

生成时间：2026-06-03  
主仓：`C:\code\githubstar\wechathtmldownload`  
WSL 视角路径：`/mnt/c/code/githubstar/wechathtmldownload`  
当前主线：Atlas / HUAIDJ 方案 A，DB3 关系身份完整性 blocker。  

## WSL2 目录对照

默认 WSL distro：`Ubuntu`。

| 用途 | Windows 路径 | WSL 路径 | Explorer UNC |
| --- | --- | --- | --- |
| 主仓 | `C:\code\githubstar\wechathtmldownload` | `/mnt/c/code/githubstar/wechathtmldownload` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload` |
| 本接手文档 | `C:\code\githubstar\wechathtmldownload\docs\handoffs\HANDOFF_DEEPSEEK_TUI_DB3_RELATION_20260603.md` | `/mnt/c/code/githubstar/wechathtmldownload/docs/handoffs/HANDOFF_DEEPSEEK_TUI_DB3_RELATION_20260603.md` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\docs\handoffs\HANDOFF_DEEPSEEK_TUI_DB3_RELATION_20260603.md` |
| S232D-3B7 report dir | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b7_repair_packet_20260603` | `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_relation_identity_s232d3b7_repair_packet_20260603` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b7_repair_packet_20260603` |
| S217 source/provider report dir | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602` | `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602` |
| DeepSeek TUI 用户目录，使用前需确认 | `\\wsl.localhost\Ubuntu\home\pc\.deepseek` | `/home/pc/.deepseek` | `\\wsl.localhost\Ubuntu\home\pc\.deepseek` |
| DeepSeek TUI 草稿/mailroom，历史路径，使用前需确认 | `D:\agent-comm\drafts` | `/mnt/d/agent-comm/drafts` | 不建议从 Explorer 全盘扫 D，只按此目录精确打开 |

## 本线程是干什么的

这条 Codex 线程只负责 **建立可接手文档和交接边界**。它不是 DB3 写库线程、不是 OpenClaw runtime 执行线程、不是 ReleaseGuard、小程序上传、CloudBase 发布或 DB2 投影线程。

本线程已经做的事：

- 读取当前主仓与 controller wake-state，确认 DB3 blocker、OpenClaw runtime、坐标 lane、release guard 的边界。
- 把 DeepSeek TUI 后续 agent 的接手入口、输入文件、禁止动作、输出字段和最小下一步写成本文档。
- 把 OpenClaw / Docker 武器库后续 agent 的接手入口另写成 `docs/handoffs/HANDOFF_OPENCLAW_DOCKER_WEAPONS_20260603.md`。
- 只写文档，不写 DB，不启动 Docker，不联网抓取，不读凭据，不发布。

后续 agent 看到本文档后，应把本线程当作“交接说明生成线程”，而不是继续在本线程里执行 DB 写入或生产发布。

## 给接手 Agent 的一句话

你的角色是 **WSL2 DeepSeek TUI 只读分析 sidecar**：帮主线程审 `348` 个 DB3 same-normalized-name multi-id groups，产出“候选处置/缺失证据/人工审核建议”。你不能写 DB，不能进入 S232D-4，不能把模型判断当成写库授权。

## 当前权威状态

当前 deploy/upload 仍 fail-closed。前端 rendered gate 已绿，坐标 lane 已经有自己的运行证据，但它们都不解锁 DB3。

DB3 blocker：

- blocker id：`atlas_relation_field_integrity`
- 具体字段：`db3_same_normalized_name_multi_id=348`
- 权威报告：`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_deploy_upload_preflight_20260531\atlas_relation_field_integrity\atlas_relation_field_integrity.json`
- 当前 repair packet：`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b7_repair_packet_20260603\atlas_relation_identity_s232d3b7_repair_packet.json`
- 当前 rows：`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b7_repair_packet_20260603\s232d3b7_repair_rows.jsonl`

S232D-3B7 当前结论：

- `decision=atlas_relation_identity_s232d3b7_repair_packet_ready_report_only_no_write`
- `repair_row_count=348`
- `provider_crosscheck_review=38`
- `manual_disposition_review=93`
- `external_evidence_required=217`
- `approved_for_s232d4_count=0`
- `db_write_allowed_now_count=0`

## 输入文件

优先读这些，不要全量扫 repo：

1. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_deploy_upload_next_gate_20260603\weekly_deploy_upload_next_gate_20260603.json`
2. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b7_repair_packet_20260603\atlas_relation_identity_s232d3b7_repair_packet.json`
3. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b7_repair_packet_20260603\s232d3b7_repair_rows.jsonl`
4. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602\source_provider_acquisition_workbench_s185.jsonl`
5. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602\provider_crosscheck_rows_s185.jsonl`
6. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602\manual_review_rows_s185.jsonl`
7. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_relation_identity_source_provider_acquisition_s217_after_s216_full_20260602\external_or_manual_acquisition_rows_s185.jsonl`

## DeepSeek TUI 应该做什么

按这个顺序做：

1. 先审 `provider_crosscheck_review` 的 38 行。
   - 这些是最接近 source-backed 的候选，但仍不是写库授权。
   - 每行要判断：同一艺人可合并、不同艺人必须保留、厂牌/场地/collective/lineup 不是 DJ、证据不足。

2. 再审 `manual_disposition_review` 的 93 行。
   - 重点识别 alias、复合名、中文/英文变体、艺名同名但不同人的情况。
   - 不允许只靠 normalized name 合并。

3. 最后审 `external_evidence_required` 的 217 行。
   - 这些当前缺 source-backed 证据。
   - DeepSeek TUI 只能列出需要补什么证据，不能自己联网抓取，不能拼搜索 URL。

## 输出建议

输出应是 draft-only，供主线程转成正式 packet。推荐字段：

```json
{
  "work_order_id": "...",
  "group_id": "...",
  "repair_lane": "provider_crosscheck_review|manual_disposition_review|external_evidence_required",
  "display_names": [],
  "dj_ids": [],
  "proposed_disposition": "merge_candidate|preserve_separate|non_person_or_lineup|needs_more_evidence",
  "source_backed": false,
  "confidence": 0.0,
  "evidence_ids": [],
  "missing_fields": [],
  "stop_gates": [],
  "reason": "短理由，不要编造事实"
}
```

如需要写入仓库，先让主线程确认输出路径；默认只生成文本/JSONL 草稿，不改 DB。

## 禁止动作

这些动作必须等主线程显式释放 S232D-4 或对应 controller release：

- 不写 DB1/DB2/DB3。
- 不执行 SQL writer、spool writer、projection。
- 不启动 Docker/worker/network/provider/model 批处理。
- 不读 cookie、token、`.env`、API key、浏览器 profile。
- 不发布、不上传、不 CloudBase sync、不 WeChat review。
- 不把 `merge_candidate` 当成 `approved_for_s232d4=true`。
- 不把 DeepSeek TUI 的文本判断当成 source-backed evidence。

## 什么时候能进入 S232D-4

只有同时满足：

1. 有 approved source-backed disposition / merge candidates。
2. 主线程显式签发 S232D-4 write gate。
3. write gate 包含：
   - single-writer lock
   - DB3 backup
   - transaction / rollback
   - no-empty-overwrite
   - identity redirect preservation
   - source_ref preservation
   - postwrite readback
   - rerun relation integrity audit
   - rerun deploy-upload preflight

当前全部未满足。

## 与上下游的关系

上游：

- Atlas DB3 是唯一上游事实库。
- S217/S232D-3B7 是当前只读 evidence/workbench。

下游：

- DB2 外链系统是消费者，不是 DB3 写门。
- 小程序/CloudBase/release guard 是消费者，不是 DB3 写门。
- 坐标 lane 的 coordinate write runtime 不解决 `db3_same_normalized_name_multi_id=348`。

## WSL2 / DeepSeek TUI 操作注意

在 WSL2 里使用：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
```

如果通过 DeepSeek TUI / mailroom 交付草稿，历史记忆里有 `D:\agent-comm\drafts`、outbox/result/ack 一类侧通信道；这些路径和端口可能已经漂移，使用前必须本地确认，不要把空 outbox 当成没有任务。

模型策略：

- 默认用直接 DeepSeek 路线，不能用 OpenRouter/Claude/Gemini/Anthropic。
- 只处理已脱敏/本地报告。
- 若输入包含 raw URL/private path/secret，先停并报告。

## 下一步最小任务

接手后先做一个小切片：

1. 读取 S232D-3B7 summary 和 repair rows。
2. 抽取 38 条 `provider_crosscheck_review`。
3. 产出只读草稿：哪些可能是 `merge_candidate`，哪些仍 `needs_more_evidence`，每条缺什么字段。
4. 报告给主线程；不要写 DB，不要开 S232D-4。

## 验证口径

完成后报告这些字段：

- `input_rows_reviewed`
- `merge_candidate_draft_count`
- `preserve_separate_draft_count`
- `non_person_or_lineup_draft_count`
- `needs_more_evidence_count`
- `source_backed_candidate_count`
- `approved_for_s232d4_count=0`
- `db_write_executed=false`
- `raw_url_private_path_secret_leak_count=0`
