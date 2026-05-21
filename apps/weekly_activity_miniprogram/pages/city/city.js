const { requestApi } = require("../../utils/api");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

Page({
  data: {
    cities: [],
    loading: true,
    error: "",
  },

  onLoad() {
    enableShareMenu();
    this.loadCities();
  },

  onShareAppMessage() {
    return buildSimpleShare("坏DJclub 城市活动列表", "/pages/city/city");
  },

  onShareTimeline() {
    return buildSimpleTimeline("坏DJclub 城市活动列表");
  },

  async loadCities() {
    this.setData({ loading: true, error: "" });
    try {
      const cities = await requestApi("/api/v1/weekly/cities");
      this.setData({
        cities: (cities.cities || []).filter((c) => c.item_count > 0),
        loading: false,
      });
    } catch (err) {
      console.error("[city] loadCities failed", err);
      this.setData({ loading: false, error: "加载失败" });
    }
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  openCity(event) {
    const key = event.currentTarget.dataset.key || "";
    if (!key) return;
    wx.setStorageSync("weeklyActivityPendingCity", key);
    wx.switchTab({
      url: "/pages/index/index",
      fail: () => {
        wx.navigateTo({
          url: `/pages/index/index?city=${encodeURIComponent(key)}`,
        });
      },
    });
  },
});
