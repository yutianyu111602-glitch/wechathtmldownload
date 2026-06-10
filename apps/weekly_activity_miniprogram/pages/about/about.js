const VERSION = "0.5.15";
const BUILD_DATE = "2026-06-11";
const ATLAS_BETA_URL = "https://huaidj.club/";
const ABOUT_TAB_INDEX = 3;
const { HAPTIC, vibrateLight } = require("../../utils/haptics");
const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

Page({
  data: {
    lang: "zh",
    t: text("about", "zh"),
    version: VERSION,
    buildDate: BUILD_DATE,
    year: new Date().getFullYear(),
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
    wx.removeStorageSync("weeklySoundAtlasNoticeSeen:v1");
    wx.hideTabBarRedDot({ index: ABOUT_TAB_INDEX });
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("about", lang);
    this.setData({
      lang,
      t: text("about", lang),
      year: new Date().getFullYear(),
    });
  },

  onShareAppMessage() {
    return buildSimpleShare(this.data.lang === "en" ? "HUAIDJ weekly events" : "坏DJclub 本周电音活动查询", "/pages/index/index", {
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

  copyEnvId() {
    wx.setClipboardData({
      data: "huaidjweekly-d8g1go7-d0a07863e3e",
      success: () => wx.showToast({ title: this.data.t.copied, icon: "none" }),
    });
  },

  openAtlasBeta() {
    this.lightHaptic(HAPTIC.tabInterval);
    const sourceRoute = "/pages/source/source?url="
      + encodeURIComponent(ATLAS_BETA_URL)
      + `&lang=${encodeURIComponent(this.data.lang || "zh")}`;
    wx.navigateTo({
      url: sourceRoute,
      fail: () => {
        wx.setClipboardData({
          data: ATLAS_BETA_URL,
          success: () => {
            wx.showModal({
              title: this.data.t.atlasBrowserGuideTitle || "",
              content: this.data.t.atlasBrowserGuide || "",
              confirmText: this.data.t.atlasBrowserConfirm || "OK",
              showCancel: false,
            });
          },
          fail: () => {
            wx.showToast({ title: this.data.t.atlasCopied || this.data.t.copied, icon: "none" });
          },
        });
      },
    });
  },

  openInterview() {
    this.lightHaptic(HAPTIC.tabInterval);
    wx.navigateTo({
      url: "/pages/interview/interview",
      fail: () => wx.reLaunch({ url: "/pages/interview/interview" }),
    });
  },

  onLogoLongpress() {
    this.lightHaptic();
    wx.showModal({
      title: "管理员验证",
      content: "",
      editable: true,
      placeholderText: "请输入管理员密码",
      success(res) {
        if (res.confirm && res.content === "196823") {
          wx.navigateTo({
            url: "/pages/admin/admin",
            fail() {
              wx.showToast({ title: "页面加载失败", icon: "none" });
            },
          });
        } else if (res.confirm) {
          wx.showToast({ title: "密码错误", icon: "none" });
        }
      },
    });
  },
});
