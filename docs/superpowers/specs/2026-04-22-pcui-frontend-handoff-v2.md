<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI Frontend Handoff v2

Date: 2026-04-22

> 2026-04-23 UI-only 口径更新：本文保留为 PCUI frontend 历史交接和 contract 背景，不再作为当前 UI 事实源。当前 UI 设计与工程唯一事实源是 `docs/superpowers/specs/pcui-final-ssot.md`；当前 UI-only 执行 track 是 `docs/superpowers/specs/2026-04-23-pcui-ui-only-ralph-prd.md`、`docs/superpowers/plans/2026-04-23-pcui-ui-only-consolidation-plan.md`、`.omc/ralph/pcui-ui-only-consolidation/prd.json` 和 `.omc/state/pcui-ui-only-ralph-state.json`。

## 定位

`WeChat History HTML Pipeline` 的桌面端定位固定为：

- Operator Console
- Pipeline Workbench
- Artifact Manager

这不是网页后台、dashboard、AI 展示页或 landing page。目标用户是长期运行本地公众号归档、下载、转换、LLM 导出和最终产物审查的 power user。

## 固定 Shell

前端必须收敛到同一个桌面 shell：

```text
titlebar
commandbar
navigation rail | main table | right inspector
bottom run console
statusbar
```

规则：

- `commandbar` 随当前工作区切换动作、筛选、搜索和紧凑计数。
- `main table` 是每个工作区的主视口；统计不能做成卡墙。
- `right inspector` 只跟随当前选择；无选择时短空态。
- `bottom run console` 只承接活动流、失败流和系统消息。
- `statusbar` 只保留一行事实：工作区、root/profile、运行锁、进度、错误、刷新时间。

## 设计系统

主参考：

- Cloudscape 的操作台纪律：状态、布局节奏、工作台稳定性。

辅助参考：

- Fluent 的 Windows 控件状态。
- Spectrum 的清晰状态表达。

明确拒绝：

- hero
- overview dashboard
- 统计卡墙
- monitor card 作为主结构
- 紫粉 AI 渐变
- glow / neon / glassmorphism
- 过度圆角、阴影、blur
- 网页后台模板

## 工作区主对象

| 工作区 | 主对象 | 主数据源 |
|---|---|---|
| 任务总线 | job / run | `batch:snapshot`, `batch:get-latest-snapshot` |
| 采集与账号 | account | `collect:get-state` |
| 归档与下载 | archive bundle / article task | `archive:get-state`, `audit:get-projection`, mptext status/results |
| 处理与导出 | article bundle | `process:get-state`, live snapshot fallback |
| LLM 子态 | llm input / downstream row | `process:get-state`, `batch:snapshot` for `llm-export` |
| 产物与审查 | final pack row | `pack:get-projection` |

## 契约冻结

必须保持稳定：

- `window.wechatDesktop` IPC surface。
- `batch:snapshot` 和 `batch:error`。
- `accepted:true` 只代表命令被接受，不能显示成阶段完成。
- root 语义：`discoveryRoot`, `archiveRoot`, `artifactRoot`, `markdownMirrorRoot`, `releaseRoot`, `mptextRoot`。
- 状态字典：`archived`, `partial`, `deferred`, `waiting_batch`, `pending`, `done`, `ready`, `review`, `blocked` 等。
- stable row key：final pack 不允许只靠 token。
- live mptext download lock：同 archive root 的维护/写入命令必须禁用，并由后端返回 `accepted:false`。

## 模块需求

### 总界面

- 左侧五工作区 rail。
- 顶部 commandbar 随工作区变化。
- 主视口 table-first。
- inspector 跟随选择。
- console 只显示事件流。
- statusbar 一行事实。

### 下载界面

- 一行一个 `archive bundle / article task`。
- 字段：token、账号、sourceUrl、capture、assets、HTML/MHTML/PDF 完整度、最近错误、异常码。
- mptext 监控压缩到 commandbar / console / statusbar，不做 header 统计卡。

### 数据预处理 / 转 MD

- 一行一个 `article bundle`。
- 字段：phase、quality、sidecar、llm_input、OCR、downstream、warnings。
- 动作：重跑处理、导出 LLM、打开 bundle、查看 quality warning。

### LLM 子态

- 从 `处理与导出` 切换进入，不新建聊天式页面。
- 围绕 `llm_input.md`、mirror markdown、downstream manifest/result、provider readiness、最近错误组织。
- 禁止出现聊天气泡、AI 助手头像、prompt hero、模型营销卡。

### 账号采集

- 一行一个 account。
- 字段：fakeid、昵称、发现数、入队数、重复数、最近发现、错误。
- 动作：导入账号清单、刷新发现、打开 ready queue、筛异常、筛 Queue>0。

### 产物审查

- 一行一个 final pack row。
- 字段：ready/review/blocked、warning_count、图片数、正文字符、背景召回字符。
- 动作：生成 pack、打开 release、筛质量桶、抽查 provenance。

## 出图管线

执行工具：

- dry run: `npm run pcui:image:prompts`
- access gate: `npm run pcui:image:verify`
- generation: `npm run pcui:image:generate`

输出目录：

- `tmp-pcui-images/gpt-image-2/prompts`
- `tmp-pcui-images/gpt-image-2/prompt-manifest.json`
- `tmp-pcui-images/gpt-image-2/image-generation-manifest.json`

门禁：

- 如果没有 API key，或 `gpt-image-2` 未授权，记录失败并停止，不伪造图片完成。
- 只有图像评审 note 选定 baseline、各模块变体和 master board 后，才开始下一轮 1:1 UI 大改。

## 实现顺序

1. 冻结契约与状态字典。
2. 生成 prompt 和图片门禁结果。
3. 生成模块图与 master board。
4. 写图像评审 note。
5. 拆 `renderer.js`：state、root/profile、workspace controller、projection adapter、inspector、command dispatch、console/statusbar。
6. 重构 shell。
7. 重构工作区：任务总线 -> 采集与账号 -> 归档与下载 -> 处理与导出 -> LLM 子态 -> 产物与审查。
8. runtime 截图验证。

## 验收

- 主表永远能定位 live 当前对象。
- root 切换、projection 缺失、读取失败时清空 stale rows 和 stale inspector。
- `accepted:true` 不伪装完成。
- background lock 文案和后端拒绝一致。
- screenshot 无 hero、无 dashboard 卡墙、无装饰渐变、无大圆角主结构。
