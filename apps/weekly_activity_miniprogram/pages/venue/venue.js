const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { openSourceByHash } = require("../../utils/sourceAction");
const { buildVenueSourceArticles } = require("../../utils/sourceArticles");
const { buildNamedPageShare, buildNamedPageTimeline, enableShareMenu } = require("../../utils/share");

function venueMatches(item, name, key) {
  const targetKey = String(key || "").trim();
  if (targetKey) return item.organizerKey === targetKey || item.organizer_key === targetKey;
  const target = String(name || "").trim().toLowerCase();
  if (!target) return false;
  return [item.venueLabel, item.promoter, item.account, item.cardLocationLabel]
    .filter(Boolean)
    .some((value) => String(value).trim().toLowerCase().includes(target) || target.includes(String(value).trim().toLowerCase()));
}

async function fetchAllCurrentItems() {
  const allItems = [];
  let cursor = 0;
  for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
    const current = await requestApi("/api/v1/weekly/current", { limit: 100, cursor });
    allItems.push(...(current.items || []));
    const nextCursor = current.page?.nextCursor;
    if (nextCursor === null || nextCursor === undefined || nextCursor === "") break;
    const parsedNext = Number(nextCursor);
    if (!Number.isFinite(parsedNext) || parsedNext <= cursor) break;
    cursor = parsedNext;
  }
  return allItems;
}

Page({
  data: {
    name: "",
    loading: true,
    error: "",
    events: [],
    sourceArticles: [],
    address: "",
    aboutLines: [],
  },

  onLoad(query) {
    enableShareMenu();
    this.name = decodeURIComponent(query.name || "");
    this.key = decodeURIComponent(query.key || "");
    this.lang = query.lang === "en" ? "en" : "zh";
    this.setData({ name: this.name });
    this.loadVenue();
  },

  onShareAppMessage() {
    return buildNamedPageShare("/pages/venue/venue", this.data.name || this.name, "zh", "本周活动");
  },

  onShareTimeline() {
    return buildNamedPageTimeline(this.data.name || this.name, "zh", "本周活动");
  },

  async loadVenue() {
    try {
      const events = (await fetchAllCurrentItems()).map(compactItem).filter((item) => venueMatches(item, this.name, this.key));
      const sourceArticles = buildVenueSourceArticles(events);
      const first = events[0] || {};
      this.setData({
        events,
        sourceArticles,
        address: first.addressLabel || first.cardLocationLabel || "",
        aboutLines: first.bioLines || [],
        loading: false,
      });
    } catch (error) {
      console.error("[venue] loadVenue failed", error);
      this.setData({ loading: false, error: "加载失败" });
    }
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  copyAddress() {
    if (!this.data.address) return;
    wx.setClipboardData({
      data: this.data.address,
      success: () => wx.showToast({ title: "地址已复制", icon: "none" }),
    });
  },

  openDetail(event) {
    wx.navigateTo({ url: `/pages/detail/detail?id=${event.currentTarget.dataset.id}&lang=${this.lang || "zh"}` });
  },

  openSourceArticle(event) {
    const hash = event.currentTarget.dataset.hash || "";
    const fallbackDetailId = event.currentTarget.dataset.id || "";
    openSourceByHash(hash, this.lang || "zh", { fallbackDetailId });
  },
});
