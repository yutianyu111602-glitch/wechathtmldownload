<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PCUI UI Optimization Business PRD Report

更新时间：2026-04-23T21:40:00+08:00

## 1. 产品结论

PCUI 的所有 UI 优化计划已完成并通过验收。该交付把 PCUI 从“可运行的桌面壳”收口为“可接手、可验证、可持续演进的桌面操作台”。

本报告面向业务端，描述业务价值、用户能力、验收结果和后续使用边界。

## 2. 业务目标

PCUI 服务于 WeChat History HTML Pipeline 的本地桌面操作场景，核心目标是让操作人员在长时间任务运行中稳定观察、切换、定位、审查和验证任务状态。

本轮优化解决的问题：

- UI 文档入口分散，后续容易误用旧设计。
- 交互只靠静态断言，真实 Electron 行为缺少证据。
- 大任务列表、搜索、过滤和选中状态容易产生性能或状态回退。
- 右键菜单、Escape、键盘焦点、主题、窄屏布局等桌面工具高频交互缺少统一治理。
- 业务端缺少一套可复跑的 UI 验收门禁。

## 3. 用户角色

- 业务操作员：需要监控任务总线、采集、归档、处理导出、产物审查。
- 审查人员：需要在多 workspace 中定位异常、查看 inspector、使用右键动作。
- 长跑任务维护者：需要确认 UI 在 10W 级数据和长会话下不失控。
- 后续开发者：需要明确哪些 UI 规则不可回退，并有自动证据保护。

## 4. 已交付能力

### 4.1 统一桌面操作台

PCUI 保持 Windows desktop operator console 模式：

- titlebar
- commandbar
- navigation rail
- table-first workspace
- right inspector
- bottom run console
- statusbar

明确禁止 dashboard、landing hero、card wall、AI chat UI、装饰性渐变和网页后台视觉。

### 4.2 真实交互可靠性

已建立 Electron 真实交互 harness，覆盖：

- workspace switch
- process mode switch
- commandbar search
- table search
- filter switch
- context menu row-key
- Escape isolation
- console tab keyboard
- F6 focus-region cycle
- console collapse
- theme toggle

当前结果：`scenarioCount=14`，`consoleErrorCount=0`。

### 4.3 大列表性能和状态稳定性

保留 10W fake-DOM hard gate：

- `fixtureSize=100000`
- `maxVirtualDomRows=44`
- `pass=true`

同时新增真实 Electron performance trace：

- `operationCount=10`
- `maxDurationMs=16.6`
- `consoleErrorCount=0`

### 4.4 键盘和桌面效率

已集中治理：

- 文本输入区域不会误触发全局快捷键。
- 行级 Enter/Space 激活统一。
- F6 可在 workspace、inspector、console 间移动焦点。
- console tab 支持键盘切换。
- context menu 的 Escape 不会触发全局停止/取消。

### 4.5 Inspector 和右键动作可信

Inspector 独立 controller 接管 detail、extra、actions、multi-select model。

右键菜单不再从 `.row-sub` 文本猜目标，而是按 row dataset 解析：

- `data-row-key`
- `data-row-kind`
- `data-row-object-id`

业务意义：右键操作更可追踪，降低误操作风险。

### 4.6 深浅主题和长期使用舒适度

已完成 dark/light theme：

- 主题由 `desktop/pcuiThemeController.js` 管理。
- light theme 暗色残留已 token 化。
- 截图证据包含 `themePixels`，防止“manifest 写 light 但实际截图仍是 dark”的假阳性。
- reduced-motion 已覆盖，降低长时间操作中的动效干扰。

### 4.7 响应式桌面窗口

已覆盖 viewport：

- 900
- 1260
- 1440
- 1680
- 2200

right inspector 在窄屏隐藏时，commandbar compact inspector action 保证选中对象动作仍可达。

### 4.8 可复跑验收体系

业务端验收不依赖主观截图，已有命令化证据：

```powershell
npm run pcui:interact
npm run pcui:perf
npm run pcui:state-matrix
npm run pcui:ui-audit
npm run pcui:electron-perf
```

## 5. 验收标准和结果

| 验收项 | 结果 |
| --- | --- |
| UI-only Ralph stories | US-001 到 US-013 全部通过 |
| Interaction gate | pass=true, scenarioCount=14 |
| 10W fake-DOM perf | pass=true, maxVirtualDomRows=44 |
| State matrix | pass=true, scenarioCount=17 |
| UI audit | pass=true, checkCount=12 |
| Electron perf trace | pass=true, operationCount=10 |
| Build | pass |
| Tests | 172/172 pass |

## 6. 非目标

本轮没有改变：

- 下载业务逻辑
- 归档业务逻辑
- 处理/导出业务逻辑
- LLM/finalize 业务逻辑
- runner 业务流
- IPC 合同
- 远程执行链路

业务端如需要以上能力变化，应新建业务 PRD，不应复用本 UI-only track。

## 7. 发布建议

可以把本轮 PCUI UI 优化视作“UI 验收完成，可进入业务试用/回归”的状态。

建议业务试用时关注：

- 大批量任务运行中的实时可读性。
- 窄屏窗口下 inspector action 是否满足操作习惯。
- light/dark theme 是否符合现场环境。
- 键盘操作路径是否符合高频操作员习惯。

如果业务侧提出新 UI 需求，建议创建新 Ralph track，并继承本轮门禁。

## 8. Ralph 转换

本 PRD 已转换为 Ralph JSON：

- `.omc/ralph/pcui-ui-business-prd/prd.json`

该 JSON 是业务验收型 Ralph PRD，记录当前已完成交付状态，因此 story 的 `passes` 为 `true`。
