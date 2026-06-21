// pages/atlas-starmap/atlas-starmap.js
// Native mp star map (图鉴, not a game): a 2D relationship graph on <canvas type="2d">.
// Loads the bundled overview (data/atlas_starmap.json, from reconciled atlas v2),
// pan/zoom, tap a node to drill its ego-network + see a detail card, search to focus.
// ES5-conservative for the WeChat sandbox. Backend-free first version; DJ-trajectory /
// future-activity lenses come later via a CloudRun endpoint (see design doc).
var bundle = require("../../data/atlas_starmap.json");

var TYPE_LABEL = { dj: "DJ", venue: "场地", org: "厂牌", series: "系列" };

Page({
  data: {
    loading: true,
    lens: "entity",            // entity (works now) | future | dj_traj (server, soon)
    query: "",
    selected: null,            // detail card
    nodeCount: 0,
    serverLens: false,         // true when a not-yet-wired lens is picked
  },

  onLoad: function () {
    this._nodes = (bundle && bundle.nodes) || [];
    this._edges = (bundle && bundle.edges) || [];
    // adjacency for ego drill
    this._adj = {};
    for (var e = 0; e < this._edges.length; e++) {
      var a = this._edges[e][0], b = this._edges[e][1];
      (this._adj[a] || (this._adj[a] = [])).push(b);
      (this._adj[b] || (this._adj[b] = [])).push(a);
    }
    this._scale = 1; this._ox = 0; this._oy = 0;
    this._sel = -1; this._highlight = null;
    this._touch = null;
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
        that._ctx = ctx; that._cw = w; that._ch = h;
        that._base = Math.min(w, h) * 0.42;
        that._ox = w / 2; that._oy = h / 2; that._scale = 1;
        that.setData({ loading: false });
        that.draw();
      });
  },

  _sx: function (x) { return this._ox + x * this._base * this._scale; },
  _sy: function (y) { return this._oy + y * this._base * this._scale; },

  draw: function () {
    var ctx = this._ctx; if (!ctx) return;
    var W = this._cw, H = this._ch, nodes = this._nodes, edges = this._edges, hl = this._highlight;
    ctx.fillStyle = "#05070d"; ctx.fillRect(0, 0, W, H);
    // edges
    for (var e = 0; e < edges.length; e++) {
      var a = nodes[edges[e][0]], b = nodes[edges[e][1]];
      if (!a || !b) continue;
      var eon = !hl || (hl[edges[e][0]] && hl[edges[e][1]]);
      ctx.strokeStyle = eon ? "rgba(125,185,225,0.30)" : "rgba(125,185,225,0.04)";
      ctx.lineWidth = eon ? 0.9 : 0.4;
      ctx.beginPath();
      ctx.moveTo(this._sx(a.x), this._sy(a.y));
      ctx.lineTo(this._sx(b.x), this._sy(b.y));
      ctx.stroke();
    }
    // nodes
    var zk = Math.max(0.6, Math.min(this._scale, 3));
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i], on = !hl || hl[i];
      var r = (2 + n.s * 1.8) * zk;
      var sx = this._sx(n.x), sy = this._sy(n.y);
      ctx.globalAlpha = on ? 1 : 0.16;
      ctx.beginPath(); ctx.arc(sx, sy, r, 0, 6.2832);
      ctx.fillStyle = n.col; ctx.fill();
      if (i === this._sel) {
        ctx.globalAlpha = 1; ctx.lineWidth = 1.6; ctx.strokeStyle = "#A7FF26";
        ctx.beginPath(); ctx.arc(sx, sy, r + 3, 0, 6.2832); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // readable labels: hubs always, others when zoomed or selected
      if (on && (n.s > 1.7 || this._scale > 1.7 || i === this._sel)) {
        ctx.fillStyle = "#e8f0f8"; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(n.n, sx, sy - r - 3);
      }
    }
  },

  // ---- touch: pan / pinch / tap ----
  onTouchStart: function (ev) {
    var t = ev.touches;
    if (t.length === 1) {
      this._touch = { x: t[0].x, y: t[0].y, sx: t[0].x, sy: t[0].y, t: Date.now(), moved: false };
    } else if (t.length === 2) {
      this._touch = { pinch: true, d: this._dist(t), ox: this._ox, oy: this._oy, sc: this._scale };
    }
  },
  onTouchMove: function (ev) {
    var t = ev.touches, st = this._touch; if (!st) return;
    if (st.pinch && t.length === 2) {
      var nd = this._dist(t);
      var k = nd / (st.d || 1);
      this._scale = Math.max(0.4, Math.min(6, st.sc * k));
    } else if (t.length === 1) {
      var dx = t[0].x - st.x, dy = t[0].y - st.y;
      this._ox += dx; this._oy += dy; st.x = t[0].x; st.y = t[0].y;
      if (Math.abs(t[0].x - st.sx) + Math.abs(t[0].y - st.sy) > 8) st.moved = true;
    }
    this.draw();
  },
  onTouchEnd: function (ev) {
    var st = this._touch; this._touch = null;
    if (st && !st.pinch && !st.moved && Date.now() - st.t < 350) {
      var hit = this._hit(st.sx, st.sy);
      if (hit >= 0) this.selectNode(hit); else this.clearSel();
    }
  },
  _dist: function (t) {
    var dx = t[0].x - t[1].x, dy = t[0].y - t[1].y;
    return Math.sqrt(dx * dx + dy * dy);
  },
  _hit: function (px, py) {
    var best = -1, bd = 18 * 18;
    for (var i = 0; i < this._nodes.length; i++) {
      var n = this._nodes[i];
      var dx = this._sx(n.x) - px, dy = this._sy(n.y) - py;
      var d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  },

  selectNode: function (i) {
    var n = this._nodes[i]; if (!n) return;
    this._sel = i;
    var hl = {}; hl[i] = true;
    var nb = this._adj[i] || [];
    for (var k = 0; k < nb.length; k++) hl[nb[k]] = true;
    this._highlight = hl;
    this.setData({
      selected: {
        name: n.n, type: TYPE_LABEL[n.t] || n.t, city: n.c || "未知",
        degree: nb.length, urn: n.u,
      },
    });
    this.draw();
  },
  clearSel: function () {
    this._sel = -1; this._highlight = null;
    this.setData({ selected: null });
    this.draw();
  },

  onLens: function (e) {
    var lens = e.currentTarget.dataset.lens;
    // entity works offline (bundled). future / dj_traj need the CloudRun endpoint.
    this.setData({ lens: lens, serverLens: lens !== "entity" });
    if (lens === "entity") this.draw();
  },

  onSearchInput: function (e) { this.setData({ query: e.detail.value }); },
  onSearchConfirm: function () {
    var q = (this.data.query || "").trim().toLowerCase(); if (!q) return;
    for (var i = 0; i < this._nodes.length; i++) {
      if (String(this._nodes[i].n).toLowerCase().indexOf(q) >= 0) {
        // center + zoom on the match
        this._scale = 2.2;
        this._ox = this._cw / 2 - this._nodes[i].x * this._base * this._scale;
        this._oy = this._ch / 2 - this._nodes[i].y * this._base * this._scale;
        this.selectNode(i);
        return;
      }
    }
    wx.showToast({ title: "未找到", icon: "none" });
  },

  // tap a DJ detail -> open the full artist page (DJ history / relations)
  openArtist: function () {
    var sel = this.data.selected; if (!sel) return;
    var n = this._nodes[this._sel];
    if (n && n.t === "dj") {
      wx.navigateTo({ url: "/pages/artist/artist?name=" + encodeURIComponent(sel.name) });
    } else {
      wx.showToast({ title: "暂仅支持 DJ 详情", icon: "none" });
    }
  },
});
