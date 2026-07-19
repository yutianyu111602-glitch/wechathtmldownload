const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

// 2026-06-14：ATLAS 从太空贸易游戏重做为纯 DJ/俱乐部关系图谱探索。
// 2026-06-24：ATLAS tab 从 saved 移至 atlas-starmap。
test("ATLAS tab is the DJ/club relationship-graph explorer", () => {
  const appJson = JSON.parse(read("app.json"));
  const savedJs = read("pages/saved/saved.js");
  const savedWxml = read("pages/saved/saved.wxml");
  const savedWxss = read("pages/saved/saved.wxss");

  const atlasTab = appJson.tabBar.list.find((item) => item.pagePath === "pages/atlas-starmap/atlas-starmap");
  assert.ok(atlasTab, "atlas-starmap page is registered as a tab");

  // 接入后端关系图谱 API（serving DB 的 dj_relation_rollup / dj_venue_rollup）
  assert.match(savedJs, /\/api\/v1\/atlas\/family\/profile/);
  assert.match(savedJs, /\/api\/v1\/weekly\/atlas\/dj-profile\//);
  assert.match(savedJs, /legacyDjProfileToFamilyProfile\b/);
  assert.match(savedJs, /DEFAULT_ATLAS_ENTRY/);
  assert.match(savedJs, /loadFirstAvailableGraph\b/);
  assert.match(savedJs, /silentNotFound/);
  assert.match(savedJs, /loadSeeds\b/);
  assert.match(savedJs, /loadGraph\b/);
  assert.match(savedJs, /exploreNode\b/);
  assert.match(savedJs, /relatedDjs/);
  assert.match(savedJs, /onTabItemTap\(\)/);
  // 跨页约束：语言上下文 + 可跳活动详情
  assert.match(savedJs, /weeklyActivityLang/);
  assert.match(savedJs, /\/pages\/detail\/detail\?id=/);

  // 极坐标星图渲染（纯 WXML/WXSS，无 canvas / web-view）
  assert.match(savedWxml, /class="graph-stage/);
  assert.match(savedWxml, /class="graph-center/);
  assert.match(savedWxml, /bindtap="exploreNode"/);
  assert.match(savedWxml, /bindtap="selectSeed"/);
  assert.doesNotMatch(savedWxml, /<canvas/);
  assert.doesNotMatch(savedWxml, /<web-view/);
  assert.match(savedWxss, /\.graph-stage/);
  assert.match(savedWxss, /\.graph-node/);

  // 太空贸易机制必须已彻底移除
  assert.doesNotMatch(savedJs, /buildAtlasUniverse|scanField|wormhole|ledger|\bcontract\b/);
  assert.doesNotMatch(savedWxml, /contract-panel|wormhole-gate|ledger-panel|ship-systems/);

  // 星系渲染：关系强度归一化出 weight，决定星的大小/亮度（强度分层）
  assert.match(savedJs, /buildNeighbors\b/);
  assert.match(savedJs, /weight/);
  assert.match(savedWxml, /class="starfield"/);
  assert.match(savedWxml, /style="width:\{\{item\.dotSize\}\}rpx/);
  assert.match(savedWxss, /\.starfield/);
  assert.match(savedWxss, /tier-strong/);

  // 玩法：点过的星会被「点亮」收藏 + 顶部探索轨迹可回跳
  assert.match(savedJs, /markVisited\b/);
  assert.match(savedJs, /jumpTo\b/);
  assert.match(savedWxml, /bindtap="jumpTo"/);
  assert.match(savedWxml, /visitedCount/);

  // 手感：漫游下一颗星时不清空旧图（整屏 loading/error 仅冷启动 !center 时出现），改用变暗 + toast
  assert.match(savedWxml, /loading && !center/);
  assert.match(savedWxml, /error && !center/);
  assert.match(savedWxml, /graph-loading/);
  assert.match(savedWxss, /\.graph-loading/);
  assert.match(savedJs, /wx\.showToast/);
  // 健壮性：找到但无邻居星的「死胡同」给引导，不是空白
  assert.match(savedJs, /deadEnd/);
  assert.match(savedWxml, /class="dead-end-hint"/);
  // 单次 setData：移除冗余的二次刷新方法
  assert.doesNotMatch(savedJs, /refreshVisitedFlags/);

  // Phase 1 图谱深度：补主办/厂牌节点 + 按 id 下钻 + 稠密种子 + 关系标签 + 随机跳，治「0 节点」
  assert.match(savedJs, /sectionItems\(profile, "organizations"\)/); // 不再丢弃 org 维度
  assert.match(savedWxss, /\.node-org/);
  assert.match(savedWxss, /\.center-org/);
  assert.match(savedJs, /fetchAtlasProfile\(name, id\)/); // 按稳定 id 下钻
  assert.match(savedWxml, /data-id="\{\{item\.id\}\}"/);
  assert.match(savedJs, /MIN_SEED_NEIGHBORS/); // 优选稠密入口
  assert.match(savedJs, /relationMeta\b/); // 关系类型标签
  assert.match(savedJs, /exploreRandom\b/); // 随机跳一颗强邻居
  assert.match(savedWxml, /bindtap="exploreRandom"/);
});
