const { requestApi } = require("../../utils/api");
const { compactItem, joinList } = require("../../utils/format");
const { applyLanguageChrome, localizeItem, localizedSourceArticles, normalizeLang, text } = require("../../utils/i18n");
const { buildSourcePageUrl, fetchSourceByHash, openSourceUrl } = require("../../utils/sourceAction");
const { buildDetailSourceArticles } = require("../../utils/sourceArticles");
const { buildDetailShare, buildDetailTimeline, enableShareMenu } = require("../../utils/share");
const { posterFallbackState, posterImageErrorFallback, resolvePosterUrlForItem } = require("../../utils/cloudPosterUrls");

function safeDecode(value) {
  try {
    return decodeURIComponent(String(value || ""));
  } catch {
    return String(value || "");
  }
}

function mapDestination(location) {
  if (!location) return null;
  const latitude = Number(location.latitude);
  const longitude = Number(location.longitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;
  if (latitude === 0 && longitude === 0) return null;
  return { latitude, longitude };
}

function safeHideLoading() {
  if (typeof wx !== "undefined" && typeof wx.hideLoading === "function") wx.hideLoading();
}

function safeShowLoading(options) {
  if (typeof wx !== "undefined" && typeof wx.showLoading === "function") wx.showLoading(options);
}

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

function preferredSourceHash(item) {
  const direct = String(item?.sourceHash || "").trim();
  if (direct) return direct;
  const sourceArticles = Array.isArray(item?.sourceArticles) ? item.sourceArticles : [];
  for (const article of sourceArticles) {
    const hash = String(article?.hash || "").trim();
    if (hash) return hash;
  }
  return "";
}

Page({
  data: {
    lang: "zh",
    t: text("detail", "zh"),
    loading: true,
    loadingProgress: 0,
    loadingStep: "加载中",
    error: "",
    item: null,
    priceLabel: "",
    saved: false,
    sourceUrl: "",
    sourceLoading: false,
    posterLoadFailed: false,
  },

  onLoad(query) {
    enableShareMenu();
    this.itemId = safeDecode(query.id);
    const lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    wx.setStorageSync("weeklyActivityLang", lang);
    applyLanguageChrome("detail", lang);
    this.setData({ lang, t: text("detail", lang) });
    this.loadDetail();
  },

  onShareAppMessage() {
    return buildDetailShare(this.data.item, this.data.lang, this.itemId);
  },

  onShareTimeline() {
    return buildDetailTimeline(this.data.item, this.data.lang, this.itemId);
  },

  async loadDetail() {
    this.setData({
      loading: true,
      loadingProgress: 12,
      loadingStep: this.data.t.loading,
      error: "",
    });
    try {
      this.setData({ loadingProgress: 42, loadingStep: this.data.t.loading });
      const raw = await requestApi(`/api/v1/weekly/items/${this.itemId}`);
      this.setData({ loadingProgress: 76, loadingStep: this.data.t.sourcePreparing });
      let weeklyAtlas = null;
      try {
        weeklyAtlas = await requestApi(`/api/v1/weekly/atlas-events/${this.itemId}`);
      } catch (atlasError) {
        console.warn("[detail] atlas snapshot unavailable", atlasError && (atlasError.errMsg || atlasError.message || atlasError));
      }
      let compact;
      try {
        compact = compactItem({ ...raw, weeklyAtlas });
      } catch (compactError) {
        console.error("[detail] compactItem failed", compactError);
        // 回退：跳过 compact 处理，直接使用 raw + weeklyAtlas 原始字段
        compact = { ...raw, weeklyAtlas, id: raw.id || this.itemId };
      }
      const item = await resolvePosterUrlForItem(localizeItem(compact, this.data.lang));
      item.sourceArticles = localizedSourceArticles(buildDetailSourceArticles(compact), this.data.lang);
      const savedIds = wx.getStorageSync("savedActivityIds") || [];
      this.setData({
        item,
        priceLabel: joinList(item.price),
        saved: savedIds.includes(item.id),
        posterLoadFailed: false,
        loadingProgress: 100,
        loading: false,
      });
      this.prefetchSource(preferredSourceHash(item));
    } catch (error) {
      console.error("[detail] loadDetail failed", error);
      this.setData({
        loading: false,
        error: this.data.t.loadFailed,
      });
    }
  },

  async prefetchSource(hash) {
    if (!hash) {
      this.setData({ sourceUrl: "", sourceLoading: false });
      return;
    }
    this.setData({ sourceUrl: "", sourceLoading: true });
    const url = await fetchSourceByHash(hash);
    if (this.data.item?.sourceHash !== hash) return;
    this.setData({ sourceUrl: url, sourceLoading: false });
  },

  toggleLang() {
    const lang = this.data.lang === "en" ? "zh" : "en";
    wx.setStorageSync("weeklyActivityLang", lang);
    applyLanguageChrome("detail", lang);
    this.setData({
      lang,
      t: text("detail", lang),
    });
    if (this.itemId) this.loadDetail();
  },

  goBack() {
    const fallbackHome = () => {
      wx.switchTab({
        url: "/pages/index/index",
        fail: () => wx.reLaunch({ url: "/pages/index/index" }),
      });
    };
    try {
      const pages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
      if (pages.length > 1) {
        wx.navigateBack({ delta: 1, fail: fallbackHome });
        setTimeout(() => {
          try {
            const currentPages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
            const current = currentPages[currentPages.length - 1];
            if (current && current.route === "pages/detail/detail") fallbackHome();
          } catch {}
        }, 300);
        return;
      }
    } catch {}
    fallbackHome();
  },

  openArtist(event) {
    safeVibrate("light");
    const name = event.currentTarget.dataset.name || "";
    if (!name) return;
    wx.navigateTo({
      url: `/pages/artist/artist?name=${encodeURIComponent(name)}&lang=${this.data.lang}`,
    });
  },

  openVenue() {
    safeVibrate("light");
    const name = this.data.item?.venueLabel || this.data.item?.promoter || this.data.item?.account || "";
    const key = this.data.item?.organizerKey || "";
    if (!name) return;
    safeShowLoading({ title: this.data.t.clubSchedule || "加载排期…", mask: false });
    wx.navigateTo({
      url: `/pages/venue/venue?name=${encodeURIComponent(name)}&key=${encodeURIComponent(key)}&lang=${this.data.lang}`,
      complete: () => safeHideLoading(),
    });
  },

  openSource() {
    safeVibrate("light");
    const hash = preferredSourceHash(this.data.item);
    if (!hash) return;
    if (this.data.sourceLoading && !this.data.sourceUrl) {
      wx.showToast({ title: this.data.t.sourcePreparing, icon: "none" });
      return;
    }
    if (this.data.sourceUrl) {
      // 优先用官方接口打开公众号原文；微信不允许时 fallback 到 source 页面（提供链接复制等操作入口）
      openSourceUrl(this.data.sourceUrl, this.data.lang, {
        fallbackHash: hash,
        suppressFallback: false,
        fail: () => this.copyArticleUrl(this.data.sourceUrl),
      });
      return;
    }
    // sourceUrl 尚未就绪时：尝试即时获取，而非直接跳 source 页（source 页也需调同一个 API）
    this.setData({ sourceLoading: true });
    fetchSourceByHash(hash).then((url) => {
      this.setData({ sourceUrl: url, sourceLoading: false });
      if (url) {
        openSourceUrl(url, this.data.lang, {
          fallbackHash: hash,
          suppressFallback: false,
          fail: () => this.copyArticleUrl(url),
        });
      } else {
        wx.navigateTo({ url: buildSourcePageUrl(hash, this.data.lang) });
      }
    }).catch(() => {
      this.setData({ sourceLoading: false });
      wx.navigateTo({ url: buildSourcePageUrl(hash, this.data.lang) });
    });
  },

  copyArticleUrl(url) {
    const link = String(url || "").trim();
    if (!link) return;
    wx.setClipboardData({
      data: link,
      success: () => {
        wx.showToast({
          title: this.data.t.linkCopied || "原文链接已复制，可粘贴到浏览器打开",
          icon: "none",
        });
      },
    });
  },

  copyDiscoveryLink(event) {
    safeVibrate("light");
    const url = String(event.currentTarget.dataset.url || "").trim();
    if (!url) return;
    wx.setClipboardData({
      data: url,
      success: () => {
        wx.showToast({
          title: this.data.t.linkCopied || this.data.t.copyLink || "链接已复制",
          icon: "none",
        });
      },
    });
  },

  openSourceArticle(event) {
    safeVibrate("light");
    const hash = event.currentTarget.dataset.hash || "";
    if (!hash) return;
    if (hash === preferredSourceHash(this.data.item) && this.data.sourceUrl) {
      openSourceUrl(this.data.sourceUrl, this.data.lang, { fallbackHash: hash });
      return;
    }
    wx.navigateTo({ url: buildSourcePageUrl(hash, this.data.lang) });
  },

  openPoster() {
    // Product rule (2026-06-13): tapping the poster opens the source article
    // when a trustworthy one exists; otherwise it falls back to previewing.
    if (preferredSourceHash(this.data.item)) {
      this.openSource();
      return;
    }
    safeVibrate("light");
    const coverUrl = this.data.item?.coverUrl;
    if (coverUrl) {
      wx.previewImage({ urls: [coverUrl], current: coverUrl });
      return;
    }
    wx.showToast({ title: this.data.t.posterUnavailable, icon: "none" });
  },

  onPosterImageLoad() {
    if (this.data.posterLoadFailed) this.setData({ posterLoadFailed: false });
  },

  async onPosterImageError() {
    const item = this.data.item || {};
    const fallback = await posterImageErrorFallback(item, item.coverUrl || "");
    if (fallback) {
      this.setData({
        item: {
          ...item,
          ...posterFallbackState(item, fallback),
        },
        posterLoadFailed: false,
      });
      return;
    }
    this.setData({ posterLoadFailed: true });
  },

  saveItem() {
    safeVibrate("medium");
    const savedIds = wx.getStorageSync("savedActivityIds") || [];
    const id = this.data.item.id;
    const next = savedIds.includes(id)
      ? savedIds.filter((savedId) => savedId !== id)
      : [id, ...savedIds];
    wx.setStorageSync("savedActivityIds", next);
    this.setData({ saved: next.includes(id) });
  },

  handleAddressTap() {
    safeVibrate("light");
    this.openMapLocation();
  },

  openMapLocation() {
    const location = this.data.item?.mapLocation;
    const destination = mapDestination(location);
    if (!destination) {
      if (this.copyAddress({ silent: true })) {
        wx.showToast({ title: this.data.t.openMapFallback, icon: "none" });
      }
      return;
    }
    if (typeof wx.openLocation !== "function") {
      if (this.copyAddress({ silent: true })) {
        wx.showToast({ title: this.data.t.openMapFailed, icon: "none" });
      }
      return;
    }
    wx.openLocation({
      latitude: destination.latitude,
      longitude: destination.longitude,
      name: location.name || this.data.item?.venueLabel || this.data.item?.displayTitle || "",
      address: location.address || this.data.item?.addressLabel || "",
      scale: 16,
      fail: () => {
        this.copyAddress({ silent: true });
        wx.showToast({ title: this.data.t.openMapFailed, icon: "none" });
      },
    });
  },

  copyAddress(options = {}) {
    if (!this.data.item?.addressLabel) return false;
    wx.setClipboardData({
      data: this.data.item.addressLabel,
      success: () => {
        if (!options.silent) {
          wx.showToast({ title: this.data.t.addressCopied, icon: "none" });
        }
      },
    });
    return true;
  },
});
