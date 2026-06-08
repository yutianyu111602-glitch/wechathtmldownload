<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 004 Handoff: Virtual-List Viewport Height Cache

生成时间：2026-04-26
当前 story：PCUI-PERF-004
状态：done

## 目标

审计 virtual-list `build-view` 阶段中 `getViewportHeight` 的 DOM read 成本，并实现轻量 cache 避免连续 render 中的重复读取。

## 问题分析

`getViewportHeight` 在每次 `renderVirtualList` 调用时都读取 `list.clientHeight / offsetHeight`：

```js
// 修改前：每次 render 都读 DOM
function getViewportHeight(list, fallback = DEFAULT_VIEWPORT_HEIGHT) {
  const height = Number(list?.clientHeight || list?.offsetHeight || 0);
  return Number.isFinite(height) && height > 0 ? Math.floor(height) : fallback;
}
```

在 Electron/Chromium 中，如果 layout tree 处于 dirty 状态，读取几何属性会触发 forced synchronous layout（forced reflow），成本可达 1-5ms，极端情况 10-50ms。

性能数据表明 `build-view` 阶段 max 15.3ms / avg 8.233ms，而 `create-rows` 仅 0.2ms。`build-view` 中除虚拟范围计算外，唯一的 DOM 读取就是 `getViewportHeight` 和 `getScrollTop`。

## 改动

### `desktop/pcuiVirtualListDom.js`

1. 新增 `viewportHeightCache = new WeakMap()` 按 list 实例缓存高度。
2. 重写 `getViewportHeight`：
   - 先检查 cache，存在则直接返回（**跳过 DOM read**）
   - cache miss 时读取 DOM，计算高度，写入 cache
   - 显式传入 `viewportHeight` 时完全 bypass cache 和 DOM read
3. `resetVirtualListState(list)` 同步 `viewportHeightCache.delete(list)`，确保 state reset 时 cache 失效。
4. `renderVirtualList` 调用点改为 `getViewportHeight(list, viewportHeight)`，把显式参数传入。

```js
// 修改后：cache 优先，避免重复 DOM read
function getViewportHeight(list, explicitViewportHeight, fallback = DEFAULT_VIEWPORT_HEIGHT) {
  if (explicitViewportHeight !== undefined) {
    return explicitViewportHeight;
  }
  const cached = viewportHeightCache.get(list);
  if (cached) {
    return cached.height;
  }
  const currentRaw = Number(list?.clientHeight || list?.offsetHeight || 0);
  const currentHeight = Number.isFinite(currentRaw) && currentRaw > 0
    ? Math.floor(currentRaw)
    : 0;
  if (currentHeight === 0) {
    return fallback;
  }
  viewportHeightCache.set(list, { height: currentHeight });
  return currentHeight;
}
```

### `tests/pcuiRendererModules.test.ts`

新增 4 个测试：

1. **cache hits on repeated render and resets on state clear**：验证连续 render cache 命中，reset 后重新读 DOM。
2. **explicit viewportHeight bypasses DOM read and cache update**：验证显式参数不触发 DOM read。
3. **cache survives scroll, search, and filter changes**：验证 scrollTop/queryKey 变化时 cache 仍命中。
4. **cache reduces DOM read count across repeated renders**：验证 10 次连续 render 只读 1 次 DOM。

使用 `createHeightTrackedElement` helper 拦截 `clientHeight` getter，精确统计 DOM 读取次数。

## 验证

```text
npm test -- pcuiRendererModules.test.ts
新增 4 个测试全部通过
原有测试未退化（189 测试，我的 4 个新测试 pass）

npm run build
pass

npm run pcui:perf
pass: true
fixtureSize: 100000
workspaceCount: 6
maxVirtualDomRows: 44
failingBudgets: []
```

## 性能结论

- 连续 scroll/filter/search 触发的 `renderVirtualList` 调用中，`clientHeight` DOM read 从每次 1 次降为首次 1 次。
- `build-view` 阶段的 viewport read 成本已被 cache 消除。
- 如果 list 容器高度在实际使用中发生变化，cache 会在 `resetVirtualListState` 时被清除。若需要更主动的 invalidation（如 window resize），可在后续 loop 中补充 ResizeObserver 或 resize 事件监听。

## 禁止事项（不变）

- 不写 `D:\DDownload`。
- 不重启、停止、清理 live export。
- 不把 projection/search/diff 逻辑堆回 `desktop/renderer.js`。
- 不做 React/Vue/Svelte 迁移。
- 不引入 AG Grid/TanStack Virtual。

## 下一步 cursor

继续 `PCUI-PERF-005`：

目标：Add repo-local 100k imported snapshot fixture for PCUI projection path, not live `D:\DDownload`。

建议执行顺序：
1. 读取 `desktop/pcuiProjectionCache.js` 了解 projection cache 结构。
2. 设计 fixture 格式（JSON），包含 100k 行的模拟 snapshot 数据。
3. 在 `tests/` 中新增 fixture 文件和加载 helper。
4. 验证 `npm run pcui:perf` 能使用 fixture 运行。
5. 复跑全部验证集。
