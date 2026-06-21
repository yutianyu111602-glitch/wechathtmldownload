const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { applyLanguageChrome, localizeItems, normalizeLang, text } = require("../../utils/i18n");
const { mergeVenues, mergeCollaborators } = require("../../utils/atlasContract");
const { openSourceByHash } = require("../../utils/sourceAction");
const { normalizeDjDiscoverySectionsForDisplay } = require("../../utils/publicExternalLinks");
const { copyOriginalExternalLink } = require("../../utils/externalLinkAction");
const { socialToLinkItems } = require("../../utils/djLinks");
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

function normalizeEventToken(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "");
}

function eventDedupeKey(item = {}) {
  const title = normalizeEventToken(item.displayTitle || item.title || item.titleDisplay || "");
  const date = String(item.eventDateStart || item.date || item.dateLabel || item.dateCompact || "").slice(0, 10);
  const venue = normalizeEventToken(item.venueLabel || item.venueName || item.venue || item.promoter || "");
  const sourceHash = String(item.sourceHash || item.sourceRefId || item.source_ref_id || item.hash || "").trim();
  if (title && date && venue) return `${date}|${venue}|${title}`;
  if (sourceHash) return `source|${sourceHash}`;
  return String(item.id || item.eventId || [title, date, venue].join("|"));
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
    const k = eventDedupeKey(item);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    out.push(item);
  }
  return out;
}

Page({
  data: {
    lang: "zh", t: text("sub", "zh"), name: "", loading: true, error: "",
    events: [], bioLines: [], djDiscovery: [],
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
      const [profileResult, historyItems] = await Promise.all([
        this.fetchDjProfile(),
        fetchAllCurrentItems({ lookbackDays: 45 }),
      ]);

      // Process full DJ profile response
      const events = [];
      const bioLines = [];

      if (profileResult) {
        // Atlas events from the profile. Keep sourceRefId (the `src:` atlas ref)
        // so a tap routes to the atlas-evidence page; preferring the bare hash
        // sent it to the weekly source resolver, which 404s — every history row
        // looked "un-openable".
        const atlasEvts = dedupeEvents((profileResult.events || []).map(e => ({
          eventId: e.eventId, title: e.title, date: e.date,
          venueName: e.venueName, city: e.city,
          sourceRefId: e.sourceRefId || e.sourceHash,
          sourceHash: e.sourceHash || e.sourceRefId,
        })));

        // Merge name/identity variants of the same venue/DJ (old fragmented DB)
        // and recompute counts from the deduped lists.
        const mergedVenues = mergeVenues(profileResult.venues || []);
        const mergedCollaborators = mergeCollaborators(profileResult.collaborators || []);
        const profile = profileResult.profile ? { ...profileResult.profile } : null;
        if (profile) {
          if (mergedVenues.length) profile.venueCount = mergedVenues.length;
          if (mergedCollaborators.length) profile.collaboratorCount = mergedCollaborators.length;
        }

        // Rich card: external media (RA/SoundCloud/Mixcloud/Instagram/…) + verbatim
        // bio atoms (资料来源), reusing the column feature's discovery renderer. Renders
        // only when the API supplies profile.social / profile.bioAtoms (handoff B3).
        const displayName = (profile && profile.displayName) || this.name;
        const djDiscovery = normalizeDjDiscoverySectionsForDisplay([{
          name: displayName,
          links: socialToLinkItems((profile && profile.social) || profileResult.social || {}, { entityName: displayName }),
          bioAtoms: (profile && profile.bioAtoms) || profileResult.bioAtoms || [],
        }], this.lang);

        this.setData({
          atlasProfile: profile,
          atlasEvents: atlasEvts || [],
          atlasCollaborators: mergedCollaborators,
          atlasVenues: mergedVenues,
          djDiscovery,
        });
      }

      // Legacy: filter history items by artist name
      const atlasEventKeys = new Set((this.data.atlasEvents || []).map(eventDedupeKey));
      const compactEvents = dedupeEvents((historyItems || []).map(compactItem))
        .filter(item => includesArtist(item, this.name))
        .filter(item => !atlasEventKeys.has(eventDedupeKey(item)));
      const localizedEvents = localizeItems(compactEvents, this.lang);

      // Merge yuanbao bios from compact events
      for (const e of localizedEvents) {
        if (e.bioLines?.length) {
          for (const b of e.bioLines) {
            if (!bioLines.includes(b)) bioLines.push(b);
          }
        }
      }

      this.setData({
        events: localizedEvents,
        bioLines,
        loading: false,
      });
    } catch (error) {
      console.error("[artist] loadArtist failed", error);
      this.setData({ loading: false, error: this.data.t.loadFailed });
    }
  },

  async fetchDjProfile() {
    // /atlas/artist honours query limits; the /dj-profile route hard-caps venues
    // at 15 / collaborators at 20, which makes a deduped count impossible. Pull
    // the full lists here, fall back to dj-profile by name only if this fails.
    try {
      const r = await requestApi("/api/v1/weekly/atlas/artist", {
        name: this.name, eventLimit: 100, collaboratorLimit: 1500, venueLimit: 500,
      });
      if (r && r.found) return r;
    } catch (err) {
      console.warn("[artist] atlas/artist unavailable, trying dj-profile", err);
    }
    try {
      const r = await requestApi("/api/v1/weekly/atlas/dj-profile/" + encodeURIComponent(this.name));
      return r && r.found ? r : null;
    } catch (err) {
      console.warn("[artist] DJ profile API unavailable", err);
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

  openExternalLink(e) {
    safeVibrate("light");
    const url = e.currentTarget.dataset.url || "";
    // Mini-program can't open arbitrary external links -> copy to clipboard.
    if (url) copyOriginalExternalLink(url, this.lang || "zh");
  },
});
