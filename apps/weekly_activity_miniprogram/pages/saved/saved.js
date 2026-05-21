const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { HAPTIC, vibrateLight } = require("../../utils/haptics");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

Page({
  data: {
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
  },

  onShareAppMessage() {
    return buildSimpleShare("坏DJclub 我的收藏", "/pages/saved/saved");
  },

  onShareTimeline() {
    return buildSimpleTimeline("坏DJclub 本周电音活动查询");
  },

  onTabItemTap() {
    this.lightHaptic(HAPTIC.tabInterval);
  },

  onShow() {
    const ids = wx.getStorageSync("savedActivityIds") || [];
    this.setData({
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
      const allItems = results.flatMap((r) => (r.items || []).map(compactItem));
      this.setData({
        items: allItems,
        loading: false,
      });
    } catch (error) {
      console.error("[saved] loadSavedItems failed", error);
      this.setData({ loading: false, error: "加载失败" });
    }
  },

  openDetail(event) {
    const lang = wx.getStorageSync("weeklyActivityLang") || "zh";
    wx.navigateTo({
      url: `/pages/detail/detail?id=${event.currentTarget.dataset.id}&lang=${lang}`,
    });
  },
});
