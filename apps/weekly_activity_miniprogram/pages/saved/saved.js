const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { HAPTIC, vibrateLight } = require("../../utils/haptics");
const { applyLanguageChrome, localizeItems, normalizeLang, text } = require("../../utils/i18n");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

Page({
  data: {
    lang: "zh",
    t: text("saved", "zh"),
    ids: [],
    items: [],
    loading: false,
    error: "",
  },
  lastHapticAt: 0,

  lightHaptic(intervalMs = HAPTIC.tabInterval) {
    const now = Date.now();
    if (now - this.lastHapticAt < intervalMs) return;
    this.lastHapticAt = now;
    vibrateLight();
  },

  onLoad() {
    enableShareMenu();
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("saved", lang);
    this.setData({ lang, t: text("saved", lang) });
  },

  onShareAppMessage() {
    return buildSimpleShare(this.data.lang === "en" ? "HUAIDJ Saved" : "坏DJclub 我的收藏", "/pages/saved/saved", {
      lang: this.data.lang,
    });
  },

  onShareTimeline() {
    return buildSimpleTimeline(this.data.lang === "en" ? "HUAIDJ weekly events" : "坏DJclub 本周电音活动查询", {
      lang: this.data.lang,
    });
  },

  onTabItemTap() {
    this.lightHaptic(HAPTIC.tabInterval);
  },

  onShow() {
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    const ids = wx.getStorageSync("savedActivityIds") || [];
    applyLanguageChrome("saved", lang);
    this.setData({
      lang,
      t: text("saved", lang),
      ids,
    });
    this.loadSavedItems(ids);
  },

  async loadSavedItems(ids) {
    if (!ids.length) {
      this.setData({ items: [], loading: false, error: "" });
      return;
    }
    this.setData({ loading: true, error: "" });
    try {
      // Use batch by-id endpoint to avoid limit=100 local filter miss
      const chunks = [];
      for (let i = 0; i < ids.length; i += 80) {
        chunks.push(ids.slice(i, i + 80));
      }
      const results = await Promise.all(
        chunks.map((chunk) => requestApi("/api/v1/weekly/items/batch", { ids: chunk.join(",") }))
      );
      const allItems = localizeItems(results.flatMap((r) => (r.items || []).map(compactItem)), this.data.lang);
      this.setData({
        items: allItems,
        loading: false,
      });
    } catch (error) {
      console.error("[saved] loadSavedItems failed", error);
      this.setData({ loading: false, error: this.data.t.loadFailed });
    }
  },

  openDetail(event) {
    this.lightHaptic();
    const lang = normalizeLang(this.data.lang || wx.getStorageSync("weeklyActivityLang"));
    wx.navigateTo({
      url: `/pages/detail/detail?id=${event.currentTarget.dataset.id}&lang=${lang}`,
    });
  },
});
