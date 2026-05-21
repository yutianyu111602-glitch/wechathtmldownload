const { requestApi } = require("../../utils/api");
const { compactItem, joinList } = require("../../utils/format");
const { buildSourcePageUrl, fetchSourceByHash, openSourceUrl } = require("../../utils/sourceAction");
const { buildDetailSourceArticles } = require("../../utils/sourceArticles");
const { buildDetailShare, buildDetailTimeline, enableShareMenu } = require("../../utils/share");

const I18N = {
  zh: {
    lang: "zh",
    langToggle: "EN",
    loading: "加载中",
    loadFailed: "加载失败",
    promoter: "俱乐部",
    date: "日期",
    city: "城市",
    venue: "场地",
    address: "地址",
    genre: "风格",
    lineup: "LINEUP",
    artists: "ARTISTS",
    atlas: "ATLAS",
    atlasVerified: "VERIFIED",
    atlasHint: "HINT",
    description: "简介",
    runningHours: "时间",
    location: "地点",
    music: "音乐",
    tickets: "票务",
    price: "票价",
    save: "收藏",
    saved: "已收藏",
    about: "About",
    copyAddress: "复制地址",
    addressCopied: "地址已复制",
    lineupHint: "点击海报跳转公众号原文查看",
    sourcePreparing: "原文准备中",
    viewSource: "点击海报跳转公众号原文查看",
  },
  en: {
    lang: "en",
    langToggle: "中文",
    loading: "Loading",
    loadFailed: "Failed to load",
    promoter: "Promoter",
    date: "Date",
    city: "City",
    venue: "Venue",
    address: "Address",
    genre: "Genre",
    lineup: "Lineup",
    artists: "Artists",
    atlas: "Atlas",
    atlasVerified: "Verified",
    atlasHint: "Hint",
    description: "Description",
    runningHours: "Running hours",
    location: "Location",
    music: "Music",
    tickets: "Tickets",
    price: "Cost",
    save: "Save",
    saved: "Saved",
    about: "About",
    copyAddress: "Copy address",
    addressCopied: "Address copied",
    lineupHint: "Tap poster to view source",
    sourcePreparing: "Preparing source",
    viewSource: "Tap poster to view source",
  },
};

function normalizeLang(value) {
  return value === "en" ? "en" : "zh";
}

function safeDecode(value) {
  try {
    return decodeURIComponent(String(value || ""));
  } catch {
    return String(value || "");
  }
}

Page({
  data: {
    lang: "zh",
    t: I18N.zh,
    loading: true,
    loadingProgress: 0,
    loadingStep: "加载中",
    error: "",
    item: null,
    priceLabel: "",
    saved: false,
    sourceUrl: "",
    sourceLoading: false,
  },

  onLoad(query) {
    enableShareMenu();
    this.itemId = safeDecode(query.id);
    const lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    wx.setStorageSync("weeklyActivityLang", lang);
    this.setData({ lang, t: I18N[lang] });
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
      const item = compactItem({ ...raw, weeklyAtlas });
      item.sourceArticles = buildDetailSourceArticles(item);
      const savedIds = wx.getStorageSync("savedActivityIds") || [];
      this.setData({
        item,
        priceLabel: joinList(item.price),
        saved: savedIds.includes(item.id),
        loadingProgress: 100,
        loading: false,
      });
      this.prefetchSource(item.sourceHash);
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
    this.setData({ lang, t: I18N[lang] });
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
    const name = event.currentTarget.dataset.name || "";
    if (!name) return;
    wx.navigateTo({
      url: `/pages/artist/artist?name=${encodeURIComponent(name)}&lang=${this.data.lang}`,
    });
  },

  openVenue() {
    const name = this.data.item?.venueLabel || this.data.item?.promoter || this.data.item?.account || "";
    const key = this.data.item?.organizerKey || "";
    if (!name) return;
    wx.navigateTo({
      url: `/pages/venue/venue?name=${encodeURIComponent(name)}&key=${encodeURIComponent(key)}&lang=${this.data.lang}`,
    });
  },

  openSource() {
    const hash = this.data.item?.sourceHash || "";
    if (!hash) return;
    if (this.data.sourceLoading && !this.data.sourceUrl) {
      wx.showToast({ title: this.data.t.sourcePreparing, icon: "none" });
      return;
    }
    if (this.data.sourceUrl) {
      openSourceUrl(this.data.sourceUrl, this.data.lang, { fallbackHash: hash });
      return;
    }
    wx.navigateTo({ url: buildSourcePageUrl(hash, this.data.lang) });
  },

  openSourceArticle(event) {
    const hash = event.currentTarget.dataset.hash || "";
    if (!hash) return;
    if (hash === this.data.item?.sourceHash && this.data.sourceUrl) {
      openSourceUrl(this.data.sourceUrl, this.data.lang, { fallbackHash: hash });
      return;
    }
    wx.navigateTo({ url: buildSourcePageUrl(hash, this.data.lang) });
  },

  openPoster() {
    const hash = this.data.item?.sourceHash || "";
    if (!hash) return;
    if (this.data.sourceLoading && !this.data.sourceUrl) {
      wx.showToast({ title: this.data.t.sourcePreparing, icon: "none" });
      return;
    }
    if (this.data.sourceUrl) {
      openSourceUrl(this.data.sourceUrl, this.data.lang, { fallbackHash: hash });
      return;
    }
    wx.navigateTo({ url: buildSourcePageUrl(hash, this.data.lang) });
  },

  saveItem() {
    const savedIds = wx.getStorageSync("savedActivityIds") || [];
    const id = this.data.item.id;
    const next = savedIds.includes(id)
      ? savedIds.filter((savedId) => savedId !== id)
      : [id, ...savedIds];
    wx.setStorageSync("savedActivityIds", next);
    this.setData({ saved: next.includes(id) });
  },

  copyAddress() {
    if (!this.data.item?.addressLabel) return;
    wx.setClipboardData({
      data: this.data.item.addressLabel,
      success: () => {
        wx.showToast({ title: this.data.t.addressCopied, icon: "none" });
      },
    });
  },
});
