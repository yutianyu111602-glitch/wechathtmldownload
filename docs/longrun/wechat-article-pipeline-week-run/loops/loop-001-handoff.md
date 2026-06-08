<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 001 Handoff: US-001 Freeze Baseline Evidence

时间：2026-04-27 13:20 +08
状态：passed
Story：US-001 Freeze baseline evidence

## 已完成

- 完整扫描权威文档、新旧产物、管线目录。
- 冻结所有关键计数和状态。
- 确认无冲突写入进程。
- 未修改任何生产数据。

## 基线事实

### 目录存在性

| Path | Exists | Type | DirectDirs | DirectFiles | LastWrite |
| --- | --- | --- | --- | --- | --- |
| D:\rawwechat | True | dir | 32 | 0 | 2026/4/21 16:04 |
| D:\rawwechat_md | True | dir | 27 | 2 | 2026/4/21 03:58 |
| D:\rawwechat_archive | False | - | 0 | 0 | - |
| D:\rawwechat_llm_artifacts | False | - | 0 | 0 | - |
| D:\DDownload\_llm_release | True | dir | 1 | 0 | 2026/4/26 20:29 |
| D:\DDownload\_llm_release\articles | True | dir | 49 | 0 | 2026/4/26 21:29 |
| D:\DDownload\_llm_artifacts | True | dir | 63 | 103 | 2026/4/26 21:18 |
| D:\DDownload\_llm_md | True | dir | 63 | 0 | 2026/4/25 21:18 |
| D:\DDownload\_archive_mptext | True | dir | 63 | 7 | 2026/4/24 00:18 |

### 递归计数

- rawwechat_html: 8095
- rawwechat_md: 3146
- release_clubs: 49
- release_article_dirs: 68733

### MarkItDown 状态

- status: running
- startedAt: 04/20/2026 17:48:16
- endedAt: (empty)
- total: 8095
- succeeded: 3146
- failed: 0
- skipped: 0
- completed: 3146
- currentFile: D:\rawwechat\loopy Club\html\20161026_11_13 周日｜兵马司唱片呈现Future Orients 全新专辑《Eat or Die》全国巡演杭州站_kI5WNi0LLOBQ5e0ID9aOtQ.html
- items: queued=4948, running=1, succeeded=3146

### L1/L2 产物

- l1_part1: 65794
- l1_part2: 1417
- l1_total: 67211
- l2_unique: 94
- l2_content_type: 91
- l2_null: 3

### 进程扫描

- no conflicting node/llama rawwechat writer process found

## 验证

- 所有计数通过 PowerShell 直接读取。
- MarkItDown JSON 解析成功。
- 无生产数据修改。

## 下一步

US-002: 备份并修复 MarkItDown stale running 状态。
