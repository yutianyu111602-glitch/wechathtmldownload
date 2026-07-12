const { requestApi } = require("../../utils/api");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

const TYPE_TABS = [
  { key: "", label: "全部" },
  { key: "dj", label: "DJ" },
  { key: "venue", label: "场地" },
  { key: "org", label: "厂牌" },
  { key: "series", label: "系列" },
];

const TYPE_LABELS = {
  dj: "DJ",
  venue: "场地",
  org: "厂牌",
  organizer: "厂牌",
  series: "系列",
};

function safeText(value) {
  return String(value || "").trim();
}

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

function typeLabel(type) {
  return TYPE_LABELS[String(type || "").toLowerCase()] || "实体";
}

function normalizeResult(row) {
  const name = safeText(row && (row.name || row.displayName || row.n));
  const type = safeText(row && row.type).toLowerCase();
  const city = safeText(row && row.city);
  const aliases = Array.isArray(row && row.aliases) ? row.aliases.map(safeText).filter(Boolean).slice(0, 4) : [];
  const eventCount = Number(row && row.eventCount) || 0;
  const meta = [city, eventCount ? `${eventCount} 条记录` : ""].filter(Boolean).join(" · ");
  return {
    id: safeText(row && (row.id || row.subjectId || row.i)),
    type,
    typeLabel: typeLabel(type),
    name,
    city,
    aliases,
    aliasLine: aliases.join(" / "),
    eventCount,
    meta,
    isDj: type === "dj",
    isVenue: type === "venue",
  };
}

Page({
  data: {
    query: "",
    activeType: "",
    tabs: TYPE_TABS,
    loading: false,
    error: "",
    searched: false,
    results: [],
  },

  onLoad(query) {
    query = query || {};
    const q = safeText(decodeURIComponent(query.q || ""));
    const type = safeText(query.type);
    this._seq = 0;
    enableShareMenu();
    this.setData({
      query: q,
      activeType: TYPE_TABS.some((tab) => tab.key === type) ? type : "",
    });
    if (q) this.search();
  },

  onInput(event) {
    this.setData({ query: event.detail.value, error: "" });
  },

  onTypeTap(event) {
    const type = safeText(event.currentTarget.dataset.type);
    this.setData({ activeType: type });
    if (this.data.query.trim()) this.search();
  },

  onSearchConfirm() {
    this.search();
  },

  clearSearch() {
    this._seq += 1;
    this.setData({ query: "", results: [], error: "", loading: false, searched: false });
  },

  async search() {
    const query = safeText(this.data.query);
    if (!query) {
      this.setData({ searched: false, results: [], error: "" });
      return;
    }
    const seq = (this._seq || 0) + 1;
    this._seq = seq;
    this.setData({ loading: true, error: "", searched: true });
    try {
      const payload = await requestApi("/api/v1/weekly/atlas/search", {
        q: query,
        type: this.data.activeType || undefined,
        limit: 24,
      });
      if (seq !== this._seq) return;
      const results = (payload && Array.isArray(payload.results) ? payload.results : [])
        .map(normalizeResult)
        .filter((item) => item.name);
      this.setData({
        loading: false,
        results,
        error: results.length ? "" : "没有匹配实体",
      });
    } catch (error) {
      console.warn("[atlas-search] search failed", error);
      if (seq !== this._seq) return;
      this.setData({ loading: false, results: [], error: "搜索暂时不可用" });
    }
  },

  openResult(event) {
    const index = Number(event.currentTarget.dataset.index);
    const item = this.data.results[index];
    if (!item) return;
    safeVibrate("light");
    const name = encodeURIComponent(item.name);
    if (item.isDj) {
      const subjectId = encodeURIComponent(item.id || "");
      wx.navigateTo({ url: `/pages/artist/artist?name=${name}${subjectId ? `&subjectId=${subjectId}` : ""}` });
      return;
    }
    if (item.isVenue) {
      wx.navigateTo({ url: `/pages/venue/venue?name=${name}` });
      return;
    }
    const q = encodeURIComponent(item.name);
    const id = encodeURIComponent(item.id || "");
    wx.navigateTo({ url: `/pages/atlas-starmap/atlas-starmap?q=${q}&focusId=${id}` });
  },

  openStarmap() {
    const q = safeText(this.data.query);
    wx.navigateTo({ url: "/pages/atlas-starmap/atlas-starmap" + (q ? `?q=${encodeURIComponent(q)}` : "") });
  },

  onShareAppMessage() {
    const q = safeText(this.data.query);
    const type = safeText(this.data.activeType);
    return buildSimpleShare(q ? `ATLAS 搜索：${q}` : "ATLAS 搜索图鉴", "/pages/atlas-search/atlas-search", { q, type });
  },

  onShareTimeline() {
    const q = safeText(this.data.query);
    const type = safeText(this.data.activeType);
    return buildSimpleTimeline(q ? `ATLAS 搜索：${q}` : "ATLAS 搜索图鉴", { q, type });
  },
});
