const ATLAS_BETA_URL = "https://huaidj.club/atlas/starmap";
const ABOUT_TAB_INDEX = 3;
const SOUND_NOTICE_SEEN_KEY = "weeklySoundAtlasNoticeSeen:v1";
const BUILD_IDENTITY = require("../../config/buildIdentity");
const { HAPTIC, vibrateLight } = require("../../utils/haptics");
const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

Page({
  data: {
    lang: "zh",
    t: text("about", "zh"),
    version: BUILD_IDENTITY.version,
    buildDate: BUILD_IDENTITY.buildDate,
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
    try { wx.setStorageSync(SOUND_NOTICE_SEEN_KEY, true); } catch (_) {}
    try { wx.hideTabBarRedDot({ index: ABOUT_TAB_INDEX }); } catch (_) {}
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

  openSound() {
    this.lightHaptic(HAPTIC.tabInterval);
    wx.navigateTo({
      url: "/pages/sound/sound",
      fail: () => wx.reLaunch({ url: "/pages/sound/sound" }),
    });
  },
});
