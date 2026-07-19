const { requestApi } = require("../../utils/api");
const { buildCityGuide } = require("../../utils/cityGuide");
const { compactItem, dedupeItems } = require("../../utils/format");
const { applyLanguageChrome, localizeItems, normalizeLang, text, translateCity } = require("../../utils/i18n");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

async function fetchAllCurrentItems() {
  const allItems = [];
  let cursor = 0;
  for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
    const current = await requestApi("/api/v1/weekly/current", {
      scope: "current",
      cityKey: "",
      date: "",
      lookbackDays: 0,
      limit: 500,
      cursor,
    });
    allItems.push(...(current.items || []));
    const nextCursor = current.page && current.page.nextCursor;
    if (nextCursor === null || nextCursor === undefined || nextCursor === "") break;
    const parsedNext = Number(nextCursor);
    if (!Number.isFinite(parsedNext) || parsedNext <= Number(cursor)) break;
    cursor = parsedNext;
  }
  return allItems;
}

function currentCityFacets(items, upstreamCities, lang) {
  const labels = new Map((Array.isArray(upstreamCities) ? upstreamCities : []).map((city) => [
    String(city.city_key || city.cityKey || city.key || ""),
    city.city || city.label || city.city_key || "",
  ]));
  const bucket = new Map();
  for (const item of Array.isArray(items) ? items : []) {
    const key = String(item.city_key || (item.city_keys || [])[0] || "").trim();
    if (!key) continue;
    const rawCity = labels.get(key) || (Array.isArray(item.city) ? item.city[0] : item.city) || key;
    const current = bucket.get(key) || {
      city_key: key,
      city: rawCity,
      item_count: 0,
    };
    current.item_count += 1;
    bucket.set(key, current);
  }
  return Array.from(bucket.values())
    .map((city) => ({ ...city, displayCity: translateCity(city.city, lang, city.city_key) }))
    .sort((left, right) => right.item_count - left.item_count || left.city_key.localeCompare(right.city_key));
}

Page({
  data: {
    lang: "zh",
    t: text("city", "zh"),
    cities: [],
    guide: buildCityGuide({ cities: [], items: [], selectedCityKey: "", lang: "zh" }),
    selectedCityKey: "",
    loading: true,
    error: "",
  },

  onLoad(query) {
    enableShareMenu();
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    const selectedCityKey = decodeURIComponent((query && query.city) || wx.getStorageSync("weeklyActivityGuideCity") || "");
    applyLanguageChrome("city", lang);
    this.setData({ lang, t: text("city", lang), selectedCityKey });
    this.loadGuide(selectedCityKey);
  },

  _shareTitle() {
    const guide = this.data.guide;
    const city = guide && guide.selectedCityLabel;
    const count = guide && guide.eventCount;
    const lang = this.data.lang;
    if (!city) return lang === "en" ? "HUAIDJ tonight" : "坏DJclub 今晚去哪";
    return lang === "en"
      ? `${city} tonight — HUAIDJ${count ? ` · ${count} events` : ""}`
      : `${city}今晚去哪${count ? `：${count} 个活动线索` : ""}`;
  },

  onShareAppMessage() {
    return buildSimpleShare(this._shareTitle(), "/pages/city/city", {
      lang: this.data.lang,
      city: this.data.selectedCityKey,
    });
  },

  onShareTimeline() {
    return buildSimpleTimeline(this._shareTitle(), {
      lang: this.data.lang,
      city: this.data.selectedCityKey,
    });
  },

  async loadGuide(selectedCityKey) {
    this.setData({ loading: true, error: "" });
    try {
      const [citiesResult, rawItems] = await Promise.all([
        requestApi("/api/v1/weekly/cities", { scope: "current", lookbackDays: 0 }),
        fetchAllCurrentItems(),
      ]);
      const items = localizeItems(dedupeItems(rawItems.map(compactItem)), this.data.lang);
      // Counts come from the exact current item set shown after navigation. The
      // upstream facet payload contributes labels only, so stale package counts
      // can never produce a "131 outside / 13 inside" split again.
      const cities = currentCityFacets(items, citiesResult.cities, this.data.lang);
      this.cityGuideCities = cities;
      this.cityGuideItems = items;
      const guide = buildCityGuide({
        cities,
        items,
        selectedCityKey,
        lang: this.data.lang,
      });
      this.setData({
        cities: guide.cities,
        guide,
        selectedCityKey: guide.selectedCityKey,
        loading: false,
      });
    } catch (err) {
      console.error("[city] loadGuide failed", err);
      this.setData({ loading: false, error: this.data.t.loadFailed });
    }
  },

  refreshGuide(selectedCityKey) {
    const guide = buildCityGuide({
      cities: this.cityGuideCities || [],
      items: this.cityGuideItems || [],
      selectedCityKey,
      lang: this.data.lang,
    });
    this.setData({
      guide,
      cities: guide.cities,
      selectedCityKey: guide.selectedCityKey,
    });
  },

  goBack() {
    wx.switchTab({
      url: "/pages/index/index",
      fail: () => wx.navigateBack({ delta: 1 }),
    });
  },

  openCity(event) {
    safeVibrate("light");
    const key = event.currentTarget.dataset.key || "";
    if (!key) return;
    wx.setStorageSync("weeklyActivityGuideCity", key);
    this.refreshGuide(key);
  },

  clearSelectedCity() {
    safeVibrate("light");
    wx.removeStorageSync("weeklyActivityGuideCity");
    this.refreshGuide("");
  },

  openAllEvents() {
    safeVibrate("light");
    const key = this.data.selectedCityKey || "";
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

  openDecisionDetail(event) {
    safeVibrate("light");
    const id = encodeURIComponent(event.currentTarget.dataset.id || "");
    if (!id) return;
    wx.navigateTo({ url: `/pages/detail/detail?id=${id}&lang=${this.data.lang}` });
  },

  openVenueGuide(event) {
    safeVibrate("light");
    const name = encodeURIComponent(event.currentTarget.dataset.name || "");
    if (!name) return;
    wx.navigateTo({ url: `/pages/venue/venue?name=${name}&lang=${this.data.lang}` });
  },

  openMap() {
    safeVibrate("light");
    wx.navigateTo({ url: `/pages/map/map?lang=${this.data.lang}` });
  },

  openColumn() {
    safeVibrate("light");
    wx.navigateTo({ url: `/pages/column/column?lang=${this.data.lang}` });
  },
});
