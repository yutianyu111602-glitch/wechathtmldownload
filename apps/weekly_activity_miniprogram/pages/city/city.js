const { requestApi } = require("../../utils/api");
const { applyLanguageChrome, normalizeLang, text, translateCity } = require("../../utils/i18n");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

Page({
  data: {
    lang: "zh",
    t: text("city", "zh"),
    cities: [],
    loading: true,
    error: "",
  },

  onLoad() {
    enableShareMenu();
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("city", lang);
    this.setData({ lang, t: text("city", lang) });
    this.loadCities();
  },

  onShareAppMessage() {
    return buildSimpleShare(this.data.lang === "en" ? "HUAIDJ city events" : "坏DJclub 城市活动列表", "/pages/city/city", {
      lang: this.data.lang,
    });
  },

  onShareTimeline() {
    return buildSimpleTimeline(this.data.lang === "en" ? "HUAIDJ city events" : "坏DJclub 城市活动列表", {
      lang: this.data.lang,
    });
  },

  async loadCities() {
    this.setData({ loading: true, error: "" });
    try {
      const cities = await requestApi("/api/v1/weekly/cities");
      this.setData({
        cities: (cities.cities || [])
          .filter((c) => c.item_count > 0)
          .map((city) => ({
            ...city,
            displayCity: translateCity(city.city || city.city_key, this.data.lang, city.city_key),
          })),
        loading: false,
      });
    } catch (err) {
      console.error("[city] loadCities failed", err);
      this.setData({ loading: false, error: this.data.t.loadFailed });
    }
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  openCity(event) {
    safeVibrate("light");
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
