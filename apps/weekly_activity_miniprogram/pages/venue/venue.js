const { requestApi } = require("../../utils/api");
const { atlasEventToWeeklyItem, compactItem } = require("../../utils/format");
const { applyLanguageChrome, localizeItems, localizedSourceArticles, normalizeLang, text } = require("../../utils/i18n");
const { openSourceByHash } = require("../../utils/sourceAction");
const { buildVenueSourceArticles } = require("../../utils/sourceArticles");
const { buildNamedPageShare, buildNamedPageTimeline, enableShareMenu } = require("../../utils/share");

function normalizeEntityKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "");
}

function fuzzyEntityMatch(value, target) {
  const raw = String(value || "").trim().toLowerCase();
  const rawTarget = String(target || "").trim().toLowerCase();
  const normalized = normalizeEntityKey(value);
  const normalizedTarget = normalizeEntityKey(target);
  if (!normalized || !normalizedTarget) return false;
  if (normalized === normalizedTarget) return true;
  if (raw && rawTarget && (raw.includes(rawTarget) || rawTarget.includes(raw))) return true;
  const [shorter, longer] = [normalized, normalizedTarget].sort((a, b) => a.length - b.length);
  return shorter.length >= 4 && longer.includes(shorter);
}

function venueMatches(item, name, key) {
  const targetKey = normalizeEntityKey(key);
  const itemKeys = [
    item.organizerKey,
    item.organizer_key,
    item.clubProfile?.organizerKey,
    item.club_profile?.organizer_key,
  ].map(normalizeEntityKey).filter(Boolean);
  if (targetKey && itemKeys.includes(targetKey)) return true;

  const target = String(name || "").trim();
  if (!target) return false;
  return [item.venueLabel, item.promoter, item.account, item.cardLocationLabel, item.clubProfile?.displayName]
    .filter(Boolean)
    .some((value) => fuzzyEntityMatch(value, target));
}

function safeHideLoading() {
  if (typeof wx !== "undefined" && typeof wx.hideLoading === "function") wx.hideLoading();
}

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

async function fetchAllCurrentItems(options = {}) {
  const allItems = [];
  let cursor = 0;
  for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
    const params = { limit: 500, cursor };
    if (options.lookbackDays) params.lookbackDays = options.lookbackDays;
    const current = await requestApi("/api/v1/weekly/current", params);
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
    lang: "zh",
    t: text("sub", "zh"),
    name: "",
    loading: true,
    error: "",
    events: [],
    sourceArticles: [],
    address: "",
    mapLocation: null,
    mapLocationName: "",
    aboutLines: [],
    // Atlas fields
    atlasProfile: null,
    atlasEvents: [],
    atlasResidentDJs: [],
  },

  onLoad(query) {
    enableShareMenu();
    this.name = decodeURIComponent(query.name || "");
    this.key = decodeURIComponent(query.key || "");
    this.lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("venue", this.lang);
    this.setData({ lang: this.lang, t: text("sub", this.lang), name: this.name });
    this.loadVenue();
  },

  onShareAppMessage() {
    return buildNamedPageShare("/pages/venue/venue", this.data.name || this.name, this.lang, this.data.t.weeklyEvents);
  },

  onShareTimeline() {
    return buildNamedPageTimeline(this.data.name || this.name, this.lang, this.data.t.weeklyEvents);
  },

  async loadVenue() {
    try {
      // Phase 1: Load first page immediately for fast render
      const firstPage = await requestApi("/api/v1/weekly/current", { limit: 200, cursor: 0 });
      const firstPageItems = firstPage.items || [];
      const compactFirst = firstPageItems.map(compactItem).filter((item) => venueMatches(item, this.name, this.key));
      const firstEvents = localizeItems(compactFirst, this.lang);
      const firstArticle = firstEvents[0] || {};
      let mapLocation = null;
      if (firstArticle.mapLocation) {
        const lat = Number(firstArticle.mapLocation.latitude);
        const lng = Number(firstArticle.mapLocation.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng) && lat !== 0 && lng !== 0) {
          mapLocation = { latitude: lat, longitude: lng };
        }
      }
      this.setData({
        events: firstEvents,
        sourceArticles: localizedSourceArticles(buildVenueSourceArticles(compactFirst, { includeSingles: true, maxArticles: 30 }), this.lang),
        address: firstArticle.addressLabel || firstArticle.cardLocationLabel || "",
        mapLocation,
        mapLocationName: firstArticle.venueLabel || firstArticle.promoter || "",
        aboutLines: firstArticle.bioLines || [],
        loading: false,
        atlasLoading: true,
        atlasLabel: this.data.t.atlasLoading || "加载历史演出...",
      });

      // Phase 2: Background load full dataset + Atlas
      const [sourceScopeItems, atlasResult] = await Promise.all([
        fetchAllCurrentItems({ lookbackDays: 31 }),
        this.fetchAtlasVenue(),
      ]);
      const compactEvents = sourceScopeItems.map(compactItem).filter((item) => venueMatches(item, this.name, this.key));
      const compactSourceEvents = sourceScopeItems.map(compactItem).filter((item) => venueMatches(item, this.name, this.key));
      const events = localizeItems(compactEvents, this.lang);
      const atlasSourceEvents = (atlasResult?.events || []).map((event) => atlasEventToWeeklyItem(event, { venueName: this.name }));
      const sourceArticles = localizedSourceArticles(
        buildVenueSourceArticles([...(compactSourceEvents.length ? compactSourceEvents : compactEvents), ...atlasSourceEvents], {
          includeSingles: true,
          maxArticles: 50,
        }),
        this.lang,
      );
      const first = events[0] || {};
      mapLocation = null;
      if (first.mapLocation) {
        const lat = Number(first.mapLocation.latitude);
        const lng = Number(first.mapLocation.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng) && lat !== 0 && lng !== 0) {
          mapLocation = { latitude: lat, longitude: lng };
        }
      }
      // Merge atlas (historical) events into the main list, deduplicating by title+date
      const atlasMerged = (atlasResult?.events || []).map((ae) => ({
        ...atlasEventToWeeklyItem(ae, { venueName: this.name }),
        eventDateStart: ae.date || "",
      }));
      const titleDateSet = new Set(events.map(e => `${e.displayTitle || ''}|${e.dateLabel || ''}`));
      const filteredAtlas = atlasMerged.filter(ae => {
        const key = `${ae.displayTitle}|${ae.dateLabel}`;
        if (titleDateSet.has(key)) return false;
        titleDateSet.add(key);
        return true;
      });
      const mergedEvents = [...events, ...filteredAtlas].sort((a, b) => {
        const da = a.eventDateStart || a.dateLabel || '';
        const db = b.eventDateStart || b.dateLabel || '';
        if (da > db) return -1;
        if (da < db) return 1;
        return 0;
      });
      this.setData({
        events: mergedEvents,
        sourceArticles,
        address: first.addressLabel || first.cardLocationLabel || "",
        mapLocation,
        mapLocationName: first.venueLabel || first.promoter || "",
        aboutLines: first.bioLines || [],
        atlasProfile: atlasResult?.profile || null,
        atlasResidentDJs: atlasResult?.residentDJs || [],
        loading: false,
      });
      safeHideLoading();
    } catch (error) {
      console.error("[venue] loadVenue failed", error);
      this.setData({ loading: false, error: this.data.t.loadFailed });
      safeHideLoading();
    }
  },

  async fetchAtlasVenue() {
    try {
      const result = await requestApi("/api/v1/weekly/atlas/venue", {
        name: this.name,
        eventLimit: 50,
      });
      return result.found ? result : null;
    } catch (err) {
      console.warn("[venue] Atlas API unavailable", err);
      return null;
    }
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

  handleAddressTap() {
    if (!this.data.address) return;
    const loc = this.data.mapLocation;
    if (loc && typeof wx.openLocation === "function") {
      wx.openLocation({
        latitude: loc.latitude,
        longitude: loc.longitude,
        name: this.data.mapLocationName || "",
        address: this.data.address,
        scale: 16,
        fail: () => this.copyAddress(),
      });
      return;
    }
    this.copyAddress();
  },

  copyAddress() {
    if (!this.data.address) return;
    wx.setClipboardData({
      data: this.data.address,
      success: () => wx.showToast({ title: this.data.t.addressCopied, icon: "none" }),
    });
  },

  openDetail(event) {
    safeVibrate("light");
    const dataset = event.currentTarget.dataset || {};
    const isAtlasEvent = dataset.isAtlas === true || dataset.isAtlas === "true";
    const sourceHash = dataset.sourceHash || "";
    if (isAtlasEvent && sourceHash) {
      openSourceByHash(sourceHash, this.lang || "zh");
      return;
    }
    wx.navigateTo({ url: `/pages/detail/detail?id=${dataset.id}&lang=${this.lang || "zh"}` });
  },

  openSourceArticle(event) {
    safeVibrate("light");
    const hash = event.currentTarget.dataset.hash || "";
    const fallbackDetailId = event.currentTarget.dataset.id || "";
    openSourceByHash(hash, this.lang || "zh", { fallbackDetailId });
  },

  openArtist(e) {
    safeVibrate("light");
    const name = e.currentTarget.dataset.name;
    if (name) wx.navigateTo({ url: `/pages/artist/artist?name=${encodeURIComponent(name)}&lang=${this.lang || "zh"}` });
  },

  openVenue(e) {
    safeVibrate("light");
    const venue = e.currentTarget.dataset.venue;
    if (venue) wx.navigateTo({ url: `/pages/venue/venue?name=${encodeURIComponent(venue)}&lang=${this.lang || "zh"}` });
  },
});
