const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { buildNamedPageShare, buildNamedPageTimeline, enableShareMenu } = require("../../utils/share");

function includesArtist(item, name) {
  const target = String(name || "").trim().toLowerCase();
  if (!target) return false;
  return (item.lineupItems || []).some((artist) => String(artist).trim().toLowerCase() === target);
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
    bioLines: [],
  },

  onLoad(query) {
    enableShareMenu();
    this.name = decodeURIComponent(query.name || "");
    this.setData({ name: this.name });
    this.loadArtist();
  },

  onShareAppMessage() {
    return buildNamedPageShare("/pages/artist/artist", this.data.name || this.name, "zh", "相关活动");
  },

  onShareTimeline() {
    return buildNamedPageTimeline(this.data.name || this.name, "zh", "相关活动");
  },

  async loadArtist() {
    try {
      const events = (await fetchAllCurrentItems()).map(compactItem).filter((item) => includesArtist(item, this.name));
      this.setData({
        events,
        bioLines: events.find((item) => item.hasBio)?.bioLines || [],
        loading: false,
      });
    } catch (error) {
      console.error("[artist] loadArtist failed", error);
      this.setData({ loading: false, error: "加载失败" });
    }
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  openDetail(event) {
    wx.navigateTo({ url: `/pages/detail/detail?id=${event.currentTarget.dataset.id}` });
  },
});
