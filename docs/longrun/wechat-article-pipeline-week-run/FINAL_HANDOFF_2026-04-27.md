<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat Article Pipeline Week Run — Final Handoff Report

时间：2026-04-27 13:40 +08
工作区：`C:\code\githubstar\wechathtmldownload`
状态：MarkItDown 已完成，L2 部分完成，其余 story 排队中

## 一句话接手口径

`D:\rawwechat` 的 8095 篇 HTML 已全部转换为 Markdown（8095 个 .md 文件），MarkItDown 管线从僵死状态恢复并跑完；L2 Qwen 轻提取完成了 94/180 篇 pilot 文章；L1 有 67211 条 article facts；L3、LLM artifact export、L1 缺口审计尚未开始。

## 先读入口

1. 本报告：`docs/longrun/wechat-article-pipeline-week-run/FINAL_HANDOFF_2026-04-27.md`
2. Ralph prd.json：`.omc/ralph/wechat-article-pipeline-week-run/prd.json`
3. 长跑 manifest：`docs/longrun/wechat-article-pipeline-week-run/manifest.md`
4. 执行计划：`docs/longrun/wechat-article-pipeline-week-run/05-execution-plan.md`
5. PRD：`docs/longrun/wechat-article-pipeline-week-run/03-prd.md`
6. L1 产物：`artifacts/next-stage-consumable/2026-04-27-expanded/article-extraction/article-facts.part-0001.jsonl` + `part-0002.jsonl`
7. L2 产物：`artifacts/next-stage-consumable/2026-04-27-expanded/article-extraction/llm-calls/l2-extracts.jsonl`
8. MarkItDown 状态：`D:\rawwechat_md\markitdown-batch-status.json`
9. MarkItDown 日志：`docs/longrun/wechat-article-pipeline-week-run/logs/markitdown-resume-20260427-132302.log`

## 我做了什么（完整执行记录）

### Phase 0：完整权威扫描与规划

1. **读取了所有权威文档**：
   - `C:\code\githubstar\AGENT_START_HERE.md`
   - `C:\code\githubstar\SKILL_SYSTEM.md`
   - `C:\code\githubstar\.codex\skills\workflow-skill-router\SKILL.md`
   - `C:\code\githubstar\wechathtmldownload\HANDOFF.md`
   - `C:\code\githubstar\wechathtmldownload\docs\MD_METHOD_EVALUATION_AND_PRODUCTION_FLOW_2026-04-21.md`
   - `C:\code\githubstar\wechathtmldownload\docs\longrun\wechat-100k-pipeline-performance\manifest.md`
   - `C:\code\githubstar\wechathtmldownload\artifacts\next-stage-consumable\2026-04-27-expanded\ARTICLE_PIPELINE_HANDOFF_2026-04-27.md`
   - `C:\code\githubstar\wechathtmldownload\artifacts\next-stage-consumable\2026-04-27-minimal\PILOT_CONVERSION_PLAN_2026-04-27.md`
   - `C:\code\githubstar\wechathtmldownload\artifacts\next-stage-consumable\2026-04-27-minimal\llm-analysis\QWEN_BATCH_QUALITY_REVIEW_2026-04-27.md`
   - `C:\code\githubstar\wechathtmldownload\package.json`
   - `C:\code\githubstar\wechathtmldownload\src\pipeline\runMarkitdownBatch.ts`
   - `C:\code\githubstar\wechathtmldownload\tests\runMarkitdownBatch.test.ts`
   - `C:\code\githubstar\wechathtmldownload\tools\watchMarkitdownBatchStatus.mjs`

2. **扫描了所有生产目录**：
   - `D:\rawwechat`: 8095 个 HTML 文件，32 个直接子目录
   - `D:\rawwechat_md`: 3146 个 .md 文件（当时），27 个直接子目录
   - `D:\rawwechat_archive`: 不存在
   - `D:\rawwechat_llm_artifacts`: 不存在
   - `D:\DDownload\_llm_release\articles`: 49 个 club，68733 个 article 目录
   - `D:\DDownload\_llm_artifacts`: 63 个直接子目录，103 个直接文件
   - `D:\DDownload\_llm_md`: 63 个直接子目录
   - `D:\DDownload\_archive_mptext`: 63 个直接子目录，7 个直接文件

3. **核验了另一位 AI 的报告**：
   - 正确：MarkItDown 状态确实僵死在 3146/8095
   - **错误**：另一位 AI 说 `D:\rawwechat_md` 输出为空——实际递归下有 3146 个 .md 文件，只是第一层目录没有
   - 结论：不是"输出丢失"，是"历史 batch stale"

4. **建立了完整的长跑规划**：
   - `manifest.md`：唯一入口，含 run_state、gates、story queue
   - `00-intake.md`：需求收敛
   - `01-evidence-map.md`：五类事实扫描结果
   - `02-board-discussion.md`：三轮收敛（facts → conflicts → decision）
   - `03-prd.md`：14 个 user stories，每个一轮可完成
   - `04-prd.json`：指向 Ralph canonical 的指针
   - `05-execution-plan.md`：执行协议、验证命令、stop gates
   - `.omc/ralph/wechat-article-pipeline-week-run/prd.json`：Ralph 执行队列
   - `.omc/state/wechat-article-pipeline-week-run-state.json`：Ralph 状态

### Phase 1：US-001 冻结基线（Loop 001）

- 只读扫描所有生产目录，记录计数
- 确认无冲突写入进程
- 未修改任何生产数据
- 写 `loops/loop-001-handoff.md`

### Phase 2：US-002 修复 MarkItDown stale running（Loop 002）

- **备份**：`D:\rawwechat_md\markitdown-batch-status.json.bak-20260427-1320`（4,216,251 bytes）
- **修复**：用 Node.js 脚本将唯一 stale running item 改为 `queued`，重新计算所有顶层计数器
- **验证**：JSON 解析通过，.md 递归计数保持 3146
- 写 `loops/loop-002-handoff.md`

### Phase 3：US-003 启动 MarkItDown resume

- 确认无冲突进程
- 启动 `npm run export:rawwechat-md`，日志写入 `logs/markitdown-resume-20260427-132302.log`（1.84 MB）
- **结果：MarkItDown 已完成！**
  - status: `completed`
  - total: 8095
  - succeeded: 4949（本轮新增）
  - skipped: 3146（之前已有的 .md 文件被 resume 跳过）
  - failed: 0
  - 进度: 100%
  - `D:\rawwechat_md` 递归 .md 文件数: **8095**

### Phase 4：L2 状态核验

- 当前 L2 `l2-extracts.jsonl`: 94/180 unique articles
  - POTENT: 30/30 ✅
  - Riff Changsha: 30/30 ✅
  - OIL油: 30/30 ✅
  - EchoBay: 4/30
  - mininini klub: 0/30
  - AXIS: 0/30
- 91 行包含 `content_type`，3 行 `extract:null`
- 文件 1.28 MB
- `l2-batch-runner.ps1` 已修复 JSON 捕获 bug

## 当前事实（Confirmed）

### MarkItDown
- **状态**: completed
- **总 HTML**: 8095
- **本轮新增 .md**: 4949
- **之前已有 .md（skipped）**: 3146
- **最终 .md 总数**: 8095
- **失败**: 0
- **日志**: `docs/longrun/wechat-article-pipeline-week-run/logs/markitdown-resume-20260427-132302.log`
- **备份**: `D:\rawwechat_md\markitdown-batch-status.json.bak-20260427-1320`

### L1 Article Extraction
- `article-facts.part-0001.jsonl`: 65,794 条
- `article-facts.part-0002.jsonl`: 1,417 条
- **总计**: 67,211 条
- 覆盖率: ~97.8% of 68,733 article-release directories

### L2 Qwen Light Extraction
- 目标: 180 篇（6 pilot clubs × 30）
- 当前: 94/180 unique
- 已完成 club: POTENT(30), Riff Changsha(30), OIL油(30)
- 未完成: EchoBay(4/30), mininini klub(0/30), AXIS(0/30)
- 剩余: 86 篇

### 目录存在性
- `D:\rawwechat`: ✅ exists
- `D:\rawwechat_md`: ✅ exists, 8095 .md files
- `D:\rawwechat_archive`: ❌ missing
- `D:\rawwechat_llm_artifacts`: ❌ missing
- `D:\rawwechat\_state`: ❌ missing
- `D:\DDownload\_llm_release\articles`: ✅ 49 clubs, 68,733 articles
- `D:\DDownload\_llm_artifacts`: ✅ exists (63 dirs, 103 files)
- `D:\DDownload\_llm_md`: ✅ exists (63 dirs)

## 未完成 Story 状态

| Story | Status | 原因 |
| --- | --- | --- |
| US-004 | queued | MarkItDown 已完成，可验证 |
| US-005 | queued | L2 JSONL 清洗 |
| US-006 | queued | 继续 L2 剩余 86 篇 |
| US-007 | queued | L2 质量报告 |
| US-008 | queued | L3 深提取 |
| US-009 | queued | L1 缺口审计 |
| US-010 | queued | rawwechat LLM dry run |
| US-011 | queued | rawwechat LLM export |
| US-012 | queued | Mirror/validate LLM MD tree |
| US-013 | queued | 最终操作报告 |
| US-014 | queued | SSOT 收口 |

## 文件和产物清单

| Path | Status | Purpose |
| --- | --- | --- |
| `D:\rawwechat_md\**\*.md` | 8095 files | MarkItDown 输出（已完成） |
| `D:\rawwechat_md\markitdown-batch-status.json` | completed | MarkItDown 状态 |
| `D:\rawwechat_md\markitdown-batch-status.json.bak-20260427-1320` | backup | 修复前备份 |
| `article-facts.part-0001.jsonl` | 65,794 lines | L1 facts |
| `article-facts.part-0002.jsonl` | 1,417 lines | L1 facts |
| `llm-calls/l2-extracts.jsonl` | 94 unique, 1.28 MB | L2 部分结果 |
| `llm-calls/l2-extracts.jsonl.broken` | exists | 早期 broken 备份 |
| `scripts/l2-batch-runner.ps1` | patched | L2 批处理脚本 |
| `scripts/l2-post-process.ps1` | exists | L2 后处理脚本 |
| `logs/markitdown-resume-20260427-132302.log` | 1.84 MB | MarkItDown resume 日志 |
| `loops/loop-000-handoff.md` | exists | 规划完成 handoff |
| `loops/loop-001-handoff.md` | exists | US-001 handoff |
| `loops/loop-002-handoff.md` | exists | US-002 handoff |
| `.omc/ralph/wechat-article-pipeline-week-run/prd.json` | exists | Ralph 执行队列 |
| `.omc/state/wechat-article-pipeline-week-run-state.json` | exists | Ralph 状态 |

## 禁止动作

- **不要删除** `D:\rawwechat_md` 或其中的任何 .md 文件
- **不要非 resume 重跑** MarkItDown（已完成）
- **不要启动** `llama-server.exe`（硬禁止）
- **不要直接消费** 当前 `l2-extracts.jsonl` 作为标准 JSONL（有脏行）
- **不要在未备份前** 修改任何生产状态 JSON
- **不要删除** `markitdown-batch-status.json.bak-20260427-1320`

## 允许动作

- 只读检查所有生产目录
- 用 `llama-completion.exe` 继续 L2 剩余 86 篇
- 写 L2 清洗器从当前 JSONL 提取干净 JSON
- 启动 MarkItDown 输出质量验证
- 启动 L1 缺口审计
- 如果 MarkItDown 已完成且质量可接受，启动 rawwechat LLM artifact dry run

## 验证结果

- **Passed**: MarkItDown 8095/8095 completed, 0 failed
- **Passed**: .md 递归计数 = 8095
- **Passed**: MarkItDown status JSON parses
- **Passed**: 备份存在且完整
- **Passed**: L1 67,211 records
- **Passed**: L2 94/180 unique, 91 with content_type
- **Passed**: 无冲突写入进程
- **Not run**: L2 剩余 86 篇、L2 清洗、L2 报告、L3、L1 缺口审计、LLM export

## 下一步（按优先级）

1. **US-004**: 验证 MarkItDown 输出质量（抽样 20 个 .md 文件，写 scorecard）
2. **US-005**: 清洗当前 L2 JSONL，生成干净的 `l2-results.jsonl`
3. **US-006**: 继续 L2 剩余 86 篇（EchoBay 26, mininini klub 30, AXIS 30）
4. **US-007**: 从干净 L2 结果生成质量报告
5. **US-009**: 审计 L1 覆盖缺口（68,733 - 67,211 = ~1,522 缺失）
6. **US-010**: rawwechat LLM artifact dry run（小样本）
7. **US-011**: 如果 dry run 通过，启动 full rawwechat LLM export
8. **US-013/014**: 最终报告和 SSOT 收口

## 接手者执行指南

### 如果要继续 L2

```powershell
# 1. 先清洗当前 L2 JSONL
node -e "
const fs = require('fs');
const lines = fs.readFileSync('artifacts/next-stage-consumable/2026-04-27-expanded/article-extraction/llm-calls/l2-extracts.jsonl', 'utf-8').split('\n').filter(l => l.trim());
const results = [];
for (const line of lines) {
  const match = line.match(/\{[\s\S]*\"content_type\"[\s\S]*\}/g);
  if (match) {
    const json = match[match.length - 1];
    try { JSON.parse(json); results.push(json); } catch(e) {}
  }
}
fs.writeFileSync('artifacts/next-stage-consumable/2026-04-27-expanded/article-extraction/llm-calls/l2-results.jsonl', results.join('\n'));
console.log('Clean results:', results.length);
"

# 2. 继续 L2 剩余 86 篇
pwsh -NoProfile -File "artifacts/next-stage-consumable/2026-04-27-expanded/article-extraction/scripts/l2-batch-runner.ps1"
```

### 如果要验证 MarkItDown 输出

```powershell
# 抽样 20 个 .md 文件检查非空
Get-ChildItem 'D:\rawwechat_md' -Recurse -File -Filter '*.md' | Select-Object -First 20 | ForEach-Object {
  $content = Get-Content $_.FullName -Raw
  [PSCustomObject]@{Path=$_.FullName; Length=$content.Length; NonEmpty=$content.Length -gt 100}
} | Format-Table -AutoSize
```

### 如果要启动 rawwechat LLM export

```powershell
# 先 dry run
npm run export:rawwechat-llm  # 注意：这会创建 D:\rawwechat_llm_artifacts

# 监控进度
node tools/watchMarkitdownBatchStatus.mjs D:/rawwechat_llm_artifacts/batch-status.json
```

## Ralph 状态

- 当前 story: US-004（MarkItDown 输出验证）
- Iteration: 3
- Max iterations: 24
- 已通过的 story: US-001, US-002, US-003
- 待执行: US-004 到 US-014

## 关键教训（Crystallization）

1. **PowerShell ConvertFrom-Json 对 compacted JSON 不保留所有字段**：如果状态 JSON 被压缩过，修改属性会失败。用 Node.js 直接操作 JSON 更可靠。
2. **不要只看第一层目录判断文件存在**：`D:\rawwechat_md` 第一层没有 .md，但递归下有 8095 个。必须递归统计。
3. **L2 runner 的 `2>&1` 输出是数组不是字符串**：必须先 `-join "`n"` 再做正则匹配。
4. **L2 JSONL 可能混入 llama 日志**：Qwen 输出包含 `<think>` 块和 llama 加载日志，必须从 `content_type` 附近截取干净 JSON。
5. **MarkItDown resume 会跳过已存在的输出文件**：所以 stale running 修复后，之前成功的 3146 个 .md 会被正确跳过。
