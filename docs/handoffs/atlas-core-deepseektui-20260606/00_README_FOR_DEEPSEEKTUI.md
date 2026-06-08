# Atlas Core DeepSeekTUI 接手包

生成时间：2026-06-06 15:56 CST
仓库：`C:\code\githubstar\wechathtmldownload`
WSL 仓库路径：`/mnt/c/code/githubstar/wechathtmldownload`
状态：report-local candidate accepted for shadow/read-model work; production promotion not approved

## 一句话口径

Atlas Core 三库合一第一阶段已经形成可验收的 report-local 核心库和旧库兼容导出，API shadow diff 从 9 个回归压到 0 个；DeepSeekTUI 下一步只能接手优化、审阅、扩充 shadow/coverage 和身份审批包，不能写生产 DB 或切换线上指针。

## 先读顺序

1. `00_README_FOR_DEEPSEEKTUI.md`：入口和边界。
2. `01_ACCEPTANCE_REPORT.md`：已验收证据、未验收范围、核心计数。
3. `02_EXECUTION_LOG.md`：本轮工作日志、修复路径、验证命令。
4. `03_NEXT_OPTIMIZATION_PLAN.md`：DeepSeekTUI 接下来怎么优化、为什么这么排。
5. `04_DEEPSEEKTUI_RUNBOOK.md`：WSL2 运行/复核命令、禁止动作、停止门。
6. `05_WEAPONS_SKILLS_TOOLS.md`：使用的 skill、脚本、测试和工具。
7. `06_HIGHLIGHTS_PITFALLS.md`：亮点、坑点、容易误判的地方。
8. `07_COMPASS_PROMPT_FOR_DEEPSEEK.md`：可直接贴给 DeepSeekTUI 的接手 prompt。
9. `08_DEEPSEEK_NEXT_PLAN_DESIGNED_BY_CODEX.md`：Codex 设计的 DeepSeek 下一轮计划和第一批执行边界。
10. `docs/superpowers/specs/2026-06-06-atlas-core-deepseektui-next-optimization-design.md`：superpowers brainstorming 设计 spec。
11. `docs/superpowers/plans/2026-06-06-atlas-core-deepseektui-next-optimization.md`：superpowers writing-plans 执行计划。

## 当前权威入口

- 仓库文档索引：`docs/DOCUMENTATION_INDEX.md`
- Atlas Core 原始接手文档：`docs/handoffs/HANDOFF_ATLAS_CORE_CANDIDATE_20260605.md`
- 本 DeepSeekTUI 接手包：`docs/handoffs/atlas-core-deepseektui-20260606/`

## 关键产物

- 最终候选目录：`tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/`
- 核心库：`atlas_core.sqlite`
- 旧 serving 导出候选：`atlas_serving.sqlite`
- 小程序 sqlite 导出候选：`atlas_miniapp.sqlite`
- 小程序压缩索引候选：`atlas_index.json.gz`
- 安全执行报告：`atlas_core_safe_execution_report.json`
- API shadow diff：`tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_report.json`

## DeepSeekTUI 的角色

DeepSeekTUI 是 WSL2 里的长跑分析/优化 sidecar，不是生产写入者。

可以做：

- 读本接手包和证据文件。
- 生成候选优化建议、shadow path 扩充方案、coverage 解释包、identity approval packet 草稿。
- 对 DB2/OpenClaw external-link、DB3 identity case、旧库兼容 read model 做有证据的分析。
- 输出需要 Codex 或人工复核的候选 Markdown/JSONL。

不能做：

- 写 DB1/DB2/DB3 生产库。
- 覆盖 production `atlas_serving.sqlite`、`atlas_miniapp.sqlite`、`atlas_index.json.gz`。
- 执行 DB3 S232D-4 merge/write。
- 部署 CloudRun/VPS/huaidj.club。
- 上传、提审、发布小程序。
- 读取 `.env`、cookies、token、SSH key、浏览器 profile 或任何密钥。
- 扫描 `D:\`、`D:\DDownload`、`D:\aidata`、`/mnt/d` 根目录。

## WSL2 接手目录

本包会镜像到 DeepSeekTUI 既有 handoff 根目录：

- Linux 主入口：`/home/pc/deepseektui-handoffs/atlas-core-20260606`
- Windows UNC 主入口：`\\wsl.localhost\Ubuntu\home\pc\deepseektui-handoffs\atlas-core-20260606`

兼容镜像也保留在：

- Linux mirror：`/home/pc/deepseektui_handoffs/atlas-core-20260606`
- Windows UNC mirror：`\\wsl.localhost\Ubuntu\home\pc\deepseektui_handoffs\atlas-core-20260606`

仓库内同源目录：

- Windows：`C:\code\githubstar\wechathtmldownload\docs\handoffs\atlas-core-deepseektui-20260606`
- WSL：`/mnt/c/code/githubstar/wechathtmldownload/docs/handoffs/atlas-core-deepseektui-20260606`
