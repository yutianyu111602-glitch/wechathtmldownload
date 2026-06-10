const { applyLanguageChrome, normalizeLang } = require("./utils/i18n");

const EVENTS_TAB_INDEX = 0;
const ABOUT_TAB_INDEX = 3;

function padDay(d) { return String(d).padStart(2, "0"); }

App({
  globalData: {
    cloud: {
      env: "huaidjweekly-d8g1go7-d0a07863e3e",
      service: "weekly-api",
      // 绑定微信云开发 AI 统一代理云函数名。留空则仅走 CloudRun 接口（容器/公开路由回退）。
      aiFunctionName: "weeklyAiProxy",
      aiFunctionTimeoutMs: 10000,
      aiUseFunctionFirst: true,
      databaseFunctionName: "weeklyDataSync",
      databaseFunctionTimeoutMs: 800,
      databaseBackupDelayMs: 0,
      databaseCircuitBreakerMs: 30 * 60 * 1000,
      useCloudDatabaseFirst: false,
      useMock: false,
      publicBaseUrl: "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com",
      staticBaseUrl: "",
      mockBaseUrl: "http://127.0.0.1:8787",
      posterUseRawSourceFirst: true,
      cloudInitTimeoutMs: 3000,
      cloudCallTimeoutMs: 6000,
      publicFallbackDelayMs: 250,
      publicRequestTimeoutMs: 8000,
      cacheFallbackDelayMs: 2200,
      offlineSnapshotFallbackDelayMs: 2500,
      cacheMaxAgeMs: 6 * 60 * 60 * 1000,
      requestTimeoutMs: 8000,
      offlineSnapshotFallback: true,
      fastOfflineSnapshotFallback: true,
      devtoolsMockFallback: true,
      cloudReady: false,
      cloudClient: null,
      cloudInitPromise: null,
    },
  },

  onLaunch() {
    applyLanguageChrome("index", normalizeLang(wx.getStorageSync("weeklyActivityLang")));
    this.updateActivityTabIcon();
    const { env, useMock } = this.globalData.cloud;
    if (!useMock && env && wx.cloud) {
      try {
        const cloudClient = wx.cloud;
        this.globalData.cloud.cloudClient = cloudClient;
        this.globalData.cloud.cloudInitPromise = Promise.resolve(
          cloudClient.init({ env, traceUser: true })
        ).then(() => {
          this.globalData.cloud.cloudReady = true;
          return cloudClient;
        });
      } catch (error) {
        this.globalData.cloud.cloudClient = null;
        this.globalData.cloud.cloudInitPromise = null;
        this.globalData.cloud.cloudReady = false;
        console.warn("cloud init skipped", error && (error.errMsg || error.message || error));
      }
    }
  },

  onShow() {
    this.updateActivityTabIcon();
    if (!wx.getStorageSync("weeklySoundAtlasNoticeSeen:v1")) {
      wx.showTabBarRedDot({ index: ABOUT_TAB_INDEX });
    }
  },

  updateActivityTabIcon() {
    if (typeof wx.setTabBarItem !== "function") return;
    const day = padDay(new Date().getDate());
    wx.setTabBarItem({
      index: EVENTS_TAB_INDEX,
      iconPath: `assets/tabbar/tab_activity_${day}.png`,
      selectedIconPath: `assets/tabbar/tab_activity_selected_${day}.png`,
    });
  },
});
