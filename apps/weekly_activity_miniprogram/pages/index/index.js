const { requestApi } = require("../../utils/api");
const { compactDate, compactItem, dedupeItems, weekdayLabel } = require("../../utils/format");
const { HAPTIC, createScrollHapticState, nextScrollHaptic, vibrateLight } = require("../../utils/haptics");
const { buildPosterPool } = require("../../utils/posterPool");
const { openSourceByHash } = require("../../utils/sourceAction");
const { withListLocationLabels } = require("../../utils/listDisplay");
const { buildIndexShare, buildIndexTimeline, enableShareMenu } = require("../../utils/share");

const I18N = {
  zh: {
    lang: "zh",
    langToggle: "EN",
    brandKicker: "坏DJclub",
    heroTitle: "本周电音活动查询",
    tabAll: "全部",
    tabForYou: "信息完整",
    tabNew: "新发布",
    featured: "海报推荐",
    allEvents: "按日期浏览",
    allCities: "全部城市",
    allDates: "全部日期",
    loading: "加载中",
    loadingStart: "连接活动源",
    loadingEvents: "读取活动列表",
    loadingFilters: "同步筛选项",
    loadingClean: "整理重复与冲突",
    loadingReady: "准备完成",
    empty: "这组筛选下暂无活动",
    loadFailed: "加载失败",
    retry: "重新加载",
    dateTitle: "日期",
    locationTitle: "城市",
    thisWeekend: "本周末",
    nextWeekend: "下周末",
    resetToday: "全部日期",
    resetLocation: "全部城市",
    apply: "确定",
    china: "全国",
  },
  en: {
    lang: "en",
    langToggle: "中文",
    brandKicker: "HUAIDJ CLUB",
    heroTitle: "Electronic music events this week",
    tabAll: "All",
    tabForYou: "Complete info",
    tabNew: "New",
    featured: "Poster picks",
    allEvents: "By date",
    allCities: "All cities",
    allDates: "All dates",
    loading: "Loading",
    loadingStart: "Connecting",
    loadingEvents: "Loading events",
    loadingFilters: "Loading filters",
    loadingClean: "Cleaning duplicates",
    loadingReady: "Ready",
    empty: "No events for this filter",
    loadFailed: "Failed to load",
    retry: "Retry",
    dateTitle: "Date",
    locationTitle: "City",
    thisWeekend: "This Weekend",
    nextWeekend: "Next Weekend",
    resetToday: "Reset to Today",
    resetLocation: "Reset to Current Location",
    apply: "Apply",
    china: "China",
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

function isUnknownValue(value) {
  const raw = String(value || "").trim().toLowerCase();
  return raw === "unknown" || raw === "未知城市";
}

function cleanFilterLabel(label, fallback) {
  return String(label || fallback || "").replace(/\s+\d+$/, "");
}

function groupItems(items) {
  const groups = [];
  const byDate = new Map();
  for (const item of items) {
    const key = item.dateLabel || "";
    if (!byDate.has(key)) {
      const group = {
        key,
        date: item.dateCompact || key,
        weekday: item.weekdayLabel || weekdayLabel(key),
        items: [],
      };
      byDate.set(key, group);
      groups.push(group);
    }
    byDate.get(key).items.push(item);
  }
  return groups;
}

function pickWeekendDate(dateFilters, offsetWeeks) {
  const now = new Date();
  const day = now.getDay();
  const daysToSaturday = (6 - day + 7) % 7 + offsetWeeks * 7;
  const target = new Date(now.getFullYear(), now.getMonth(), now.getDate() + daysToSaturday);
  const iso = [
    target.getFullYear(),
    String(target.getMonth() + 1).padStart(2, "0"),
    String(target.getDate()).padStart(2, "0"),
  ].join("-");
  return dateFilters.find((item) => item.key === iso)?.key || "";
}

function viewItemsForTab(items, tab) {
  if (tab === "new") {
    return [...items].sort((a, b) => {
      const postCompare = String(b.post_date || "").localeCompare(String(a.post_date || ""));
      if (postCompare) return postCompare;
      return String(a.dateLabel || "").localeCompare(String(b.dateLabel || ""));
    });
  }
  if (tab === "forYou") {
    const scored = items
      .map((item) => ({
        item,
        score:
          (item.hasStyle ? 4 : 0) +
          (item.hasLineup ? 4 : 0) +
          (item.hasDescription ? 2 : 0) +
          (item.hasPrice ? 1 : 0) +
          (item.hasAddress ? 1 : 0),
      }))
      .filter((entry) => entry.score >= 5)
      .sort((a, b) => b.score - a.score || String(a.dateLabel || "").localeCompare(String(b.dateLabel || "")))
      .map((entry) => entry.item);
    return scored.length ? scored : items;
  }
  return items;
}

function viewStateForItems(items, tab, posterSourceItems, selectedCity) {
  const viewItems = withListLocationLabels(viewItemsForTab(items, tab), selectedCity);
  const broadPosterItems = posterSourceItems && posterSourceItems.length
    ? viewItemsForTab(posterSourceItems, tab)
    : viewItems;
  return {
    viewItems,
    popularItems: buildPosterPool(viewItems, broadPosterItems, tab),
    groups: groupItems(viewItems),
  };
}

Page({
  data: {
    lang: "zh",
    t: I18N.zh,
    loading: true,
    loadingProgress: 0,
    loadingStep: "连接活动源",
    error: "",
    activeTab: "all",
    items: [],
    totalItems: 0,
    viewItems: [],
    popularItems: [],
    groups: [],
    cityTitle: "China",
    heroTitle: "本周电音活动查询",
    datePillLabel: "Today",
    cityPillLabel: "China",
    cityFilters: [{ key: "", label: "全部城市" }],
    dateFilters: [{ key: "", label: "全部日期" }],
    selectedCity: "",
    selectedDate: "",
    draftCity: "",
    draftDate: "",
    showDateModal: false,
    showLocationModal: false,
  },
  posterSourceItems: [],
  feedHapticState: createScrollHapticState(),
  posterHapticState: createScrollHapticState(),
  lastHapticAt: 0,
  ignoreFeedHapticUntil: 0,

  onLoad(query = {}) {
    enableShareMenu();
    const lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    const selectedCity = safeDecode(query.city || "");
    const selectedDate = safeDecode(query.date || "");
    wx.setStorageSync("weeklyActivityLang", lang);
    this.setData({
      lang,
      t: I18N[lang],
      selectedCity,
      selectedDate,
      draftCity: selectedCity,
      draftDate: selectedDate,
    });
    this.loadData();
  },

  onShow() {
    const pendingCity = safeDecode(wx.getStorageSync("weeklyActivityPendingCity") || "");
    if (!pendingCity) return;
    wx.removeStorageSync("weeklyActivityPendingCity");
    if (pendingCity === this.data.selectedCity) return;
    this.setData({
      selectedCity: pendingCity,
      draftCity: pendingCity,
      selectedDate: "",
      draftDate: "",
    });
    this.loadData({ haptic: true });
  },

  onShareAppMessage() {
    return buildIndexShare(this.data);
  },

  onShareTimeline() {
    return buildIndexTimeline(this.data);
  },

  lightHaptic(intervalMs = HAPTIC.refreshInterval) {
    const now = Date.now();
    if (now - this.lastHapticAt < intervalMs) return;
    this.lastHapticAt = now;
    vibrateLight();
  },

  suppressFeedHaptic(ms = 700) {
    this.ignoreFeedHapticUntil = Date.now() + ms;
  },

  onPosterStripScroll(event) {
    const scrollLeft = Number(event.detail?.scrollLeft || 0);
    if (!Number.isFinite(scrollLeft) || this.data.popularItems.length < 2) return;
    const haptic = nextScrollHaptic(this.posterHapticState, scrollLeft, Date.now(), HAPTIC.poster);
    if (haptic.shouldPulse) vibrateLight();
  },

  onPageScroll(event) {
    if (this.data.loading || this.data.error || this.data.items.length === 0) return;
    const now = Date.now();
    if (now < this.ignoreFeedHapticUntil) return;
    const scrollTop = Number(event.scrollTop || 0);
    if (!Number.isFinite(scrollTop)) return;
    const haptic = nextScrollHaptic(this.feedHapticState, scrollTop, now, HAPTIC.feed);
    if (haptic.shouldPulse) vibrateLight();
  },

  async fetchAllCurrentItems(labels, options) {
    const opts = options || {};
    const limit = 100;
    let cursor = 0;
    let total = 0;
    const allItems = [];
    for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
      const current = await requestApi("/api/v1/weekly/current", {
        cityKey: opts.cityKey !== undefined ? opts.cityKey : this.data.selectedCity,
        date: opts.date !== undefined ? opts.date : this.data.selectedDate,
        limit,
        cursor,
      });
      const pageItems = current.items || [];
      allItems.push(...pageItems);
      total = Number(current.page?.total || total || allItems.length);
      const loaded = total ? Math.min(allItems.length, total) : allItems.length;
      if (opts.updateProgress !== false) {
        const progress = 22 + Math.min(42, Math.round((loaded / Math.max(total || loaded || 1, 1)) * 42));
        this.setLoadingProgress(progress, `${labels.loadingEvents} ${loaded}/${total || loaded}`);
      }
      const nextCursor = current.page?.nextCursor;
      if (nextCursor === null || nextCursor === undefined || nextCursor === "") break;
      const parsedNext = Number(nextCursor);
      if (!Number.isFinite(parsedNext) || parsedNext <= Number(cursor)) break;
      cursor = parsedNext;
    }
    return { items: allItems, total: total || allItems.length };
  },

  async loadData(options) {
    const opts = options || {};
    if (opts.haptic) {
      this.lightHaptic();
      this.suppressFeedHaptic();
    }
    const labels = this.data.t;
    this.setData({
      loading: true,
      loadingProgress: 8,
      loadingStep: labels.loadingStart,
      error: "",
    });
    try {
      const hasNarrowFilter = Boolean(this.data.selectedCity || this.data.selectedDate);
      const currentPromise = this.fetchAllCurrentItems(labels);
      const posterSourcePromise = hasNarrowFilter
        ? this.fetchAllCurrentItems(labels, { cityKey: "", date: "", updateProgress: false })
        : currentPromise;
      const citiesPromise = requestApi("/api/v1/weekly/cities").then((result) => {
        this.setLoadingProgress(60, labels.loadingFilters);
        return result;
      });
      const datesPromise = requestApi("/api/v1/weekly/dates").then((result) => {
        this.setLoadingProgress(72, labels.loadingFilters);
        return result;
      });
      const [current, posterSource, cities, dates] = await Promise.all([
        currentPromise,
        posterSourcePromise,
        citiesPromise,
        datesPromise,
      ]);
      this.setLoadingProgress(84, labels.loadingClean);
      const items = dedupeItems((current.items || []).map(compactItem));
      this.posterSourceItems = dedupeItems((posterSource.items || []).map(compactItem));
      const cityFilters = [
        { key: "", label: this.data.t.allCities, count: "" },
        ...(cities.cities || [])
          .filter((city) => !isUnknownValue(city.city_key) && !isUnknownValue(city.city || city.city_key))
          .map((city) => ({
            key: city.city_key,
            label: city.city || city.city_key,
            count: city.item_count || city.count || "",
          })),
      ];
      const dateFilters = [
        { key: "", label: this.data.t.allDates, count: "" },
        ...(dates.dates || [])
          .filter((date) => !isUnknownValue(date.date))
          .map((date) => ({
            key: date.date,
            label: compactDate(date.date),
            fullLabel: date.date,
            count: date.item_count || date.count || "",
          })),
      ];
      const selectedCity = cityFilters.find((item) => item.key === this.data.selectedCity) || cityFilters[0];
      const selectedDate = dateFilters.find((item) => item.key === this.data.selectedDate) || dateFilters[0];
      this.setData({
        items,
        totalItems: current.total || items.length,
        ...viewStateForItems(items, this.data.activeTab, this.posterSourceItems, this.data.selectedCity),
        cityFilters,
        dateFilters,
        cityTitle: selectedCity.key ? selectedCity.label : this.data.t.china,
        heroTitle: selectedCity.key ? selectedCity.label : this.data.t.heroTitle,
        cityPillLabel: cleanFilterLabel(selectedCity.label, this.data.t.allCities),
        datePillLabel: selectedDate.label || this.data.t.allDates,
        loadingProgress: 100,
        loadingStep: labels.loadingReady,
        loading: false,
      });
    } catch (error) {
      console.error("[weekly] loadData failed", error);
      this.setData({
        loading: false,
        error: this.data.t.loadFailed,
      });
    } finally {
      if (opts.stopPullDownRefresh && wx.stopPullDownRefresh) {
        wx.stopPullDownRefresh();
      }
    }
  },

  onPullDownRefresh() {
    this.loadData({ haptic: true, stopPullDownRefresh: true });
  },

  retryLoadData() {
    this.loadData({ haptic: true });
  },

  refreshViewItems() {
    this.setData(viewStateForItems(this.data.items, this.data.activeTab, this.posterSourceItems, this.data.selectedCity));
  },

  setLoadingProgress(progress, step) {
    if (!this.data.loading) return;
    const nextProgress = Math.max(Number(progress) || 0, Number(this.data.loadingProgress) || 0);
    this.setData({
      loadingProgress: Math.min(nextProgress, 100),
      loadingStep: step || this.data.loadingStep,
    });
  },

  toggleLang() {
    const lang = this.data.lang === "en" ? "zh" : "en";
    wx.setStorageSync("weeklyActivityLang", lang);
    this.setData({ lang, t: I18N[lang] });
    this.loadData();
  },

  setTab(event) {
    const activeTab = event.currentTarget.dataset.tab || "all";
    if (activeTab !== this.data.activeTab) {
      this.lightHaptic(HAPTIC.tabInterval);
      this.suppressFeedHaptic();
    }
    this.setData({
      activeTab,
      ...viewStateForItems(this.data.items, activeTab, this.posterSourceItems, this.data.selectedCity),
    });
  },

  onTabItemTap() {
    this.lightHaptic(HAPTIC.tabInterval);
  },

  openDateModal() {
    this.setData({ showDateModal: true, draftDate: this.data.selectedDate });
  },

  openLocationModal() {
    this.setData({ showLocationModal: true, draftCity: this.data.selectedCity });
  },

  closeModal() {
    this.setData({ showDateModal: false, showLocationModal: false });
  },

  noop() {},

  chooseDraftDate(event) {
    const key = event.currentTarget.dataset.key || "";
    this.setData({
      draftDate: key,
      selectedDate: key,
      showDateModal: false,
    });
    this.loadData({ haptic: true });
  },

  chooseDraftCity(event) {
    const key = event.currentTarget.dataset.key || "";
    this.setData({
      draftCity: key,
      selectedCity: key,
      showLocationModal: false,
    });
    this.loadData({ haptic: true });
  },

  resetDate() {
    this.setData({
      draftDate: "",
      selectedDate: "",
      showDateModal: false,
    });
    this.loadData({ haptic: true });
  },

  resetLocation() {
    this.setData({
      draftCity: "",
      selectedCity: "",
      showLocationModal: false,
    });
    this.loadData({ haptic: true });
  },

  chooseThisWeekend() {
    const key = pickWeekendDate(this.data.dateFilters, 0);
    this.setData({
      draftDate: key,
      selectedDate: key,
      showDateModal: false,
    });
    this.loadData({ haptic: true });
  },

  chooseNextWeekend() {
    const key = pickWeekendDate(this.data.dateFilters, 1);
    this.setData({
      draftDate: key,
      selectedDate: key,
      showDateModal: false,
    });
    this.loadData({ haptic: true });
  },

  applyDate() {
    this.setData({
      selectedDate: this.data.draftDate || "",
      showDateModal: false,
    });
    this.loadData({ haptic: true });
  },

  applyLocation() {
    this.setData({
      selectedCity: this.data.draftCity || "",
      showLocationModal: false,
    });
    this.loadData({ haptic: true });
  },

  openDetail(event) {
    const id = encodeURIComponent(event.currentTarget.dataset.id || "");
    const lang = encodeURIComponent(this.data.lang || "zh");
    wx.navigateTo({
      url: `/pages/detail/detail?id=${id}&lang=${lang}`,
    });
  },

  openSource(event) {
    const hash = event.currentTarget.dataset.hash || "";
    const id = event.currentTarget.dataset.id || "";
    openSourceByHash(hash, this.data.lang, { fallbackDetailId: id });
  },

  openPosterSource(event) {
    const hash = event.currentTarget.dataset.hash || "";
    const id = event.currentTarget.dataset.id || "";
    if (hash) {
      openSourceByHash(hash, this.data.lang, { fallbackDetailId: id });
      return;
    }
    if (id) {
      const detailId = encodeURIComponent(id);
      const lang = encodeURIComponent(this.data.lang || "zh");
      wx.navigateTo({
        url: `/pages/detail/detail?id=${detailId}&lang=${lang}`,
      });
    }
  },
});
