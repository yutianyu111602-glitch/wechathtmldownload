// pages/atlas-starmap/atlas-starmap.js
// Native mp star map (图鉴, not a game): a 2D relationship graph on <canvas type="2d">.
// Cooler + explorable: glowing nodes, deep-space backdrop, edges colored by relation type,
// smooth fly-to animation, type-legend filtering, random hop. Loads the bundled overview
// (data/atlas_starmap.js, from reconciled atlas v2). ES5-conservative for the WeChat sandbox.
var requestApi = require("../../utils/api").requestApi;
var cityFootprint = require("../../utils/cityFootprint.js").cityFootprint;
var bundle = require("../../data/atlas_starmap.js");
var neighborBundle = null;
var atlasLoading = require("../../utils/atlasLoading.js");

var VISITED_KEY = "atlasVisitedStars:v1";

// City geographic anchors for constellation halos (matches Python CITY_COORDS)
var CITY_HALOS = [
  { name: "上海", x: 0.68, y: -0.08, col: "#7fd4ff", r: 0.18 },
  { name: "北京", x: 0.28, y: 0.62,  col: "#a78bfa", r: 0.18 },
  { name: "成都", x: -0.50, y: -0.02, col: "#4ade80", r: 0.16 },
  { name: "深圳", x: 0.50, y: -0.68, col: "#fb923c", r: 0.14 },
  { name: "广州", x: 0.38, y: -0.72, col: "#f472b6", r: 0.12 },
  { name: "杭州", x: 0.70, y: -0.22, col: "#22d3ee", r: 0.11 },
  { name: "重庆", x: -0.18, y: -0.22, col: "#facc15", r: 0.12 },
  { name: "武汉", x: 0.18, y: 0.08,  col: "#ef4444", r: 0.10 },
  { name: "昆明", x: -0.40, y: -0.58, col: "#c084fc", r: 0.10 },
  { name: "大理", x: -0.55, y: -0.54, col: "#e879f9", r: 0.09 },
];

var TYPE_LABEL = { dj: "DJ", venue: "场地", org: "厂牌", organizer: "厂牌", series: "系列" };
var TYPE_COLOR = { dj: "#7fd4ff", venue: "#ffcf6b", org: "#b794f6", organizer: "#b794f6", series: "#2dd4bf" };
var TYPE_VISUAL = {
  dj: { shape: "circle", color: "#7FD4FF" },
  venue: { shape: "hexagon", color: "#FFCF6B" },
  org: { shape: "diamond", color: "#B794F6" },
  series: { shape: "ring", color: "#2DD4BF" },
};
var EVENT_P99 = 115;
var RELATION_P90 = 36;
var RELATION_P99 = 284;
var EDGE_WEIGHT_P99 = 585;
var RELATION_VISUAL = {
  b2b: { color: "255,207,107", dash: [] },
  collab: { color: "127,212,255", dash: [] },
  resident_at: { color: "45,212,191", dash: [] },
  held_at: { color: "45,212,191", dash: [] },
  signed_to: { color: "183,148,246", dash: [3, 2] },
  presented_by: { color: "183,148,246", dash: [3, 2] },
};
var CITY_COLORS = {
  "上海": "#7fd4ff", "北京": "#a78bfa", "成都": "#4ade80",
  "深圳": "#fb923c", "广州": "#f472b6", "杭州": "#22d3ee",
  "重庆": "#facc15", "武汉": "#ef4444", "昆明": "#c084fc", "大理": "#e879f9",
};
function _djColor(t, city) {
  return t === "dj" ? (CITY_COLORS[city] || TYPE_COLOR.dj) : (TYPE_COLOR[t] || "#7fd4ff");
}
var REL_LABEL = {
  b2b: "B2B",
  collab: "同场",
  resident_at: "驻场",
  signed_to: "厂牌",
  held_at: "举办",
  presented_by: "主办",
};
var EDGE_COLOR = {
  b2b: "rgba(248,197,106,A)",        // amber — deep b2b
  collab: "rgba(125,185,225,A)",     // blue — co-bill
  resident_at: "rgba(45,212,191,A)", // teal — residency
  signed_to: "rgba(183,148,246,A)",  // violet — label
  held_at: "rgba(45,212,191,A)",
  presented_by: "rgba(183,148,246,A)",
};
var REL_PRIORITY = {
  b2b: 6,
  resident_at: 5,
  held_at: 4,
  signed_to: 3,
  presented_by: 3,
  collab: 2,
};
function edgeColor(t, a) { return (EDGE_COLOR[t] || "rgba(125,185,225,A)").replace("A", a); }
function relationLabel(t) { return REL_LABEL[t] || "关系"; }
function normalizeType(t) {
  var k = String(t || "").toLowerCase();
  return k === "organizer" ? "org" : k;
}
function relationPriority(t) { return REL_PRIORITY[String(t || "").toLowerCase()] || 1; }
function getNeighborBundle() {
  if (!neighborBundle) {
    neighborBundle = require("../../data/atlas_starmap_neighbors.js");
  }
  return neighborBundle || {};
}
function relatedScore(row) {
  var rs = Number(row && row.rs) || 0;
  var w = Number(row && row.w) || 0;
  return rs * 1000000 + Math.log(w + 1) * 10000 + relationPriority(row && row.rt) * 100 + Math.min(w, 9999);
}
function scoreHint(row) {
  var rs = Number(row && row.rs) || 0;
  var w = Number(row && row.w) || 0;
  if (rs >= 6.2 || w >= 1500) return "强关联";
  if (rs >= 5.2 || w >= 500) return "高频";
  if (rs > 0 || w > 0) return "相关";
  return "";
}
function compactText(v) { return String(v || "").trim(); }
function countMeta(count, unit) {
  var n = Number(count) || 0;
  return n > 0 ? (n + unit) : "";
}
function joinMeta(parts) {
  var out = [];
  for (var i = 0; i < parts.length; i++) {
    var p = compactText(parts[i]);
    if (p) out.push(p);
  }
  return out.join(" · ");
}
function rowNames(rows, key, limit) {
  var out = [];
  rows = rows || [];
  for (var i = 0; i < rows.length && out.length < limit; i++) {
    var name = compactText(rows[i] && rows[i][key]);
    if (name) out.push(name);
  }
  return out.join(" / ");
}
// Render a footprint (from utils/cityFootprint) as a compact "city N · city N" line.
function cityFootprintLine(fp, limit) {
  var out = [];
  for (var k = 0; k < fp.order.length && out.length < limit; k++) {
    out.push(fp.order[k] + " " + fp.counts[fp.order[k]]);
  }
  return out.join(" · ");
}

Page({
  data: {
    loading: true,
    loadingMsg: atlasLoading.LOADING_MSGS[0],
    ldDots: atlasLoading.buildLdDots(),
    canvasError: false,
    lens: "entity",
    query: "",
    selected: null,
    relatedFilter: "all",
    explorationTrail: [],
    pathMode: false,
    pathHint: "",
    pathResult: null,
    nodeCount: 0,
    serverLens: false,
    seedList: [],
    visitedCount: 0,
    legend: [
      { k: "dj", label: "DJ", col: "#7fd4ff", on: true },
      { k: "venue", label: "场地", col: "#ffcf6b", on: true },
      { k: "org", label: "厂牌", col: "#b794f6", on: true },
      { k: "series", label: "系列", col: "#2dd4bf", on: true },
    ],
    cityLegend: [
      { city: "上海", col: "#7fd4ff" }, { city: "北京", col: "#a78bfa" },
      { city: "成都", col: "#4ade80" }, { city: "深圳", col: "#fb923c" },
      { city: "广州", col: "#f472b6" }, { city: "杭州", col: "#22d3ee" },
      { city: "重庆", col: "#facc15" }, { city: "武汉", col: "#ef4444" },
      { city: "昆明", col: "#c084fc" }, { city: "大理", col: "#e879f9" },
    ],
  },

  _metricScore: function (value, p99) {
    var n = Math.max(0, Number(value) || 0);
    var cap = Math.max(1, Number(p99) || 1);
    return Math.max(0, Math.min(1, Math.log(1 + n) / Math.log(1 + cap)));
  },

  _nodeVisual: function (node) {
    node = node || {};
    var t = normalizeType(node.t || "dj");
    var typeVisual = TYPE_VISUAL[t] || TYPE_VISUAL.dj;
    var hasEvents = Object.prototype.hasOwnProperty.call(node, "ec") && node.ec !== null;
    var eventScore = hasEvents
      ? this._metricScore(node.ec, EVENT_P99)
      : Math.max(0, Math.min(1, ((Number(node.s) || 0.5) - 0.5) / 2.5));
    var relationCount = Math.max(0, Number(node.rc) || 0);
    var sourceCount = Math.max(0, Number(node.sc) || 0);
    var relationScore = this._metricScore(relationCount, RELATION_P99);
    var evidenceTicks = sourceCount >= 101 ? 8 : (sourceCount >= 8 ? 4 : (sourceCount >= 1 ? 2 : 0));
    return {
      shape: typeVisual.shape,
      color: typeVisual.color,
      eventScore: eventScore,
      relationScore: relationScore,
      radius: Math.round((3.5 + 5.5 * eventScore) * 1000) / 1000,
      haloGap: Math.round((3 + 4 * relationScore) * 1000) / 1000,
      haloRings: relationCount >= RELATION_P99 ? 3 : (relationCount >= RELATION_P90 ? 2 : 1),
      evidenceTicks: evidenceTicks,
    };
  },

  _edgeVisual: function (edge, highlighted) {
    edge = edge || [];
    var relationType = String(edge[2] || "collab").toLowerCase();
    var relationVisual = RELATION_VISUAL[relationType] || { color: "143,166,184", dash: [] };
    var weightScore = this._metricScore(Number(edge[3]) || 1, EDGE_WEIGHT_P99);
    var width = 0.35 + 1.65 * weightScore + (highlighted ? 0.45 : 0);
    var alpha = highlighted ? (relationType === "b2b" ? "0.76" : "0.68") : "0.07";
    return {
      color: "rgba(" + relationVisual.color + "," + alpha + ")",
      dash: relationVisual.dash.slice(),
      lineWidth: Math.round(width * 1000) / 1000,
    };
  },

  _labelRank: function (node) {
    var visual = this._nodeVisual(node);
    return 0.55 * visual.eventScore + 0.45 * visual.relationScore;
  },

  _zoomTierForScale: function (scale) {
    var value = Number(scale) || 1;
    return value < 1.2 ? "overview" : (value < 2.2 ? "neighborhood" : "detail");
  },

  _indexDuplicateNames: function () {
    var typesByName = {};
    var duplicates = {};
    for (var i = 0; i < this._nodes.length; i++) {
      var node = this._nodes[i] || {};
      var name = String(node.n || "").trim().toLowerCase();
      var type = normalizeType(node.t || "dj");
      if (!name) continue;
      var types = typesByName[name] || (typesByName[name] = {});
      types[type] = true;
      if (Object.keys(types).length > 1) duplicates[name] = true;
    }
    this._duplicateNames = duplicates;
  },

  _nodeLabel: function (node) {
    node = node || {};
    var name = String(node.n || node.u || "");
    var key = name.trim().toLowerCase();
    var type = normalizeType(node.t || "dj");
    return this._duplicateNames && this._duplicateNames[key]
      ? (name + " · " + (TYPE_LABEL[type] || type))
      : name;
  },

  onLoad: function (query) {
    this._initialQuery = query && query.q ? decodeURIComponent(query.q) : "";
    this._initialFocusId = query && query.focusId ? decodeURIComponent(query.focusId) : "";
    this._nodes = ((bundle && bundle.nodes) || []).map(function (n) {
      var copy = {};
      for (var k in n) copy[k] = n[k];
      copy._base = true;
      return copy;
    });
    this._edges = ((bundle && bundle.edges) || []).map(function (edge) {
      return [edge[0], edge[1], edge[2], Number(edge[3]) || 1];
    });
    this._baseNodeCount = this._nodes.length;
    this._expanded = {};
    this._expansionChildren = {};
    this._hiddenDynamic = {};
    this._remoteRows = {};
    this._remoteLoading = {};
    this._remoteError = {};
    this._inspectorCache = {};
    this._inspectorLoading = {};
    this._inspectorSeq = 0;
    this._trail = [];
    this._nodeIndexById = {};
    this._edgeKeySet = {};
    for (var i = 0; i < this._nodes.length; i++) {
      this._nodes[i].i = i;
      if (this._nodes[i].u) this._nodeIndexById[this._nodes[i].u] = i;
    }
    this._indexDuplicateNames();
    this._rebuildAdj();
    this._scale = 1; this._ox = 0; this._oy = 0;
    this._sel = -1; this._highlight = null; this._touch = null;
    this._hidden = {};            // type -> true when filtered out
    this._visited = {};
    this._anim = null;
    this.setData({ nodeCount: this._visibleCount(), query: this._initialQuery || "" });
    this._startLoadingCycle();
  },

  onReady: function () {
    this._initCanvas(0);
  },

  onShow: function () {
    this._loadVisited();
    this._loadSeeds();
  },

  _loadVisited: function () {
    try {
      var raw = wx.getStorageSync(VISITED_KEY);
      this._visited = raw ? JSON.parse(raw) : {};
    } catch (e) { this._visited = {}; }
    this.setData({ visitedCount: Object.keys(this._visited).length });
  },

  _markVisited: function (name) {
    if (!this._visited) this._visited = {};
    if (!name || this._visited[name]) return;
    this._visited[name] = 1;
    try { wx.setStorageSync(VISITED_KEY, JSON.stringify(this._visited)); } catch (e) {}
    this.setData({ visitedCount: Object.keys(this._visited).length });
    // refresh visited state on seed chips
    var seeds = this.data.seedList;
    if (!seeds || !seeds.length) return;
    var updated = false;
    var next = seeds.map(function (s) {
      if (s.name === name && !s.visited) { updated = true; return { name: s.name, visited: true }; }
      return s;
    });
    if (updated) this.setData({ seedList: next });
  },

  _loadSeeds: function () {
    var that = this;
    requestApi("/api/v1/weekly/current", { limit: 60 }).then(function (r) {
      var seen = {};
      var list = [];
      var visited = that._visited || {};
      (r && r.items || []).forEach(function (item) {
        var candidates = [].concat(item.atlasArtistItems || item.atlas_artists || [])
                           .concat(item.lineupItems || item.lineup_artists || []);
        candidates.forEach(function (c) {
          var name = String((c && (c.displayName || c.name)) || "").trim();
          if (name && !seen[name] && list.length < 20) {
            seen[name] = 1;
            list.push({ name: name, visited: !!visited[name] });
          }
        });
      });
      if (list.length) that.setData({ seedList: list });
    }).catch(function () {});
  },

  onSeedTap: function (e) {
    var name = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.name;
    if (!name) return;
    var hit = this._findNode("", name);
    if (hit >= 0) {
      this.selectNode(hit, { trailMode: "replace" });
    } else {
      wx.showToast({ title: name + " 暂不在星图", icon: "none" });
    }
  },

  openFootprint: function () {
    wx.navigateTo({ url: "/pages/saved/saved" });
  },

  _initCanvas: function (attempt) {
    if (this._canvas) return;
    var that = this;
    wx.createSelectorQuery().select("#sm")
      .fields({ node: true, size: true }).exec(function (res) {
        if (!res || !res[0] || !res[0].node || !res[0].width || !res[0].height) {
          if ((attempt || 0) < 24) {
            setTimeout(function () { that._initCanvas((attempt || 0) + 1); }, 250);
          } else {
            that._stopLoadingCycle();
            that.setData({ loading: false, canvasError: true });
          }
          return;
        }
        var canvas = res[0].node, w = res[0].width, h = res[0].height;
        var dpr = (wx.getSystemInfoSync && wx.getSystemInfoSync().pixelRatio) || 2;
        canvas.width = w * dpr; canvas.height = h * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        that._canvas = canvas; that._ctx = ctx; that._cw = w; that._ch = h;
        that._base = Math.min(w, h) * 0.42;
        that._ox = w / 2; that._oy = h / 2; that._scale = 1;
        // deep-space backdrop (fixed screen-space faint stars)
        that._stars = [];
        for (var i = 0; i < 90; i++) {
          that._stars.push({ x: Math.random() * w, y: Math.random() * h,
            r: 0.4 + Math.random() * 1.1, a: 0.15 + Math.random() * 0.5, ph: Math.random() * 6.2832 });
        }
        that._stopLoadingCycle();
        that.setData({ loading: false });
        that.draw();
        that._focusInitial();
      });
  },

  _sx: function (x) { return this._ox + x * this._base * this._scale; },
  _sy: function (y) { return this._oy + y * this._base * this._scale; },
  _vis: function (n) { return !this._hidden[n.t] && !this._hiddenDynamic[n.u]; },

  _visibleCount: function () {
    var c = 0;
    for (var i = 0; i < this._nodes.length; i++) if (this._vis(this._nodes[i])) c++;
    return c;
  },

  _edgeKey: function (a, b, t) {
    var x = Math.min(a, b), y = Math.max(a, b);
    return x + "|" + y + "|" + (t || "rel");
  },

  _rebuildAdj: function () {
    this._adj = {};
    this._edgeKeySet = {};
    for (var e = 0; e < this._edges.length; e++) {
      var a = this._edges[e][0], b = this._edges[e][1], t = this._edges[e][2];
      (this._adj[a] || (this._adj[a] = [])).push(b);
      (this._adj[b] || (this._adj[b] = [])).push(a);
      this._edgeKeySet[this._edgeKey(a, b, t)] = true;
    }
  },

  _clampCoord: function (v) {
    return Math.max(-1.08, Math.min(1.08, v));
  },

  _neighborSize: function (row) {
    var rs = Number(row && row.rs) || 1;
    return Math.max(0.58, Math.min(1.28, 0.46 + rs / 7));
  },

  _neighborRows: function (nodeId) {
    var id = String(nodeId || "");
    var localRows = (((getNeighborBundle() || {}).byNode || {})[id] || []);
    if (localRows.length) return localRows;
    return this._remoteRows[id] || [];
  },

  _neighborhoodStatus: function (nodeId) {
    var id = String(nodeId || "");
    var localRows = (((getNeighborBundle() || {}).byNode || {})[id] || []);
    if (localRows.length) return "概览邻域 " + localRows.length + " 条";
    if (this._remoteLoading[id]) return "全库邻域加载中";
    if (this._remoteError[id]) return "全库邻域暂不可用";
    if (Object.prototype.hasOwnProperty.call(this._remoteRows, id)) {
      var remoteRows = this._remoteRows[id] || [];
      return remoteRows.length ? ("全库邻域 " + remoteRows.length + " 条") : "全库暂无邻域";
    }
    return "点星点加载全库邻域";
  },

  _dynamicVisible: function (nodeId) {
    for (var parentId in this._expanded) {
      if (!this._expanded[parentId]) continue;
      var children = this._expansionChildren[parentId] || [];
      for (var i = 0; i < children.length; i++) {
        if (children[i] === nodeId) return true;
      }
    }
    return false;
  },

  _refreshDynamicVisibility: function () {
    for (var i = this._baseNodeCount; i < this._nodes.length; i++) {
      var id = this._nodes[i].u;
      this._hiddenDynamic[id] = !this._dynamicVisible(id);
    }
    this.setData({ nodeCount: this._visibleCount() });
  },

  _ensureNeighborNode: function (row, center, slot, total) {
    if (!row || !row.u) return -1;
    var existing = this._nodeIndexById[row.u];
    if (existing !== undefined) {
      this._hiddenDynamic[row.u] = false;
      return existing;
    }
    var t = String(row.t || "dj").toLowerCase();
    var angle = (slot / Math.max(total, 1)) * 6.2832 + ((center.i || 0) % 7) * 0.19;
    var ring = 0.16 + (slot % 3) * 0.035 + Math.min(0.11, (Number(row.w) || 0) / 26000);
    var node = {
      i: this._nodes.length,
      u: String(row.u || ""),
      n: String(row.n || row.u || ""),
      t: t,
      c: String(row.c || ""),
      x: this._clampCoord((Number(center.x) || 0) + Math.cos(angle) * ring),
      y: this._clampCoord((Number(center.y) || 0) + Math.sin(angle) * ring),
      s: this._neighborSize(row),
      col: _djColor(t, String(row.c || "")),
      _dynamic: true,
    };
    this._nodes.push(node);
    this._nodeIndexById[node.u] = node.i;
    this._hiddenDynamic[node.u] = false;
    return node.i;
  },

  _appendEdge: function (a, b, t, weight) {
    if (a < 0 || b < 0 || a === b) return false;
    var rt = String(t || "collab");
    var key = this._edgeKey(a, b, rt);
    if (this._edgeKeySet[key]) return false;
    this._edges.push([a, b, rt, Number(weight) || 1]);
    this._edgeKeySet[key] = true;
    return true;
  },

  _relationTypeBetween: function (a, b) {
    for (var e = 0; e < this._edges.length; e++) {
      var x = this._edges[e][0], y = this._edges[e][1];
      if ((x === a && y === b) || (x === b && y === a)) return this._edges[e][2] || "collab";
    }
    return "collab";
  },

  _relatedScore: function (row) {
    return relatedScore(row);
  },

  _rankedRows: function (rows) {
    var ranked = (rows || []).slice();
    var that = this;
    ranked.sort(function (a, b) {
      var d = that._relatedScore(b) - that._relatedScore(a);
      if (d !== 0) return d > 0 ? 1 : -1;
      var an = String(a && (a.n || a.u) || "");
      var bn = String(b && (b.n || b.u) || "");
      return an < bn ? -1 : (an > bn ? 1 : 0);
    });
    return ranked;
  },

  _previewFromRow: function (row) {
    var t = normalizeType(row && row.t || "dj");
    var city = compactText(row && row.c);
    var rel = relationLabel(String(row && row.rt || "collab"));
    var hint = scoreHint(row);
    return {
      id: String(row && row.u || ""),
      name: compactText(row && (row.n || row.u)),
      filterKey: t,
      type: TYPE_LABEL[t] || t,
      city: city,
      relation: rel,
      scoreHint: hint,
      color: _djColor(t, city),
      meta: joinMeta([TYPE_LABEL[t] || t, city, rel, hint]),
    };
  },

  _relatedItems: function (i, rows) {
    var out = [], seen = {};
    rows = this._rankedRows(rows || []);
    for (var r = 0; r < rows.length; r++) {
      var row = this._previewFromRow(rows[r]);
      if (!row.id || seen[row.id]) continue;
      seen[row.id] = true;
      out.push(row);
    }
    if (out.length) return out;
    var nb = this._adj[i] || [];
    for (var k = 0; k < nb.length && out.length < 6; k++) {
      var n = this._nodes[nb[k]];
      if (!n || !this._vis(n) || seen[n.u]) continue;
      var rt = this._relationTypeBetween(i, nb[k]);
      var t = normalizeType(n.t || "dj");
      seen[n.u] = true;
      out.push({
        id: n.u || "",
        name: n.n || n.u || "",
        filterKey: t,
        type: TYPE_LABEL[t] || t,
        city: n.c || "",
        relation: relationLabel(rt),
        color: _djColor(t, n.c || ""),
        meta: joinMeta([TYPE_LABEL[t] || t, n.c || "", relationLabel(rt)]),
      });
    }
    return out;
  },

  _relatedFilters: function (items, active) {
    var counts = { all: items.length };
    var order = ["dj", "venue", "org", "series"];
    for (var i = 0; i < items.length; i++) {
      var k = normalizeType(items[i] && items[i].filterKey);
      if (!k) continue;
      counts[k] = (counts[k] || 0) + 1;
    }
    var out = [{ k: "all", label: "全部", count: counts.all || 0, on: active === "all" }];
    for (var j = 0; j < order.length; j++) {
      var key = order[j];
      if (!counts[key]) continue;
      out.push({ k: key, label: TYPE_LABEL[key] || key, count: counts[key], on: active === key });
    }
    return out;
  },

  _activeRelatedFilter: function (items, requested) {
    var k = normalizeType(requested || "all");
    if (k === "all") return "all";
    for (var i = 0; i < items.length; i++) {
      if (normalizeType(items[i] && items[i].filterKey) === k) return k;
    }
    return "all";
  },

  _relatedPreview: function (i, rows, filter) {
    var items = this._relatedItems(i, rows);
    var active = this._activeRelatedFilter(items, filter || "all");
    var out = [];
    for (var k = 0; k < items.length && out.length < 6; k++) {
      if (active !== "all" && normalizeType(items[k].filterKey) !== active) continue;
      out.push(items[k]);
    }
    return out;
  },

  _trailItem: function (i) {
    var n = this._nodes[i]; if (!n) return null;
    var t = String(n.t || "dj").toLowerCase();
    return {
      id: n.u || "",
      name: n.n || n.u || "",
      type: TYPE_LABEL[t] || t,
      color: _djColor(t, n.c || ""),
    };
  },

  _syncTrail: function (i, mode) {
    var item = this._trailItem(i);
    if (!item || !item.id) {
      this._trail = [];
    } else if (mode === "preserve") {
      if (!this._trail.length) this._trail = [item];
    } else if (mode === "append") {
      var cut = -1;
      for (var t = 0; t < this._trail.length; t++) {
        if (this._trail[t].id === item.id) cut = t;
      }
      if (cut >= 0) this._trail = this._trail.slice(0, cut + 1);
      else this._trail = this._trail.concat([item]).slice(-6);
    } else {
      this._trail = [item];
    }
    this.setData({ explorationTrail: this._trail.slice() });
  },

  _expandRows: function (i, rows) {
    var n = this._nodes[i]; if (!n || !n.u) return false;
    rows = this._rankedRows(rows || []).slice(0, 18);
    if (!rows.length) return false;
    if (!this._expansionChildren[n.u]) {
      var children = [];
      for (var r = 0; r < rows.length; r++) {
        var ni = this._ensureNeighborNode(rows[r], n, r, rows.length);
        if (ni < 0) continue;
        children.push(this._nodes[ni].u);
        this._appendEdge(i, ni, rows[r].rt || "collab", rows[r].w);
      }
      this._expansionChildren[n.u] = children;
      this._rebuildAdj();
    }
    this._expanded[n.u] = true;
    this._refreshDynamicVisibility();
    return true;
  },

  _expandNode: function (i) {
    var n = this._nodes[i]; if (!n || !n.u) return false;
    var rows = this._neighborRows(n.u);
    if (!rows.length) {
      this._expandNodeRemote(i);
      return false;
    }
    return this._expandRows(i, rows);
  },

  _remoteNeighborRow: function (row) {
    return {
      u: String(row && row.id || ""),
      n: String(row && row.name || row && row.id || ""),
      t: String(row && row.type || "dj").toLowerCase(),
      c: String(row && row.city || ""),
      rt: String(row && row.relationType || "collab"),
      w: Number(row && row.weight) || 0,
      rs: Number(row && row.rankScore) || 1,
    };
  },

  _expandNodeRemote: function (i) {
    var n = this._nodes[i]; if (!n || !n.u) return;
    var id = n.u;
    if (this._remoteLoading[id] || Object.prototype.hasOwnProperty.call(this._remoteRows, id)) return;
    var that = this;
    this._remoteLoading[id] = true;
    this._remoteError[id] = false;
    requestApi("/api/v1/weekly/atlas/neighborhood", { subjectId: id, limit: 18 })
      .then(function (payload) {
        var rows = ((payload && payload.neighbors) || []).map(function (row) {
          return that._remoteNeighborRow(row);
        }).filter(function (row) { return row.u; });
        that._remoteRows[id] = rows;
        that._remoteLoading[id] = false;
        if (rows.length) that._expandRows(i, rows);
        if (that._sel === i) that._updateSelected(i);
        that.draw();
      })
      .catch(function (error) {
        console.warn("[atlas-starmap] neighborhood fetch failed", error);
        that._remoteRows[id] = [];
        that._remoteLoading[id] = false;
        that._remoteError[id] = true;
        if (that._sel === i) that._updateSelected(i);
        that.draw();
      });
  },

  _collapseNode: function (i) {
    var n = this._nodes[i]; if (!n || !n.u || !this._expanded[n.u]) return false;
    this._expanded[n.u] = false;
    this._refreshDynamicVisibility();
    return true;
  },

  _updateSelected: function (i) {
    var n = this._nodes[i]; if (!n) return;
    var hl = {}; hl[i] = true;
    var nbRaw = this._adj[i] || [], nb = [], brk = {};
    for (var k = 0; k < nbRaw.length; k++) {
      var next = this._nodes[nbRaw[k]];
      if (!next || !this._vis(next)) continue;
      nb.push(nbRaw[k]);
      hl[nbRaw[k]] = true;
      brk[next.t] = (brk[next.t] || 0) + 1;
    }
    this._highlight = hl;
    var parts = [];
    for (var ty in brk) parts.push(brk[ty] + " " + (TYPE_LABEL[ty] || ty));
    var rows = this._neighborRows(n.u);
    var relatedItems = this._relatedItems(i, rows);
    var activeFilter = this._activeRelatedFilter(relatedItems, arguments.length > 1 ? arguments[1] : this.data.relatedFilter);
    var hasRemote = Object.prototype.hasOwnProperty.call(this._remoteRows, n.u);
    var hint = this._remoteLoading[n.u]
      ? "正在加载全库邻域…"
      : this._remoteError[n.u]
        ? "全库邻域暂时不可用"
        : rows.length
      ? (this._expanded[n.u] ? ("已展开 " + Math.min(rows.length, 18) + " 个邻居 · 再次点击收起") : "点击星点展开邻居")
      : (hasRemote ? "暂无邻域数据" : "点击星点加载全库邻域");
    var inspector = null;
    if (n.t === "dj" && n.u) {
      inspector = this._inspectorCache[n.u] || (this._inspectorLoading[n.u] ? { status: "loading", summary: "读取 ATLAS 速览…" } : null);
    }
    this.setData({
      selected: { id: n.u || "", name: n.n, type: TYPE_LABEL[n.t] || n.t, city: n.c || "未知",
        degree: nb.length, breakdown: parts.join(" · "), isDj: n.t === "dj",
        neighborhoodStatus: this._neighborhoodStatus(n.u),
        expandHint: hint, relatedFilter: activeFilter, relatedFilters: this._relatedFilters(relatedItems, activeFilter),
        relatedPreview: this._relatedPreview(i, rows, activeFilter), inspector: inspector },
      relatedFilter: activeFilter,
    });
  },

  _artistInspector: function (payload) {
    var profile = (payload && payload.profile) || {};
    var rt = profile.relationTrajectory || (payload && payload.relationTrajectory) || {};
    var cities = (rt.cities || []).slice(0, 4);
    var venues = (rt.venues || []).slice(0, 4);
    var collaborators = (rt.collaborators || []).slice(0, 4);
    var events = (rt.events || []).slice(0, 2);
    var cityLine = rowNames(cities, "city", 4);
    var venueLine = rowNames(venues, "venueName", 4);
    var collaboratorLine = rowNames(collaborators, "displayName", 4);
    var eventLine = rowNames(events, "title", 1);
    var hasData = !!(cityLine || venueLine || collaboratorLine || eventLine);
    if (hasData) {
      return {
        status: "ready",
        summary: joinMeta([
          countMeta((rt.counts || {}).cities || cities.length, "城"),
          countMeta((rt.counts || {}).venues || venues.length, "场地"),
          countMeta((rt.counts || {}).collaborators || collaborators.length, "相关DJ"),
        ]),
        cityLine: cityLine,
        venueLine: venueLine,
        collaboratorLine: collaboratorLine,
        eventLine: eventLine,
      };
    }
    // Long-tail fallback: only ~220 DJs have a curated trajectory lens. Build the
    // ATLAS 速览 for everyone else from the payload's own events/venues/collaborators
    // (already fetched) so star-map exploration is meaningful beyond the top tier.
    return this._inspectorFromPayload(payload);
  },

  _inspectorFromPayload: function (payload) {
    var pe = (payload && payload.events) || [];
    var pv = (payload && payload.venues) || [];
    var pc = (payload && payload.collaborators) || [];
    var fp = cityFootprint(pe);
    var cityLine = cityFootprintLine(fp, 4);
    var venueLine = rowNames(pv, "venueName", 4);
    var collaboratorLine = rowNames(pc, "displayName", 3);
    var eventLine = rowNames(pe, "title", 1);
    var hasData = !!(cityLine || venueLine || collaboratorLine || eventLine);
    if (!hasData) return { status: "empty", summary: "暂无轨迹摘要" };
    return {
      status: "ready",
      summary: joinMeta([
        countMeta(fp.order.length, "城"),
        countMeta(pv.length, "场地"),
        countMeta(pc.length, "相关DJ"),
      ]),
      cityLine: cityLine,
      venueLine: venueLine,
      collaboratorLine: collaboratorLine,
      eventLine: eventLine,
    };
  },

  _setSelectedInspector: function (id, inspector) {
    var sel = this.data.selected;
    if (!sel || sel.id !== id) return;
    var next = {};
    for (var k in sel) next[k] = sel[k];
    next.inspector = inspector;
    this.setData({ selected: next });
  },

  _loadSelectedInspector: function (n) {
    if (!n || n.t !== "dj" || !n.u) return;
    var id = n.u;
    if (this._inspectorCache[id]) {
      this._setSelectedInspector(id, this._inspectorCache[id]);
      return;
    }
    if (this._inspectorLoading[id]) return;
    var that = this;
    var seq = ++this._inspectorSeq;
    this._inspectorLoading[id] = true;
    this._setSelectedInspector(id, { status: "loading", summary: "读取 ATLAS 速览…" });
    requestApi("/api/v1/weekly/atlas/artist", {
      subjectId: id, eventLimit: 40, collaboratorLimit: 20, venueLimit: 12,
      cacheBust: "starmap-inspector-20260624b",
    }).then(function (payload) {
      var inspector = payload && payload.found
        ? that._artistInspector(payload)
        : { status: "empty", summary: "暂无轨迹摘要" };
      that._inspectorCache[id] = inspector;
      that._inspectorLoading[id] = false;
      if (seq === that._inspectorSeq) that._setSelectedInspector(id, inspector);
    }).catch(function (error) {
      console.warn("[atlas-starmap] artist inspector fetch failed", error);
      var inspector = { status: "error", summary: "ATLAS 速览暂不可用" };
      that._inspectorCache[id] = inspector;
      that._inspectorLoading[id] = false;
      if (seq === that._inspectorSeq) that._setSelectedInspector(id, inspector);
    });
  },

  _drawNodeShape: function (ctx, shape, x, y, radius) {
    ctx.beginPath();
    if (shape === "hexagon") {
      for (var h = 0; h < 6; h++) {
        var angle = -1.5708 + h * 1.0472;
        var hx = x + Math.cos(angle) * radius;
        var hy = y + Math.sin(angle) * radius;
        if (h === 0) ctx.moveTo(hx, hy); else ctx.lineTo(hx, hy);
      }
      ctx.closePath();
      return;
    }
    if (shape === "diamond") {
      ctx.moveTo(x, y - radius);
      ctx.lineTo(x + radius, y);
      ctx.lineTo(x, y + radius);
      ctx.lineTo(x - radius, y);
      ctx.closePath();
      return;
    }
    ctx.arc(x, y, radius, 0, 6.2832);
  },

  _drawEvidenceTicks: function (ctx, x, y, radius, count, color, alpha) {
    if (!count) return;
    ctx.strokeStyle = color;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = 1;
    for (var i = 0; i < count; i++) {
      var angle = -1.5708 + i * 6.2832 / count;
      ctx.beginPath();
      ctx.moveTo(x + Math.cos(angle) * radius, y + Math.sin(angle) * radius);
      ctx.lineTo(x + Math.cos(angle) * (radius + 3), y + Math.sin(angle) * (radius + 3));
      ctx.stroke();
    }
  },

  _drawLabel: function (ctx, label, x, y, color, occupied) {
    if (!label) return false;
    ctx.font = "10px sans-serif";
    var width = Math.ceil(ctx.measureText(label).width) + 10;
    var box = { left: x - width / 2, right: x + width / 2, top: y - 8, bottom: y + 8 };
    if (box.left < 2 || box.right > this._cw - 2 || box.top < 2 || box.bottom > this._ch - 2) return false;
    for (var i = 0; i < occupied.length; i++) {
      var old = occupied[i];
      if (!(box.right < old.left || box.left > old.right || box.bottom < old.top || box.top > old.bottom)) return false;
    }
    occupied.push(box);
    ctx.globalAlpha = 0.96;
    ctx.fillStyle = "#081018";
    ctx.fillRect(box.left, box.top, width, 16);
    ctx.strokeStyle = color;
    ctx.lineWidth = 0.6;
    ctx.strokeRect(box.left, box.top, width, 16);
    ctx.fillStyle = "#E8F0F8";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, x, y + 0.5);
    return true;
  },

  _scheduleDraw: function () {
    if (this._drawScheduled) return;
    if (!this._canvas || !this._canvas.requestAnimationFrame) {
      this.draw();
      return;
    }
    this._drawScheduled = true;
    var that = this;
    this._canvas.requestAnimationFrame(function () {
      that._drawScheduled = false;
      that.draw();
    });
  },

  draw: function () {
    var ctx = this._ctx; if (!ctx) return;
    var W = this._cw, H = this._ch, nodes = this._nodes, edges = this._edges, hl = this._highlight;
    var lens = this.data.viewLens || (this.data.lens === "city" ? "city" : "structure");
    var tier = this._zoomTierForScale(this._scale);
    ctx.fillStyle = "#05070D"; ctx.fillRect(0, 0, W, H);

    // Static screen-space stars retain atmosphere without a continuous particle loop.
    var stars = this._stars || [];
    for (var s = 0; s < stars.length; s++) {
      ctx.globalAlpha = stars[s].a;
      ctx.fillStyle = "#CFE6FF";
      ctx.beginPath(); ctx.arc(stars[s].x, stars[s].y, stars[s].r, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (lens === "city") {
      for (var h = 0; h < CITY_HALOS.length; h++) {
        var halo = CITY_HALOS[h];
        var hx = this._sx(halo.x), hy = this._sy(halo.y);
        var hr = halo.r * this._base * this._scale;
        if (hr < 6) continue;
        ctx.fillStyle = halo.col;
        ctx.globalAlpha = 0.08;
        ctx.beginPath(); ctx.arc(hx, hy, hr * 1.8, 0, 6.2832); ctx.fill();
        ctx.globalAlpha = 0.035;
        ctx.beginPath(); ctx.arc(hx, hy, hr * 2.8, 0, 6.2832); ctx.fill();
        ctx.globalAlpha = 0.52;
        ctx.fillStyle = halo.col;
        ctx.font = "bold 11px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(halo.name, hx, hy + hr * 1.6 + 4);
      }
    }
    ctx.globalAlpha = 1;

    for (var e = 0; e < edges.length; e++) {
      var edge = edges[e];
      var ea = nodes[edge[0]], eb = nodes[edge[1]];
      if (!ea || !eb || !this._vis(ea) || !this._vis(eb)) continue;
      var edgeOn = !!(hl && hl[edge[0]] && hl[edge[1]]);
      var edgeVisual = this._edgeVisual(edge, edgeOn);
      ctx.strokeStyle = edgeVisual.color;
      ctx.lineWidth = edgeVisual.lineWidth;
      if (ctx.setLineDash) ctx.setLineDash(edgeVisual.dash);
      ctx.beginPath();
      ctx.moveTo(this._sx(ea.x), this._sy(ea.y));
      ctx.lineTo(this._sx(eb.x), this._sy(eb.y));
      ctx.stroke();
    }
    if (ctx.setLineDash) ctx.setLineDash([]);

    var zoomFactor = Math.max(0.72, Math.min(1.65, Math.sqrt(this._scale)));
    var labels = [];
    for (var nIndex = 0; nIndex < nodes.length; nIndex++) {
      var node = nodes[nIndex]; if (!this._vis(node)) continue;
      var nodeOn = !hl || !!hl[nIndex];
      var visual = this._nodeVisual(node);
      var radius = visual.radius * zoomFactor;
      var sx = this._sx(node.x), sy = this._sy(node.y);
      var outer = radius + visual.haloGap;

      ctx.strokeStyle = visual.color;
      ctx.lineWidth = 0.8;
      for (var ring = 0; ring < visual.haloRings; ring++) {
        ctx.globalAlpha = nodeOn ? Math.max(0.06, 0.18 - ring * 0.045) : 0.025;
        ctx.beginPath();
        ctx.arc(sx, sy, outer + ring * 3.5, 0, 6.2832);
        ctx.stroke();
      }

      ctx.globalAlpha = nodeOn ? 0.96 : 0.16;
      ctx.fillStyle = visual.color;
      ctx.strokeStyle = visual.color;
      ctx.lineWidth = visual.shape === "ring" ? 1.8 : 1;
      this._drawNodeShape(ctx, visual.shape, sx, sy, radius);
      if (visual.shape === "ring") ctx.stroke(); else ctx.fill();

      if (visual.evidenceTicks && (nIndex === this._sel || tier === "detail")) {
        this._drawEvidenceTicks(
          ctx, sx, sy, outer + (visual.haloRings - 1) * 3.5 + 2,
          visual.evidenceTicks, visual.color, nodeOn ? 0.72 : 0.16
        );
      }
      if (nIndex === this._sel) {
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1.8;
        ctx.strokeStyle = "#A7FF26";
        ctx.beginPath(); ctx.arc(sx, sy, outer + visual.haloRings * 3.5, 0, 6.2832); ctx.stroke();
      }

      var labelAllowed = nIndex === this._sel || tier === "detail" || (tier === "neighborhood" && nodeOn) || tier === "overview";
      if (labelAllowed) {
        labels.push({
          color: visual.color,
          index: nIndex,
          label: this._nodeLabel(node),
          rank: this._labelRank(node),
          x: sx,
          y: sy - radius - 10,
        });
      }
    }
    labels.sort(function (a, b) {
      if (a.index === this._sel) return -1;
      if (b.index === this._sel) return 1;
      return b.rank - a.rank;
    }.bind(this));
    var occupied = [];
    for (var l = 0; l < labels.length; l++) {
      this._drawLabel(ctx, labels[l].label, labels[l].x, labels[l].y, labels[l].color, occupied);
    }
    ctx.globalAlpha = 1;
    ctx.textBaseline = "alphabetic";
  },

  // ---- smooth fly-to ----
  _flyTo: function (ox, oy, sc) {
    this._anim = { ox: ox, oy: oy, sc: sc };
    var that = this;
    if (this._canvas) this._canvas.requestAnimationFrame(function () { that._tick(); });
  },
  _tick: function () {
    var a = this._anim; if (!a) return;
    this._ox += (a.ox - this._ox) * 0.20;
    this._oy += (a.oy - this._oy) * 0.20;
    this._scale += (a.sc - this._scale) * 0.20;
    this.draw();
    if (Math.abs(a.ox - this._ox) < 0.5 && Math.abs(a.oy - this._oy) < 0.5 && Math.abs(a.sc - this._scale) < 0.01) {
      this._ox = a.ox; this._oy = a.oy; this._scale = a.sc; this._anim = null; this.draw(); return;
    }
    var that = this;
    if (this._canvas) this._canvas.requestAnimationFrame(function () { that._tick(); });
  },
  _flyToNode: function (i) {
    var n = this._nodes[i]; if (!n) return;
    var sc = Math.max(this._scale, 2.0);
    this._flyTo(this._cw / 2 - n.x * this._base * sc, this._ch / 2 - n.y * this._base * sc, sc);
  },

  // ---- L1 AmbientLoop + L2 PulseLoop (canvas.requestAnimationFrame, ~30fps) ----
  _startAnim: function () {
    if (this._animActive) return;
    this._animActive = true;
    this._animT = this._animT || 0;
    this._animLast = Date.now();
    var that = this;
    if (this._canvas) this._canvas.requestAnimationFrame(function () { that._animTick(); });
  },
  _stopAnim: function () { this._animActive = false; },
  _animTick: function () {
    if (!this._animActive || !this._canvas) return;
    var now = Date.now();
    var elapsed = now - (this._animLast || 0);
    if (elapsed >= 33) {  // cap ~30fps
      this._animT = (this._animT || 0) + elapsed / 1000;
      this._animLast = now;
      if (!this._anim) this.draw();  // skip during fly-to to avoid double-draw
    }
    var that = this;
    this._canvas.requestAnimationFrame(function () { that._animTick(); });
  },

  // ---- touch: pan / pinch / tap ----
  onTouchStart: function (ev) {
    this._anim = null;
    var t = ev.touches;
    if (t.length === 1) {
      this._touch = { x: t[0].x, y: t[0].y, sx: t[0].x, sy: t[0].y, t: Date.now(), moved: false };
    } else if (t.length === 2) {
      this._touch = { pinch: true, d: this._dist(t), sc: this._scale };
    }
  },
  onTouchMove: function (ev) {
    var t = ev.touches, st = this._touch; if (!st) return;
    if (st.pinch && t.length === 2) {
      this._scale = Math.max(0.4, Math.min(6, st.sc * (this._dist(t) / (st.d || 1))));
    } else if (t.length === 1) {
      this._ox += t[0].x - st.x; this._oy += t[0].y - st.y;
      st.x = t[0].x; st.y = t[0].y;
      if (Math.abs(t[0].x - st.sx) + Math.abs(t[0].y - st.sy) > 8) st.moved = true;
    }
    this._scheduleDraw();
  },
  onTouchEnd: function () {
    var st = this._touch; this._touch = null;
    if (st && !st.pinch && !st.moved && Date.now() - st.t < 350) {
      var hit = this._hit(st.sx, st.sy);
      if (hit >= 0) {
        if (this._pathMode) this._pickPathTarget(hit);
        else this.selectNode(hit);
      } else if (!this._pathMode) {
        this.clearSel();
      }
    }
  },
  _dist: function (t) { var dx = t[0].x - t[1].x, dy = t[0].y - t[1].y; return Math.sqrt(dx * dx + dy * dy); },
  _hit: function (px, py) {
    var best = -1, bd = 20 * 20;
    for (var i = 0; i < this._nodes.length; i++) {
      var n = this._nodes[i]; if (!this._vis(n)) continue;
      var dx = this._sx(n.x) - px, dy = this._sy(n.y) - py, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  },

  _findNode: function (focusId, query) {
    var fid = String(focusId || "").toLowerCase();
    var q = String(query || "").trim().toLowerCase();
    for (var i = 0; i < this._nodes.length; i++) {
      var n = this._nodes[i];
      if (!this._vis(n)) continue;
      if (fid && String(n.u || "").toLowerCase() === fid) return i;
    }
    if (!q) return -1;
    for (var j = 0; j < this._nodes.length; j++) {
      var m = this._nodes[j];
      if (!this._vis(m)) continue;
      if (String(m.n || "").toLowerCase().indexOf(q) >= 0) return j;
    }
    return -1;
  },

  _focusInitial: function () {
    var hit = this._findNode(this._initialFocusId, this._initialQuery);
    if (hit >= 0) {
      this.selectNode(hit);
    } else if (this._initialQuery || this._initialFocusId) {
      wx.showToast({ title: "星图概览未含该实体", icon: "none" });
    }
  },

  selectNode: function (i, options) {
    var n = this._nodes[i]; if (!n) return;
    options = options || {};
    var same = i === this._sel;
    this._sel = i;
    if (same && this._expanded[n.u]) {
      this._collapseNode(i);
    } else if (!this._expanded[n.u]) {
      this._expandNode(i);
    }
    this._updateSelected(i, same ? undefined : "all");
    this._syncTrail(i, options.trailMode || "replace");
    this._flyToNode(i);
    this.draw();
    this._startAnim();
    this._loadSelectedInspector(n);
    if (n.n) this._markVisited(n.n);
  },
  clearSel: function () {
    this._sel = -1; this._highlight = null;
    this._trail = [];
    this._stopAnim();
    this.setData({ selected: null, relatedFilter: "all", explorationTrail: [] });
    this.draw();
  },

  // A<->B path-finding: arm from the selected node, then the next node tap becomes
  // the target and we render the shortest relation chain through the graph.
  startPathMode: function () {
    var sel = this.data.selected; if (!sel || !sel.id) return;
    this._pathFrom = sel.id; this._pathFromName = sel.name;
    this._pathMode = true;
    this.setData({ pathMode: true, pathHint: "点一个节点，查看与「" + sel.name + "」的关系路径", pathResult: null });
    wx.showToast({ title: "选择目标节点", icon: "none" });
  },
  _pickPathTarget: function (i) {
    var n = this._nodes[i]; if (!n || !n.u) return;
    if (n.u === this._pathFrom) { wx.showToast({ title: "请选另一个节点", icon: "none" }); return; }
    this._pathMode = false;
    this.setData({ pathMode: false, pathHint: "" });
    this._fetchPath(this._pathFrom, this._pathFromName, n.u, n.n);
  },
  _fetchPath: function (from, fromName, to, toName) {
    var that = this;
    this.setData({ pathResult: { status: "loading", summary: "查找关系路径…" } });
    requestApi("/api/v1/weekly/atlas/path", { from: from, to: to }).then(function (r) {
      if (!r || !r.found) {
        that.setData({ pathResult: { status: "empty", summary: fromName + " 与 " + toName + " 暂无可见关系路径" } });
        return;
      }
      var chain = [];
      for (var i = 0; i < r.path.length; i++) {
        var node = r.path[i] || {};
        var edge = r.edges[i];
        chain.push({
          id: node.id,
          name: node.name || node.id,
          type: TYPE_LABEL[normalizeType(node.type)] || node.type || "",
          rel: edge ? relationLabel(edge.relationType) : "",
        });
      }
      that.setData({ pathResult: { status: "ready", hops: r.hops, fromName: fromName, toName: toName, chain: chain, summary: r.hops + " 跳连接" } });
    }).catch(function (e) {
      console.warn("[atlas-starmap] path fetch failed", e);
      that.setData({ pathResult: { status: "error", summary: "关系路径查询失败" } });
    });
  },
  clearPath: function () {
    this._pathMode = false;
    this.setData({ pathMode: false, pathHint: "", pathResult: null });
  },

  onToggleType: function (e) {
    var k = e.currentTarget.dataset.k;
    this._hidden[k] = !this._hidden[k];
    var lg = this.data.legend.map(function (it) {
      return it.k === k ? { k: it.k, label: it.label, col: it.col, on: !it.on } : it;
    });
    this.setData({ legend: lg, nodeCount: this._visibleCount() });
    this.draw();
  },

  randomHop: function () {
    var pool = [];
    for (var i = 0; i < this._nodes.length; i++) {
      if (this._vis(this._nodes[i]) && (this._adj[i] || []).length > 0) pool.push(i);
    }
    if (!pool.length) return;
    this.selectNode(pool[Math.floor(Math.random() * pool.length)], { trailMode: "replace" });
  },
  fitAll: function () {
    this.clearSel();
    this._flyTo(this._cw / 2, this._ch / 2, 1);
  },

  onLens: function (e) {
    var lens = e.currentTarget.dataset.lens;
    this.setData({ lens: lens, serverLens: lens !== "entity" });
    if (lens === "entity") this.draw();
  },
  onSearchInput: function (e) { this.setData({ query: e.detail.value }); },
  onSearchConfirm: function () {
    var q = (this.data.query || "").trim(); if (!q) return;
    var hit = this._findNode("", q);
    if (hit >= 0) { this.selectNode(hit, { trailMode: "replace" }); return; }
    wx.showToast({ title: "未找到", icon: "none" });
  },
  backTrail: function () {
    if (!this._trail || this._trail.length < 2) return;
    var previous = this._trail[this._trail.length - 2];
    var idx = this._nodeIndexById[previous.id];
    if (idx === undefined) return;
    this._trail = this._trail.slice(0, -1);
    this.selectNode(idx, { trailMode: "preserve" });
  },
  onRelatedFilter: function (e) {
    var k = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.k;
    k = normalizeType(k || "all");
    if (k !== "dj" && k !== "venue" && k !== "org" && k !== "series") k = "all";
    this.setData({ relatedFilter: k });
    if (this._sel >= 0) {
      this._updateSelected(this._sel, k);
      this.draw();
    }
  },
  focusRelatedNode: function (e) {
    var id = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.id;
    id = String(id || "");
    if (!id) return;
    var idx = this._nodeIndexById[id];
    if (idx === undefined && this._sel >= 0) {
      this._expandNode(this._sel);
      idx = this._nodeIndexById[id];
    }
    if (idx === undefined) {
      wx.showToast({ title: "邻域加载中", icon: "none" });
      return;
    }
    if (this._hiddenDynamic[id]) {
      this._hiddenDynamic[id] = false;
      this.setData({ nodeCount: this._visibleCount() });
    }
    this.selectNode(idx, { trailMode: "append" });
  },
  openAtlasSearch: function () {
    var q = (this.data.query || "").trim();
    wx.navigateTo({ url: "/pages/atlas-search/atlas-search" + (q ? "?q=" + encodeURIComponent(q) : "") });
  },
  openArtist: function () {
    var sel = this.data.selected; if (!sel || !sel.isDj) {
      wx.showToast({ title: "暂仅支持 DJ 详情", icon: "none" }); return;
    }
    var q = "name=" + encodeURIComponent(sel.name || "");
    if (sel.id) q += "&subjectId=" + encodeURIComponent(sel.id);
    wx.navigateTo({ url: "/pages/artist/artist?" + q });
  },

  onHide: function () { this._stopLoadingCycle(); this._stopAnim(); },
  onUnload: function () { this._stopLoadingCycle(); this._stopAnim(); },

  _startLoadingCycle: function () {
    var that = this;
    var msgs = atlasLoading.LOADING_MSGS;
    var idx = 0;
    this._loadingMsgTimer = setInterval(function () {
      if (!that.data.loading) { that._stopLoadingCycle(); return; }
      idx = (idx + 1) % msgs.length;
      that.setData({ loadingMsg: msgs[idx] });
    }, 2000);
  },

  _stopLoadingCycle: function () {
    if (this._loadingMsgTimer) {
      clearInterval(this._loadingMsgTimer);
      this._loadingMsgTimer = null;
    }
  },

  _shareQueryParts: function () {
    var q = [];
    if (this.data.lens) q.push("lens=" + encodeURIComponent(this.data.lens));
    var selected = this.data.selected || null;
    var queryText = this.data.query || "";
    if (!queryText && selected && selected.name) queryText = selected.name;
    if (queryText) q.push("q=" + encodeURIComponent(queryText));
    if (selected && selected.id) q.push("focusId=" + encodeURIComponent(selected.id));
    return q;
  },

  _shareTitle: function () {
    var selected = this.data.selected || null;
    return selected && selected.name ? "ATLAS 星图 · " + selected.name : "ATLAS 全景星图";
  },

  onShareAppMessage: function () {
    var q = this._shareQueryParts();
    return {
      title: this._shareTitle(),
      path: "/pages/atlas-starmap/atlas-starmap" + (q.length ? "?" + q.join("&") : ""),
    };
  },

  onShareTimeline: function () {
    var q = this._shareQueryParts();
    return {
      title: this._shareTitle(),
      query: q.join("&"),
    };
  },
});
