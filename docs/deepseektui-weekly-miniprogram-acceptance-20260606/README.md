# DeepSeekTUI Weekly Mini-Program Acceptance Pack - 2026-06-06

## 一句话接手口径

当前本地 155 条小程序周活动包已修复 aggregate-child 海报 fileId、POOLS/RUAALAB/Tin/Cedar 地理信息、TRUST 厂牌误作场地问题；本地质量门和前端相关测试通过，但 CloudRun 未部署、小程序体验版未上传、微信审核未提交。

## DeepSeekTUI 先读顺序

1. `README.md` - 当前状态和边界。
2. `DEEPSEEK_TUI_RUNBOOK.md` - WSL2 DeepSeekTUI 接手执行步骤。
3. `CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md` - WSL2 打通 Windows DevTools CLI、本地全覆盖测试和调试链路。
4. `DEEPSEEK_NEXT_LOGIC_REFACTOR_PLAN_20260606.md` - 下一阶段逻辑整理、解耦顺序、测试合同和禁止项。
5. `SUPERPOWERS_WEEKLY_MINIPROGRAM_LOGIC_REFACTOR_DESIGN.md` - Superpowers Brainstorming 设计稿。
6. `SUPERPOWERS_WEEKLY_MINIPROGRAM_LOGIC_REFACTOR_PLAN.md` - Superpowers Writing Plans 任务级执行计划。
7. `WORKLOG_AND_EVIDENCE.md` - 本轮工作日志、文件、命令、证据。
8. `NEXT_OPTIMIZATION_PLAN.md` - 后续优化方向、原因、验收门。
9. `../WEEKLY_MINIPROGRAM_AGG_CHILD_POSTER_AND_GEO_REPAIR_20260606.md` - 细节事实源。

## 当前确认状态

### Confirmed

- 本地当前包路径：`services/weekly_activity_cloudrun/data/current_release`
- 当前包 `item_count=155`
- 当前包质量门最新报告：`tools/stage7_rewrite/reports/weekly_current_quality_deepseektui_cli_full_coverage_20260606.json`
- 质量门结果：`ok=true`
- CloudBase 内网海报：`missing_internal_poster_count=0`
- aggregate-child 父文跳转：`aggregate_child_source_enabled_count=0`
- 地理坐标：`missing_geo_count=0`（TRUST `阿派朗创造力星球(朝阳公园店)` geo 已补入: `39.947645, 116.484822`，event_date=2026-06-13）

### Not Done / Partially Done

- 未部署 CloudRun。
- 未写 CloudBase 数据库。
- 未上传微信小程序体验版。
- 未提交微信审核。
- DevTools 渲染已验证（2026-06-07）：36/36 海报通过 CloudBase 临时 URL 渲染，0 异常，0 公网 qpic 泄漏。测试断言 `expectedMinItems=74` 因日期窗口滑动（06-05→06-07）过期，实际 36 条从 06-07 起正确展示。

## DeepSeekTUI 绝对不要误操作

- 不要把本地质量门 `ok=true` 当成线上已生效。
- 不要清空 aggregate-child 的 `cloud://.../weekly-posters/...` 海报 fileId。
- 不要把 TRUST 当固定场地写坐标；TRUST 是音乐厂牌/主办，场地必须从公众号原文标题或正文抽取。
- 不要从公网 `mmbiz.qpic.cn` 当小程序包内海报真相；包内真相必须是 CloudBase `cloud://` fileId。
- 不要读 `.env.local`、cookie、浏览器登录态、私钥或其他 secret。
- 不要清理当前脏工作树；本 repo 已有大量历史未跟踪/修改文件。

## 当前可执行下一步

1. TRUST `阿派朗创造力星球(朝阳公园店)` geo 已于 2026-06-07 验证确认补入（`39.947645, 116.484822`），`missing_geo_count=0`。
2. Python 单测（validate / repair / apply_manual_place_overrides）和 Node 前端测试（cloud-poster-url / page-source-routing / source-articles / poster-pool / production-data-source / detail-map-location / devtools-launch-default）从本机跑。
3. DevTools 渲染已过：36 条从 06-07 起的条目正确渲染，全部海报走 CloudBase 临时 URL，无异常。测试脚本的 `expectedMinItems` 阈值需按当前日期更新（非阻塞）。
4. 只有在用户明确授权后，才进入 CloudRun 部署和微信开发者工具上传。

## 给 DeepSeekTUI 的启动提示词

```text
你在 WSL2 DeepSeekTUI 中接手 HUAIDJ weekly mini-program 修复任务。
先读 /home/pc/deepseektui-handoffs/weekly-miniprogram-20260606/README.md，
再读同目录的 DEEPSEEK_TUI_RUNBOOK.md、CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md、DEEPSEEK_NEXT_LOGIC_REFACTOR_PLAN_20260606.md、SUPERPOWERS_WEEKLY_MINIPROGRAM_LOGIC_REFACTOR_DESIGN.md、SUPERPOWERS_WEEKLY_MINIPROGRAM_LOGIC_REFACTOR_PLAN.md、WORKLOG_AND_EVIDENCE.md、NEXT_OPTIMIZATION_PLAN.md。
工作 repo 在 /mnt/c/code/githubstar/wechathtmldownload。
当前本地包已通过质量门，但未部署、未上传体验版。
你的第一任务：补最后一个缺 geo 的场地“阿派朗创造力星球(朝阳公园店)”并验证 missing_geo_count=0。
下一阶段不要直接大重构，先写 poster/source/date/geo/current feed 数据合同和 Loopy/DJ Love/Love Bang/POOLS/TRUST 回归测试，再按 api.js -> format.js -> index loadData 小步拆分。
遵守边界：不读 secrets，不部署/上传，除非用户明确授权。
```
