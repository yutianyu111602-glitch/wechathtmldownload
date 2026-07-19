const { applyLanguageChrome, normalizeLang } = require("./utils/i18n");
const { nearestCityKey } = require("./utils/locationCity");

const EVENTS_TAB_INDEX = 0;
const ABOUT_TAB_INDEX = 3;
const DEVTOOLS_API_OVERRIDE_KEY = "weeklyActivityDevtoolsApiOverride:v1";
const DEVTOOLS_API_OVERRIDE_MAX_AGE_MS = 30 * 60 * 1000;
const PREFERRED_CITY_KEY = "weeklyActivityPreferredCity";
const LOCATION_CITY_KEY = "weeklyActivityUserLocCity";

function padDay(d) { return String(d).padStart(2, "0"); }

function isDevtoolsRuntime() {
  try {
    const info = wx.getSystemInfoSync && wx.getSystemInfoSync();
    if (info && String(info.platform || "").toLowerCase() === "devtools") return true;
  } catch (error) {}
  try {
    return typeof __wxConfig !== "undefined" && String(__wxConfig.platform || "").toLowerCase() === "devtools";
  } catch (error) {}
  return false;
}

function normalizeLocalDevtoolsBaseUrl(value) {
  const text = String(value || "").trim().replace(/\/+$/, "");
  if (!/^http:\/\/(?:127\.0\.0\.1|localhost):\d+$/i.test(text)) return "";
  return text;
}

function applyDevtoolsApiOverride(cloud) {
  if (!cloud || !isDevtoolsRuntime()) return false;
  let override = null;
  try {
    override = wx.getStorageSync(DEVTOOLS_API_OVERRIDE_KEY) || null;
  } catch (error) {
    return false;
  }
  const createdAt = Number(override && override.createdAt);
  const overrideAgeMs = Date.now() - createdAt;
  if (!Number.isFinite(createdAt) || createdAt <= 0 || overrideAgeMs < 0 || overrideAgeMs > DEVTOOLS_API_OVERRIDE_MAX_AGE_MS) {
    try {
      wx.removeStorageSync(DEVTOOLS_API_OVERRIDE_KEY);
    } catch (error) {}
    return false;
  }
  const publicBaseUrl = normalizeLocalDevtoolsBaseUrl(override && override.publicBaseUrl);
  if (!publicBaseUrl) return false;

  cloud.publicBaseUrl = publicBaseUrl;
  cloud.staticBaseUrl = "";
  cloud.useCloudDatabaseFirst = false;
  cloud.offlineSnapshotFallback = false;
  cloud.fastOfflineSnapshotFallback = false;
  cloud.publicFallbackDelayMs = 0;
  cloud.cacheMaxAgeMs = 0;
  cloud.cacheFallbackDelayMs = 60000;
  cloud.publicRequestTimeoutMs = 20000;
  cloud.requestTimeoutMs = 20000;
  cloud.cloudClient = {
    callContainer: () => Promise.reject({ error: { code: "DEVTOOLS_API_OVERRIDE_LOCAL_ONLY" } }),
    callFunction: () => Promise.reject({ error: { code: "DEVTOOLS_API_OVERRIDE_LOCAL_ONLY" } }),
  };
  cloud.cloudReady = true;
  cloud.cloudInitPromise = null;
  cloud.devtoolsApiOverrideApplied = true;
  return true;
}

App({
  _locationReadyCallbacks: [],
  _locationRequestPromise: null,

  globalData: {
    userLocationCityKey: "",
    preferredCityKey: "",
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
      atlasPlayerStateFunctionName: "atlasPlayerState",
      useMock: false,
      publicBaseUrl: "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com",
      staticBaseUrl: "",
      mockBaseUrl: "http://127.0.0.1:8787",
      posterUseRawSourceFirst: true,
      cloudInitTimeoutMs: 3000,
      cloudCallTimeoutMs: 6000,
      publicFallbackDelayMs: 250,
      publicRequestTimeoutMs: 3000,
      cacheFallbackDelayMs: 2200,
      offlineSnapshotFallbackDelayMs: -1,
      cacheMaxAgeMs: 6 * 60 * 60 * 1000,
      requestTimeoutMs: 8000,
      offlineSnapshotFallback: true,
      fastOfflineSnapshotFallback: false,
      devtoolsMockFallback: true,
      cloudReady: false,
      cloudClient: null,
      cloudInitPromise: null,
    },
  },

  onLaunch() {
    applyLanguageChrome("index", normalizeLang(wx.getStorageSync("weeklyActivityLang")));
    this.updateActivityTabIcon();
    const devtoolsApiOverrideApplied = applyDevtoolsApiOverride(this.globalData.cloud);
    const { env, useMock } = this.globalData.cloud;
    if (!devtoolsApiOverrideApplied && !useMock && env && wx.cloud) {
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
    this._loadPreferredCity();
    this._loadCachedLocationCity();
    this._requestLocationCity();
  },

  onShow() {
    this.updateActivityTabIcon();
    if (!wx.getStorageSync("weeklySoundAtlasNoticeSeen:v1")) {
      wx.showTabBarRedDot({ index: ABOUT_TAB_INDEX });
    }
  },

  _loadPreferredCity() {
    try {
      const preferredCity = wx.getStorageSync(PREFERRED_CITY_KEY);
      this.globalData.preferredCityKey = typeof preferredCity === "string" ? preferredCity : "";
    } catch (_) {}
  },

  _loadCachedLocationCity() {
    try {
      this._setLocationCityKey(wx.getStorageSync(LOCATION_CITY_KEY));
    } catch (_) {}
  },

  _requestLocationCity() {
    return this.requestLocationCity();
  },

  requestLocationCity() {
    const currentCityKey = this.globalData.userLocationCityKey || "";
    if (currentCityKey) return Promise.resolve(currentCityKey);
    if (this._locationRequestPromise) return this._locationRequestPromise;
    if (typeof wx === "undefined" || typeof wx.getFuzzyLocation !== "function") return Promise.resolve("");
    this._locationRequestPromise = new Promise((resolve) => {
      let settled = false;
      const finish = (cityKey) => {
        if (settled) return;
        settled = true;
        resolve(cityKey || "");
      };
      try {
        wx.getFuzzyLocation({
          type: "gcj02",
          success: (res) => {
            const latitude = Number(res && res.latitude);
            const longitude = Number(res && res.longitude);
            const cityKey = nearestCityKey(latitude, longitude);
            if (cityKey) this._setLocationCityKey(cityKey);
            finish(cityKey);
          },
          fail() {
            finish("");
          },
        });
      } catch (_) {
        finish("");
      }
    }).then((cityKey) => {
      this._locationRequestPromise = null;
      return cityKey || this.globalData.userLocationCityKey || "";
    });
    return this._locationRequestPromise;
  },

  _setLocationCityKey(key) {
    const cityKey = typeof key === "string" ? key.trim() : "";
    if (!cityKey) return;
    const previous = this.globalData.userLocationCityKey || "";
    this.globalData.userLocationCityKey = cityKey;
    try {
      wx.setStorageSync(LOCATION_CITY_KEY, cityKey);
    } catch (_) {}
    if (previous !== cityKey) {
      this._notifyLocationReady(cityKey);
    }
  },

  _notifyLocationReady(key) {
    (this._locationReadyCallbacks || []).slice().forEach((callback) => {
      try {
        callback(key);
      } catch (_) {}
    });
  },

  onLocationReady(callback) {
    if (typeof callback !== "function") return function noop() {};
    this._locationReadyCallbacks = this._locationReadyCallbacks || [];
    this._locationReadyCallbacks.push(callback);
    const cityKey = this.globalData.userLocationCityKey || "";
    if (cityKey) {
      try {
        callback(cityKey);
      } catch (_) {}
    }
    return () => {
      this._locationReadyCallbacks = (this._locationReadyCallbacks || []).filter((item) => item !== callback);
    };
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
