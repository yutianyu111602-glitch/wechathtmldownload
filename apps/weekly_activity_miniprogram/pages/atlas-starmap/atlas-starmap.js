// pages/atlas-starmap/atlas-starmap.js
// Native mp star map (图鉴, not a game): a 2D relationship graph on <canvas type="2d">.
// Cooler + explorable: glowing nodes, deep-space backdrop, edges colored by relation type,
// smooth fly-to animation, type-legend filtering, random hop. Loads the bundled overview
// (data/atlas_starmap.json, from reconciled atlas v2). ES5-conservative for the WeChat sandbox.
var bundle = require("../../data/atlas_starmap.json");

var TYPE_LABEL = { dj: "DJ", venue: "场地", org: "厂牌", series: "系列" };
var EDGE_COLOR = {
  b2b: "rgba(248,197,106,A)",        // amber — deep b2b
  collab: "rgba(125,185,225,A)",     // blue — co-bill
  resident_at: "rgba(45,212,191,A)", // teal — residency
  signed_to: "rgba(183,148,246,A)",  // violet — label
  held_at: "rgba(45,212,191,A)",
  presented_by: "rgba(183,148,246,A)",
};
function edgeColor(t, a) { return (EDGE_COLOR[t] || "rgba(125,185,225,A)").replace("A", a); }

Page({
  data: {
    loading: true,
    lens: "entity",
    query: "",
    selected: null,
    nodeCount: 0,
    serverLens: false,
    legend: [
      { k: "dj", label: "DJ", col: "#7fd4ff", on: true },
      { k: "venue", label: "场地", col: "#ffcf6b", on: true },
      { k: "org", label: "厂牌", col: "#b794f6", on: true },
      { k: "series", label: "系列", col: "#2dd4bf", on: true },
    ],
  },

  onLoad: function () {
    this._nodes = (bundle && bundle.nodes) || [];
    this._edges = (bundle && bundle.edges) || [];
    this._adj = {};
    for (var e = 0; e < this._edges.length; e++) {
      var a = this._edges[e][0], b = this._edges[e][1];
      (this._adj[a] || (this._adj[a] = [])).push(b);
      (this._adj[b] || (this._adj[b] = [])).push(a);
    }
    this._scale = 1; this._ox = 0; this._oy = 0;
    this._sel = -1; this._highlight = null; this._touch = null;
    this._hidden = {};            // type -> true when filtered out
    this._anim = null;
    this.setData({ nodeCount: this._nodes.length });
  },

  onReady: function () {
    var that = this;
    wx.createSelectorQuery().in(this).select("#sm")
      .fields({ node: true, size: true }).exec(function (res) {
        if (!res || !res[0] || !res[0].node) return;
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
            r: 0.4 + Math.random() * 1.1, a: 0.15 + Math.random() * 0.5 });
        }
        that.setData({ loading: false });
        that.draw();
      });
  },

  _sx: function (x) { return this._ox + x * this._base * this._scale; },
  _sy: function (y) { return this._oy + y * this._base * this._scale; },
  _vis: function (n) { return !this._hidden[n.t]; },

  draw: function () {
    var ctx = this._ctx; if (!ctx) return;
    var W = this._cw, H = this._ch, nodes = this._nodes, edges = this._edges, hl = this._highlight;
    // backdrop
    ctx.fillStyle = "#05070d"; ctx.fillRect(0, 0, W, H);
    var st = this._stars || [];
    for (var s = 0; s < st.length; s++) {
      ctx.globalAlpha = st[s].a; ctx.fillStyle = "#cfe6ff";
      ctx.beginPath(); ctx.arc(st[s].x, st[s].y, st[s].r, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
    // edges (colored by relation type)
    for (var e = 0; e < edges.length; e++) {
      var a = nodes[edges[e][0]], b = nodes[edges[e][1]];
      if (!a || !b || !this._vis(a) || !this._vis(b)) continue;
      var eon = !hl || (hl[edges[e][0]] && hl[edges[e][1]]);
      ctx.strokeStyle = edgeColor(edges[e][2], eon ? "0.45" : "0.05");
      ctx.lineWidth = eon ? 1.0 : 0.4;
      ctx.beginPath();
      ctx.moveTo(this._sx(a.x), this._sy(a.y));
      ctx.lineTo(this._sx(b.x), this._sy(b.y));
      ctx.stroke();
    }
    // nodes (glow halo + solid core)
    var zk = Math.max(0.6, Math.min(this._scale, 3));
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i]; if (!this._vis(n)) continue;
      var on = !hl || hl[i];
      var r = (2 + n.s * 1.8) * zk;
      var sx = this._sx(n.x), sy = this._sy(n.y);
      // halo
      ctx.globalAlpha = on ? 0.22 : 0.05;
      ctx.fillStyle = n.col;
      ctx.beginPath(); ctx.arc(sx, sy, r * 2.2, 0, 6.2832); ctx.fill();
      // core
      ctx.globalAlpha = on ? 1 : 0.18;
      ctx.beginPath(); ctx.arc(sx, sy, r, 0, 6.2832); ctx.fill();
      if (i === this._sel) {
        ctx.globalAlpha = 1; ctx.lineWidth = 1.8; ctx.strokeStyle = "#A7FF26";
        ctx.beginPath(); ctx.arc(sx, sy, r + 4, 0, 6.2832); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      if (on && (n.s > 1.7 || this._scale > 1.7 || i === this._sel)) {
        ctx.fillStyle = "#e8f0f8"; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(n.n, sx, sy - r - 4);
      }
    }
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
    this.draw();
  },
  onTouchEnd: function () {
    var st = this._touch; this._touch = null;
    if (st && !st.pinch && !st.moved && Date.now() - st.t < 350) {
      var hit = this._hit(st.sx, st.sy);
      if (hit >= 0) this.selectNode(hit); else this.clearSel();
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

  selectNode: function (i) {
    var n = this._nodes[i]; if (!n) return;
    this._sel = i;
    var hl = {}; hl[i] = true;
    var nb = this._adj[i] || [], brk = {};
    for (var k = 0; k < nb.length; k++) {
      hl[nb[k]] = true;
      var bt = this._nodes[nb[k]].t;
      brk[bt] = (brk[bt] || 0) + 1;
    }
    this._highlight = hl;
    var parts = [];
    for (var ty in brk) parts.push(brk[ty] + " " + (TYPE_LABEL[ty] || ty));
    this.setData({
      selected: { name: n.n, type: TYPE_LABEL[n.t] || n.t, city: n.c || "未知",
        degree: nb.length, breakdown: parts.join(" · "), isDj: n.t === "dj" },
    });
    this._flyToNode(i);
  },
  clearSel: function () {
    this._sel = -1; this._highlight = null;
    this.setData({ selected: null });
    this.draw();
  },

  onToggleType: function (e) {
    var k = e.currentTarget.dataset.k;
    this._hidden[k] = !this._hidden[k];
    var lg = this.data.legend.map(function (it) {
      return it.k === k ? { k: it.k, label: it.label, col: it.col, on: !it.on } : it;
    });
    this.setData({ legend: lg });
    this.draw();
  },

  randomHop: function () {
    var pool = [];
    for (var i = 0; i < this._nodes.length; i++) {
      if (this._vis(this._nodes[i]) && (this._adj[i] || []).length > 0) pool.push(i);
    }
    if (!pool.length) return;
    this.selectNode(pool[Math.floor(Math.random() * pool.length)]);
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
    var q = (this.data.query || "").trim().toLowerCase(); if (!q) return;
    for (var i = 0; i < this._nodes.length; i++) {
      if (this._vis(this._nodes[i]) && String(this._nodes[i].n).toLowerCase().indexOf(q) >= 0) {
        this.selectNode(i); return;
      }
    }
    wx.showToast({ title: "未找到", icon: "none" });
  },
  openArtist: function () {
    var sel = this.data.selected; if (!sel || !sel.isDj) {
      wx.showToast({ title: "暂仅支持 DJ 详情", icon: "none" }); return;
    }
    wx.navigateTo({ url: "/pages/artist/artist?name=" + encodeURIComponent(sel.name) });
  },
});
