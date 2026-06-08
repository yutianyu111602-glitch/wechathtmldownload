const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { applyLanguageChrome, localizeItems, normalizeLang, text } = require("../../utils/i18n");
const { openSourceByHash } = require("../../utils/sourceAction");
const { buildNamedPageShare, buildNamedPageTimeline, enableShareMenu } = require("../../utils/share");

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

function normalizeArtistName(value) {
  return String(value || "").trim().toLowerCase().replace(/^dj\s+/i, "").replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "");
}

function artistNameMatches(value, target) {
  const n = normalizeArtistName(value), nt = normalizeArtistName(target);
  if (!n || !nt) return false;
  if (n === nt) return true;
  const [shorter, longer] = [n, nt].sort((a, b) => a.length - b.length);
  return shorter.length >= 4 && longer.includes(shorter);
}

function includesArtist(item, name) {
  if (!String(name || "").trim()) return false;
  return [...(item.lineupItems || []), ...(item.atlasArtistItems || []).map(a => a.name || a.raw || "")].some(a => artistNameMatches(a, name));
}

async function fetchAllCurrentItems(options = {}) {
  const all = [];
  let cursor = 0;
  for (let i = 0; i < 20; i++) {
    const params = { limit: 500, cursor };
    if (options.lookbackDays) params.lookbackDays = options.lookbackDays;
    const r = await requestApi("/api/v1/weekly/current", params);
    all.push(...(r.items || []));
    const nc = r.page?.nextCursor;
    if (nc === null || nc === undefined || nc === "") break;
    const pn = Number(nc);
    if (!Number.isFinite(pn) || pn <= cursor) break;
    cursor = pn;
  }
  return all;
}

function dedupeEvents(items) {
  const out = [];
  const seen = new Set();
  for (const item of items) {
    const k = String(item.id || item.eventId || [item.displayTitle, item.dateLabel, item.venueLabel].join("|"));
    if (!k || seen.has(k)) continue;
    seen.add(k);
    out.push(item);
  }
  return out;
}

Page({
  data: {
    lang: "zh", t: text("sub", "zh"), name: "", loading: true, error: "",
    events: [], bioLines: [],
    atlasProfile: null, atlasEvents: [], atlasCollaborators: [], atlasVenues: [],
  },

  onLoad(query) {
    enableShareMenu();
    this.name = decodeURIComponent(query.name || "");
    this.lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("artist", this.lang);
    this.setData({ lang: this.lang, t: text("sub", this.lang), name: this.name });
    this.loadArtist();
  },

  onShareAppMessage() {
    return buildNamedPageShare("/pages/artist/artist", this.data.name || this.name, this.lang, this.data.t.relatedEvents);
  },
  onShareTimeline() {
    return buildNamedPageTimeline(this.data.name || this.name, this.lang, this.data.t.relatedEvents);
  },

  async loadArtist() {
    try {
      const [historyItems, atlasResult] = await Promise.all([
        fetchAllCurrentItems({ lookbackDays: 45 }),
        this.fetchAtlasArtist(),
      ]);
      const compactEvents = dedupeEvents(historyItems.map(compactItem))
        .filter(item => includesArtist(item, this.name));
      const events = localizeItems(compactEvents, this.lang);

      // Dedupe atlas events against weekly events by venue+date
      const weeklyKeys = new Set(events.map(e => [e.venueLabel, e.dateLabel].join("|")));
      const dedupedAtlasEvents = (atlasResult?.events || []).filter(
        e => !weeklyKeys.has([e.venueName, (e.date || "").slice(0, 10)].join("|"))
      );
      // Dedupe atlas events internally
      const seenAtlas = new Set();
      const uniqueAtlasEvents = dedupedAtlasEvents.filter(e => {
        const k = [e.title, e.date, e.venueName].join("|");
        if (seenAtlas.has(k)) return false;
        seenAtlas.add(k);
        return true;
      });

      // Dedupe venues and collaborators
      const dedupeById = (arr, key) => {
        const seen = new Set();
        return (arr || []).filter(item => { const k = item[key]; if (seen.has(k)) return false; seen.add(k); return true; });
      };

      this.setData({
        events, bioLines: events.find(item => item.hasBio)?.bioLines || [],
        atlasProfile: atlasResult?.profile || null,
        atlasEvents: uniqueAtlasEvents || [],
        atlasCollaborators: dedupeById(atlasResult?.collaborators, 'djId') || [],
        atlasVenues: dedupeById(atlasResult?.venues, 'venueName') || [],
        loading: false,
      });
    } catch (error) {
      console.error("[artist] loadArtist failed", error);
      this.setData({ loading: false, error: this.data.t.loadFailed });
    }
  },

  async fetchAtlasArtist() {
    try {
      const r = await requestApi("/api/v1/weekly/atlas/artist", { name: this.name, eventLimit: 50, collaboratorLimit: 15, venueLimit: 10 });
      return r.found ? r : null;
    } catch (err) {
      console.warn("[artist] Atlas API unavailable", err);
      return null;
    }
  },

  goBack() { wx.navigateBack({ delta: 1 }); },

  openDetail(e) {
    safeVibrate("light");
    wx.navigateTo({ url: `/pages/detail/detail?id=${e.currentTarget.dataset.id}&lang=${this.lang || "zh"}` });
  },

  openVenue(e) {
    safeVibrate("light");
    const venue = e.currentTarget.dataset.venue;
    if (venue) wx.navigateTo({ url: `/pages/venue/venue?name=${encodeURIComponent(venue)}&lang=${this.lang || "zh"}` });
  },

  openArtist(e) {
    safeVibrate("light");
    const name = e.currentTarget.dataset.name;
    if (name) wx.navigateTo({ url: `/pages/artist/artist?name=${encodeURIComponent(name)}&lang=${this.lang || "zh"}` });
  },

  openInterview() {
    safeVibrate("light");
    const name = this.data.atlasProfile?.displayName || this.data.name || this.name || "";
    const city = this.data.atlasProfile?.city || "";
    try {
      wx.setStorageSync("atlasDjInterviewSeed:v1", { djName: name, city, lang: this.lang || "zh" });
    } catch (err) {
      console.warn("[artist] failed to seed interview form", err);
    }
    wx.switchTab({
      url: "/pages/interview/interview",
      fail: () => wx.reLaunch({ url: "/pages/interview/interview" }),
    });
  },

  openAtlasEventSource(e) {
    safeVibrate("light");
    const hash = e.currentTarget.dataset.sourceHash || "";
    if (hash) openSourceByHash(hash, this.lang || "zh");
  },
});
