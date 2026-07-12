# Atlas / Weekly 技术收口（2026-07-12）

本页记录 2026-07-12 Sanji -> Atlas v2、weekly 发布、CloudBase 热库、Git 可复现性与文档构建的终态。旧 handoff 与旧候选若冲突，以本页和实时读回为准。

## Provider 与运行入口

- Weekly publish 的默认海报模式为 `legacy_ocr`。
- Atlas 海报走本地 RapidOCR，只有 OCR 文本发送给 direct DeepSeek（`ocr_deepseek`）。
- 活跃计划任务默认路径不再使用 cloud Qwen/MiMo；Ollama 仍只允许 embedding。

## Sanji -> Atlas v2

- 正式 Hermes run：`E:\atlas_v2_import_runs\run_20260712_125216`。
- 从 checkpoint `138690` 消费 2 篇可导出增量：`text_complete=1`、`needs_vision=1`。
- 18 个记录步骤全部 return code `0`；phase3 gate 与 canonical gate 全绿。
- checkpoint 与 cumulative candidate state 原子推进到 `138692`。
- canonical serving candidate：`E:\atlas_v2_import_runs\run_20260712_125216\canonical_serving_candidate.sqlite`。
- SHA256：`e5393768d60cbf3f7f57727ab2dd539c7b09c74b9621b05a853ecf510906b2b4`；本地与生产一致。

弱键裁决本轮选择 2,822 行，保守估算花费约 `¥3.0637`：

- `merge=2622`
- `keep_separate=50`
- `needs_human=50`
- `pending_llm=100`（模型返回缺项，继续 fail-closed，不参与合并）

最终 canonical 数据：

- canonical events：`205243`
- canonical event members：`512178`
- canonical DJ-event：`630194`
- canonical DJ profiles：`55525`
- DJ identity redirects：`1757`
- venue identity redirects：`1346`

## VPS 生产读回

- 服务：`baddj-cn` active。
- `/healthz=200`，`/artists=200`。
- raw compatibility tables：`57282` DJ、`512178` performance events、`133` cities。
- 上述 canonical tables 已在生产数据库内读回；`.prev` 回滚点保留。
- 当前网站代码仍以 raw compatibility tables 为主；本次事实是 canonical 数据层已部署，不把它写成所有前端查询都已切换 canonical。

## Sanji 后续边界

`E:\atlas_v2_import_runs\post_closeout_boundary_20260712_1321` 的只读导出报告：

- Sanji DB rows：`138811`
- shared checkpoint：`138692`
- 当前可导出 delta：`0`
- actionable missing HTML：`10`

剩余 10 行属于 Sanji 正文抓取边界，不是 Atlas 待消费队列；正文到位后由下一次单写增量自动处理。

## Weekly / CloudRun / CloudBase

- 当前质量通过 run：`tools\stage7_rewrite\reports\openclaw_weekly_daily_20260711_124938`。
- release package quality：`ok=true`，`487` events。
- CloudRun：`cloudrun_direct_api_deploy_verified`。
- CloudBase admin sync：`weekly_1783833576671`。
- 热库读回：`487` events / `29` cities / `1` AI summary，source=`cloudbase-database`。
- 管理同步使用一次性随机 token，收尾再次旋转；token 未打印、未写入仓库。

## Git 与测试

- 干净分支：`codex/atlas-canonical-serving`。
- 共享 dirty runtime 的 Atlas 同步前备份：`C:\code\.git-workspace-backups\wechathtmldownload\20260712-atlas-runtime-sync`。
- Atlas/CloudBase/CloudRun 定向 Python 测试：`34 passed`；canonical self-check 通过。
- 实际共享 Atlas 路径回归：`33 passed`；weekly provider default test 通过。
- CloudBase Node helper/dry-run 与 VPS deploy bash syntax 通过。

## 文档构建

- 项目 MkDocs 排除 `docs/vendor/**` 和历史同名 HTML；`mkdocs build --strict --clean` 通过。
- 根站排除嵌套 `docs/projects/**`，避免二次复制项目站；strict build 通过。
- 当前生成体积：项目站 `92.2 MB`，根站 `76.4 MB`，不再是此前多 GB 产物。

## 明确未执行

- 未上传新的微信小程序开发版。
- 未提交微信审核，未声明新的公开小程序版本。
- 未删除 `.prev`、历史 run、共享 dirty 工作或用户文件。
