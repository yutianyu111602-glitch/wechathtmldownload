const { requestApi, fetchAllCurrentItems } = require("../../utils/api");
const { getClubOverviewsForVenue } = require("../../utils/clubOverviews");
const { atlasEventToWeeklyItem, compactItem } = require("../../utils/format");
const { partitionEventsByDate, mergeResidentDjs } = require("../../utils/atlasContract");
const { applyLanguageChrome, localizeItems, localizedSourceArticles, normalizeLang, text } = require("../../utils/i18n");
const { openSourceByHash, openSourceUrl } = require("../../utils/sourceAction");
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

function eventDedupeKey(item = {}) {
  const title = normalizeEntityKey(item.displayTitle || item.title || item.titleDisplay || "");
  const date = String(item.eventDateStart || item.date || item.dateLabel || item.dateCompact || "").slice(0, 10);
  const venue = normalizeEntityKey(item.venueLabel || item.venueName || item.venue || item.promoter || "");
  const sourceHash = String(item.sourceHash || item.sourceRefId || item.source_ref_id || item.hash || "").trim();
  if (title && date && venue) return `${date}|${venue}|${title}`;
  if (sourceHash) return `source|${sourceHash}`;
  return String(item.id || item.eventId || [title, date, venue].join("|"));
}

function dedupeEvents(items) {
  const out = [];
  const seen = new Set();
  (Array.isArray(items) ? items : []).forEach((item) => {
    const key = eventDedupeKey(item);
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push(item);
  });
  return out;
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

// Scene summary surfaced in the header: a 4308-show venue otherwise reads only its
// few upcoming events. eventCount is the venue's true historical total (from the v2
// subject). Active period is intentionally omitted — venue_events is capped at 200
// (recency-biased), so any derived date span would mislead for high-volume venues.
function buildVenueSummary(profile, lang) {
  const total = Number((profile && profile.eventCount) || 0);
  if (total <= 0) return "";
  return lang === "en" ? `${total} shows total` : `共 ${total} 场演出`;
}

function safeHideLoading() {
  if (typeof wx !== "undefined" && typeof wx.hideLoading === "function") wx.hideLoading();
}

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

function copyLinkFallback(url, title) {
  if (!url || typeof wx === "undefined" || typeof wx.setClipboardData !== "function") return;
  wx.setClipboardData({
    data: url,
    success: () => {
      if (typeof wx.showToast === "function") wx.showToast({ title, icon: "none" });
    },
  });
}

Page({
  data: {
    lang: "zh",
    t: text("sub", "zh"),
    name: "",
    key: "",
    loading: true,
    error: "",
    events: [],
    pastEvents: [],
    sourceArticles: [],
    clubOverviews: [],
    clubOverviewImageFailedIds: [],
    address: "",
    mapLocation: null,
    mapLocationName: "",
    aboutLines: [],
    // Atlas fields
    atlasProfile: null,
    atlasEvents: [],
    atlasResidentDJs: [],
    venueSummary: "",
  },

  onLoad(query) {
    enableShareMenu();
    this.name = decodeURIComponent(query.name || "");
    this.key = decodeURIComponent(query.key || "");
    this.lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("venue", this.lang);
    this.setData({
      lang: this.lang,
      t: text("sub", this.lang),
      name: this.name,
      key: this.key,
      clubOverviews: getClubOverviewsForVenue(this.name, { lang: this.lang }),
      clubOverviewImageFailedIds: [],
    });
    this.loadVenue();
  },

  onShareAppMessage() {
    return buildNamedPageShare("/pages/venue/venue", this.data.name || this.name, this.lang, this.data.t.weeklyEvents, {
      key: this.data.key || this.key || "",
    });
  },

  onShareTimeline() {
    return buildNamedPageTimeline(this.data.name || this.name, this.lang, this.data.t.weeklyEvents, {
      key: this.data.key || this.key || "",
    });
  },

  async loadVenue() {
    let firstPageRendered = false;
    try {
      // Phase 1: Load first page immediately for fast render
      const firstPage = await requestApi("/api/v1/weekly/current", { limit: 200, cursor: 0 });
      const firstPageItems = firstPage.items || [];
      const compactFirst = dedupeEvents(firstPageItems.map(compactItem).filter((item) => venueMatches(item, this.name, this.key)));
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
      const firstParts = partitionEventsByDate(firstEvents);
      this.setData({
        events: firstParts.upcoming,
        pastEvents: firstParts.past,
        sourceArticles: localizedSourceArticles(buildVenueSourceArticles(compactFirst, { includeSingles: true, maxArticles: 30 }), this.lang),
        address: firstArticle.addressLabel || firstArticle.cardLocationLabel || "",
        mapLocation,
        mapLocationName: firstArticle.venueLabel || firstArticle.promoter || "",
        aboutLines: firstArticle.bioLines || [],
        loading: false,
        atlasLoading: true,
        atlasLabel: this.data.t.atlasLoading || "加载历史演出...",
      });
      firstPageRendered = true;

      // Phase 2: Background load full dataset + Atlas
      const [sourceScopeResult, atlasResult] = await Promise.all([
        fetchAllCurrentItems({ lookbackDays: 31 }).then(
          (items) => ({ items, error: null }),
          (error) => ({ items: firstPageItems, error }),
        ),
        this.fetchAtlasVenue(),
      ]);
      if (sourceScopeResult.error) {
        // Background expansion is optional after the first page is visible.
        // Keep the rendered data and still apply any Atlas enrichment.
        console.warn("[venue] background current hydration unavailable", sourceScopeResult.error);
      }
      const sourceScopeItems = sourceScopeResult.items;
      const compactEvents = dedupeEvents(sourceScopeItems.map(compactItem).filter((item) => venueMatches(item, this.name, this.key)));
      const compactSourceEvents = compactEvents;
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
      // Merge atlas (historical) events with the current-window events, then split
      // upcoming vs past so historical shows never inflate the "未来活动" count.
      const atlasMerged = (atlasResult?.events || []).map((ae) => ({
        ...atlasEventToWeeklyItem(ae, { venueName: this.name }),
        eventDateStart: ae.date || "",
      }));
      const titleDateSet = new Set(events.map(eventDedupeKey));
      const filteredAtlas = atlasMerged.filter((ae) => {
        const key = eventDedupeKey(ae);
        if (titleDateSet.has(key)) return false;
        titleDateSet.add(key);
        return true;
      });
      const parts = partitionEventsByDate(dedupeEvents([...events, ...filteredAtlas]));
      const resolvedKey = this.key || atlasResult?.profile?.subjectId || "";
      if (resolvedKey && !this.key) this.key = resolvedKey;
      this.setData({
        events: parts.upcoming,
        pastEvents: parts.past,
        sourceArticles,
        address: first.addressLabel || first.cardLocationLabel || "",
        mapLocation,
        mapLocationName: first.venueLabel || first.promoter || "",
        aboutLines: first.bioLines || [],
        atlasProfile: atlasResult?.profile || null,
        key: resolvedKey,
        atlasResidentDJs: mergeResidentDjs(atlasResult?.residentDJs || []),
        venueSummary: buildVenueSummary(atlasResult?.profile, this.lang),
        loading: false,
        atlasLoading: false,
        atlasLabel: "",
        error: "",
      });
      safeHideLoading();
    } catch (error) {
      console.error("[venue] loadVenue failed", error);
      this.setData(firstPageRendered
        ? { loading: false, atlasLoading: false, atlasLabel: "" }
        : { loading: false, error: this.data.t.loadFailed });
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
      openSourceByHash(sourceHash, this.lang || "zh", { fallbackDetailId: dataset.id || "" });
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

  openClubOverview(event) {
    safeVibrate("light");
    const url = event.currentTarget.dataset.url || "";
    if (!url) return;
    let copied = false;
    const copyOnce = () => {
      if (copied) return;
      copied = true;
      copyLinkFallback(url, this.data.t.sourceLinkCopied || "原文链接已复制");
    };
    const opened = openSourceUrl(url, this.lang || "zh", { fail: copyOnce });
    if (!opened) copyOnce();
  },

  onClubOverviewPosterError(event) {
    const id = event.currentTarget.dataset.id || "";
    if (!id) return;
    const failedIds = new Set(this.data.clubOverviewImageFailedIds || []);
    if (failedIds.has(id)) return;
    failedIds.add(id);
    const clubOverviews = (this.data.clubOverviews || []).map((item) => (
      item.id === id ? { ...item, posterLoadFailed: true } : item
    ));
    this.setData({
      clubOverviewImageFailedIds: Array.from(failedIds),
      clubOverviews,
    });
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
