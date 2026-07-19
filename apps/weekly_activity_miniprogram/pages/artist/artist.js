const { requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { applyLanguageChrome, localizeItems, normalizeLang, text } = require("../../utils/i18n");
const { mergeVenues, mergeCollaborators } = require("../../utils/atlasContract");
const { openSourceByHash } = require("../../utils/sourceAction");
const { normalizeDjDiscoverySectionsForDisplay } = require("../../utils/publicExternalLinks");
const { copyOriginalExternalLink } = require("../../utils/externalLinkAction");
const { socialToLinkItems } = require("../../utils/djLinks");
const { buildNamedPageShare, buildNamedPageTimeline, enableShareMenu } = require("../../utils/share");
const { cityFootprint: computeCityFootprint, normalizeCityName } = require("../../utils/cityFootprint");
const { groupOutlinks } = require("../../utils/groupOutlinks");

const COLUMN_HIGHLIGHT_STORAGE_KEY = "weeklyActivityColumnHighlight:v1";

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

function normalizeRadioPrograms(value, limit = 8) {
  const rows = Array.isArray(value) ? value : [];
  return rows.map((row) => {
    const url = String(row && row.url || "").trim();
    if (!/^https?:\/\//i.test(url)) return null;
    if (row.noHotlink === false || row.openMode === "embedded_media" || /\.(mp3|m4a|aac|wav|flac|ogg|mp4|m3u8)(\?|#|$)/i.test(url)) return null;
    const station = String(row.stationName || row.stationKey || row.platform || "").trim();
    const platform = String(row.platform || "").trim();
    const publishedAt = String(row.publishedAt || "").trim();
    return {
      programId: String(row.programId || row.id || url).trim(),
      title: String(row.title || station || url).trim(),
      url,
      stationName: station,
      platform,
      publishedAt,
      metaLabel: [station, platform, publishedAt].filter(Boolean).join(" · "),
      description: String(row.description || "").trim(),
      sourceUrl: String(row.sourceUrl || "").trim(),
      openMode: "external_original_site",
      noHotlink: true,
      reviewDecision: String(row.reviewDecision || "").trim(),
      reviewReasons: Array.isArray(row.reviewReasons) ? row.reviewReasons.map((item) => String(item || "").trim()).filter(Boolean) : [],
      reviewMatchedTexts: Array.isArray(row.reviewMatchedTexts) ? row.reviewMatchedTexts.map((item) => String(item || "").trim()).filter(Boolean) : [],
    };
  }).filter(Boolean).slice(0, limit);
}

function radioProgramFold(items, expanded) {
  const rows = Array.isArray(items) ? items : [];
  const limit = expanded ? 8 : 3;
  return {
    visibleRadioPrograms: rows.slice(0, limit),
    hiddenRadioProgramCount: Math.max(0, rows.length - limit),
  };
}

function discoveryFold(sections, expanded) {
  const input = Array.isArray(sections) ? sections : [];
  const linkLimit = expanded ? 8 : 3;
  const atomLimit = expanded ? 6 : 0;
  let remainingLinks = linkLimit;
  let hiddenLinkCount = 0;
  let hiddenBioAtomCount = 0;
  const visibleDjDiscovery = [];

  for (const section of input) {
    const links = Array.isArray(section && section.links) ? section.links : [];
    const bioAtoms = Array.isArray(section && section.bioAtoms) ? section.bioAtoms : [];
    const visibleLinks = remainingLinks > 0 ? links.slice(0, remainingLinks) : [];
    remainingLinks -= visibleLinks.length;
    hiddenLinkCount += Math.max(0, links.length - visibleLinks.length);

    const visibleAtoms = expanded && atomLimit > 0 ? bioAtoms.slice(0, atomLimit) : [];
    hiddenBioAtomCount += Math.max(0, bioAtoms.length - visibleAtoms.length);

    if (visibleLinks.length || visibleAtoms.length) {
      visibleDjDiscovery.push({
        ...section,
        links: visibleLinks,
        bioAtoms: visibleAtoms,
      });
    }
  }

  return { visibleDjDiscovery, hiddenDiscoveryCount: hiddenLinkCount + hiddenBioAtomCount };
}

function foldLabel(kind, lang, expanded, count) {
  const n = Number(count || 0);
  if (kind === "radio") {
    if (expanded) return lang === "en" ? "Collapse programs" : "收起节目";
    return lang === "en" ? `Show all programs${n ? ` (${n})` : ""}` : `展开全部节目${n ? `（${n}）` : ""}`;
  }
  if (kind === "outlinks") {
    if (expanded) return lang === "en" ? "Collapse links" : "收起外链";
    return lang === "en" ? `Show all links${n ? ` (${n})` : ""}` : `展开全部外链${n ? `（${n}）` : ""}`;
  }
  if (expanded) return lang === "en" ? "Collapse sources" : "收起资料";
  return lang === "en" ? `Show all sources${n ? ` (${n})` : ""}` : `展开全部资料${n ? `（${n}）` : ""}`;
}

function buildRadioProgramSourceRoute(program, lang) {
  return "/pages/source/source?externalUrl="
    + encodeURIComponent(program.url || "")
    + `&linkType=radio&lang=${encodeURIComponent(lang || "zh")}`
    + `&title=${encodeURIComponent(program.title || "")}`
    + `&meta=${encodeURIComponent(program.metaLabel || "")}`;
}

function normalizeRelatedColumns(value, limit = 4) {
  const rows = Array.isArray(value) ? value : [];
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const columnId = String(row && (row.columnId || row.id || row.cid || row.article_id) || "").trim();
    const title = String(row && (row.title || row.t) || "").trim();
    const summary = String(row && (row.summary || row.s || row.excerpt) || "").trim();
    const publishedAt = String(row && (row.publishedAt || row.p || row.published_at) || "").trim();
    const sourceTitle = String(row && (row.sourceTitle || row.st || row.source_title) || "").trim();
    const sourceRefId = String(row && (row.sourceRefId || row.sr || row.source_ref_id) || "").trim();
    if (!columnId && !title) continue;
    const key = columnId || title.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      columnId,
      title: title || sourceTitle || columnId,
      summary,
      sourceRefId,
      sourceTitle,
      publishedAt,
      metaLabel: [publishedAt.slice(0, 10), sourceTitle].filter(Boolean).join(" · "),
    });
    if (out.length >= limit) break;
  }
  return out;
}

function rememberRelatedColumnFallback(column, lang) {
  const highlight = String(column && (column.columnId || column.id) || "").trim();
  if (!highlight || typeof wx === "undefined" || typeof wx.setStorageSync !== "function") return;
  try {
    wx.setStorageSync(COLUMN_HIGHLIGHT_STORAGE_KEY, {
      highlight,
      lang: lang || "zh",
      createdAt: Date.now(),
    });
  } catch (error) {
    // Best effort only; the column tab also works without a stored highlight.
  }
}

function countLabel(value, suffix) {
  const n = Number(value || 0);
  return Number.isFinite(n) && n > 0 ? `${n}${suffix}` : "";
}

function normalizeRelationTrajectory(value) {
  if (!value || typeof value !== "object") return null;
  const cities = (Array.isArray(value.cities) ? value.cities : []).map((row) => {
    const city = String(row.city || "").trim();
    if (!city) return null;
    return {
      city,
      eventCount: Number(row.eventCount || 0),
      metaLabel: [countLabel(row.eventCount, "场"), row.firstSeenAt && row.lastSeenAt ? `${row.firstSeenAt} - ${row.lastSeenAt}` : ""].filter(Boolean).join(" · "),
    };
  }).filter(Boolean).slice(0, 4);
  const venues = (Array.isArray(value.venues) ? value.venues : []).map((row) => {
    const venueName = String(row.venueName || row.name || row.venueId || "").trim();
    if (!venueName) return null;
    return {
      venueId: String(row.venueId || "").trim(),
      venueName,
      city: String(row.city || "").trim(),
      eventCount: Number(row.eventCount || 0),
      metaLabel: [row.city, countLabel(row.eventCount, "场")].filter(Boolean).join(" · "),
    };
  }).filter(Boolean).slice(0, 6);
  const collaborators = (Array.isArray(value.collaborators) ? value.collaborators : value.relations || []).map((row) => {
    const displayName = String(row.displayName || row.name || row.djId || "").trim();
    if (!displayName) return null;
    return {
      djId: String(row.djId || "").trim(),
      displayName,
      sameEventCount: Number(row.sameEventCount || 0),
      b2bCount: Number(row.b2bCount || 0),
      label: String(row.label || "").trim(),
      metaLabel: [row.label, countLabel(row.sameEventCount, "次同台"), countLabel(row.b2bCount, "次B2B")].filter(Boolean).join(" · "),
    };
  }).filter(Boolean).slice(0, 8);
  const events = (Array.isArray(value.events) ? value.events : []).map((row) => {
    const title = String(row.title || row.eventTitle || row.eventId || "").trim();
    if (!title) return null;
    return {
      eventId: String(row.eventId || "").trim(),
      title,
      sourceRefId: String(row.sourceRefId || "").trim(),
      metaLabel: [row.startsAt, row.timeText, row.venueName, row.city].filter(Boolean).join(" · "),
    };
  }).filter(Boolean).slice(0, 4);
  if (!cities.length && !venues.length && !collaborators.length && !events.length) return null;
  return { cities, venues, collaborators, events };
}

// City footprint: geographic reach computed from the DJ's atlas events via the
// shared util (placeholder drop + English-alias + 市/省 merge). The curated
// trajectory lens only covers ~220 DJs; ~30% of all DJs play 2+ cities, so this
// surfaces the same "cities played" story for the long tail from event data
// already in the DTO. Display-only; shown only when there's no curated trajectory.
function buildCityFootprint(atlasEvents, limit = 6) {
  const fp = computeCityFootprint(atlasEvents);
  return fp.order.slice(0, limit).map((city) => {
    const range = fp.ranges[city] || {};
    const dateLabel = range.first && range.last && range.first !== range.last
      ? `${range.first} - ${range.last}`
      : range.last;
    return {
      city,
      eventCount: fp.counts[city],
      metaLabel: [countLabel(fp.counts[city], "场"), dateLabel].filter(Boolean).join(" · "),
    };
  });
}

Page({
  data: {
    lang: "zh", t: text("sub", "zh"), name: "", loading: true, error: "",
    events: [], bioLines: [], djDiscovery: [], visibleDjDiscovery: [], hiddenDiscoveryCount: 0,
    djDiscoveryExpanded: false, discoveryToggleLabel: "",
    radioPrograms: [], visibleRadioPrograms: [], hiddenRadioProgramCount: 0,
    radioProgramsExpanded: false, radioToggleLabel: "", relationTrajectory: null,
    cityFootprint: [],
    relatedColumns: [],
    djOutlinks: [], visibleDjOutlinks: [], hiddenOutlinkCount: 0,
    outlinksExpanded: false, outlinkToggleLabel: "",
    djOutlinksGrouped: [],
    atlasProfile: null, atlasEvents: [], visibleAtlasEvents: [], cityFilter: "",
    atlasCollaborators: [], atlasVenues: [],
  },

  onLoad(query) {
    enableShareMenu();
    this.name = decodeURIComponent(query.name || "");
    this.subjectId = decodeURIComponent(query.subjectId || "");
    this.lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("artist", this.lang);
    this.setData({ lang: this.lang, t: text("sub", this.lang), name: this.name, subjectId: this.subjectId });
    this.loadArtist();
  },

  onShareAppMessage() {
    return buildNamedPageShare("/pages/artist/artist", this.data.name || this.name, this.lang, this.data.t.relatedEvents, {
      subjectId: this.data.subjectId || this.subjectId || "",
    });
  },
  onShareTimeline() {
    return buildNamedPageTimeline(this.data.name || this.name, this.lang, this.data.t.relatedEvents, {
      subjectId: this.data.subjectId || this.subjectId || "",
    });
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
        const radioPrograms = normalizeRadioPrograms(
          (profile && profile.radioPrograms) || profileResult.radioPrograms || []
        );
        const relatedColumns = normalizeRelatedColumns(
          (profile && profile.relatedColumns) || profileResult.relatedColumns || []
        );
        if (profile) profile.relatedColumns = relatedColumns;
        const relationTrajectory = normalizeRelationTrajectory(
          (profile && profile.relationTrajectory) || profileResult.relationTrajectory
        );
        const djDiscovery = normalizeDjDiscoverySectionsForDisplay([{
          name: displayName,
          links: socialToLinkItems((profile && profile.social) || profileResult.social || {}, { entityName: displayName }),
          bioAtoms: (profile && profile.bioAtoms) || profileResult.bioAtoms || [],
        }], this.lang);
        const discoveryState = discoveryFold(djDiscovery, false);
        const radioState = radioProgramFold(radioPrograms, false);
        const resolvedSubjectId = this.subjectId || profile?.subjectId || profile?.djId || profileResult.subjectId || "";
        if (resolvedSubjectId && !this.subjectId) this.subjectId = resolvedSubjectId;

        // DJ outlinks from accepted candidate sidecar (candidateOnly, safe roles only)
        const djOutlinks = ((profile && profile.externalLinks) || []).filter(
          (lk) => lk && lk.url && lk.role !== "other"
        );
        const OUTLINK_FOLD = 3;
        const visibleDjOutlinks = djOutlinks.slice(0, OUTLINK_FOLD);
        const hiddenOutlinkCount = Math.max(0, djOutlinks.length - OUTLINK_FOLD);
        const djOutlinksGrouped = groupOutlinks(djOutlinks, this.lang);

        // City footprint for the long tail (skip when a curated trajectory already
        // shows cities). Only show when the DJ played 2+ cities — single city is
        // already in the header.
        const cityFootprintAll = relationTrajectory ? [] : buildCityFootprint(atlasEvts);
        const cityFootprint = cityFootprintAll.length >= 2 ? cityFootprintAll : [];

        this.setData({
          atlasProfile: profile,
          subjectId: resolvedSubjectId,
          atlasEvents: atlasEvts || [],
          visibleAtlasEvents: atlasEvts || [],
          cityFilter: "",
          atlasCollaborators: mergedCollaborators,
          atlasVenues: mergedVenues,
          djDiscovery,
          ...discoveryState,
          djDiscoveryExpanded: false,
          discoveryToggleLabel: foldLabel("discovery", this.lang, false, discoveryState.hiddenDiscoveryCount),
          radioPrograms,
          ...radioState,
          radioProgramsExpanded: false,
          radioToggleLabel: foldLabel("radio", this.lang, false, radioState.hiddenRadioProgramCount),
          relatedColumns,
          relationTrajectory,
          cityFootprint,
          similarDjs: (profile && profile.similarDjs) || [],
          djOutlinks,
          visibleDjOutlinks,
          hiddenOutlinkCount,
          outlinksExpanded: false,
          outlinkToggleLabel: foldLabel("outlinks", this.lang, false, hiddenOutlinkCount),
          djOutlinksGrouped,
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
    const atlasQuery = {
      eventLimit: 100, collaboratorLimit: 1500, venueLimit: 500,
    };
    if (this.subjectId) atlasQuery.subjectId = this.subjectId;
    else atlasQuery.name = this.name;
    try {
      const r = await requestApi("/api/v1/weekly/atlas/artist", atlasQuery);
      if (r && r.found) return r;
    } catch (err) {
      console.warn("[artist] atlas/artist unavailable, trying dj-profile", err);
    }
    if (this.subjectId) {
      try {
        const r = await requestApi("/api/v1/weekly/atlas/dj/" + encodeURIComponent(this.subjectId) + "/profile");
        if (r && r.found) return r;
      } catch (err) {
        console.warn("[artist] DJ profile by subjectId unavailable", err);
      }
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

  openOrgInStarmap(e) {
    safeVibrate("light");
    const id = e.currentTarget.dataset.id;
    const name = e.currentTarget.dataset.name;
    if (id) wx.navigateTo({ url: `/pages/atlas-starmap/atlas-starmap?focusId=${encodeURIComponent(id)}&q=${encodeURIComponent(name || "")}` });
  },

  // Tap a city in the footprint to filter this DJ's performance history to that
  // city; tap the active city again to clear. Footprint and history are the same
  // historical events, so the filter is self-consistent.
  onCityFilter(e) {
    safeVibrate("light");
    const city = String(e.currentTarget.dataset.city || "").trim();
    const next = this.data.cityFilter === city ? "" : city;
    const all = this.data.atlasEvents || [];
    const visible = next ? all.filter((ev) => normalizeCityName(ev && ev.city) === next) : all;
    this.setData({ cityFilter: next, visibleAtlasEvents: visible });
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

  toggleDjDiscovery() {
    const expanded = !this.data.djDiscoveryExpanded;
    const state = discoveryFold(this.data.djDiscovery, expanded);
    this.setData({
      ...state,
      djDiscoveryExpanded: expanded,
      discoveryToggleLabel: foldLabel("discovery", this.lang || this.data.lang, expanded, state.hiddenDiscoveryCount),
    });
  },

  toggleRadioPrograms() {
    const expanded = !this.data.radioProgramsExpanded;
    const state = radioProgramFold(this.data.radioPrograms, expanded);
    this.setData({
      ...state,
      radioProgramsExpanded: expanded,
      radioToggleLabel: foldLabel("radio", this.lang || this.data.lang, expanded, state.hiddenRadioProgramCount),
    });
  },

  openRadioProgram(e) {
    safeVibrate("light");
    const idx = Number(e.currentTarget.dataset.index);
    const program = this.data.radioPrograms[idx] || {};
    if (!program.url) return;
    wx.navigateTo({
      url: buildRadioProgramSourceRoute(program, this.lang || "zh"),
      fail: () => {
        const action = copyOriginalExternalLink(program.url, this.lang || "zh", { linkType: "radio" });
        if (!action.ok) wx.showToast({ title: this.data.t.sourceLinkCopied || this.data.t.openOriginal, icon: "none" });
      },
    });
  },

  toggleDjOutlinks() {
    const expanded = !this.data.outlinksExpanded;
    const all = this.data.djOutlinks;
    const FOLD = 3;
    this.setData({
      visibleDjOutlinks: expanded ? all : all.slice(0, FOLD),
      hiddenOutlinkCount: expanded ? 0 : Math.max(0, all.length - FOLD),
      outlinksExpanded: expanded,
      outlinkToggleLabel: foldLabel("outlinks", this.lang || this.data.lang, expanded, Math.max(0, all.length - FOLD)),
    });
  },

  openDjOutlink(e) {
    safeVibrate("light");
    const url = String(e.currentTarget.dataset.url || "").trim();
    if (!url) return;
    // ponytail: copy-link only; no wx.navigateTo for external URLs
    const action = copyOriginalExternalLink(url, this.lang || "zh", { linkType: "outlink" });
    if (!action.ok) wx.showToast({ title: this.data.t.sourceLinkCopied || "已复制链接", icon: "none" });
  },

  openRelatedColumn(e) {
    safeVibrate("light");
    const idx = Number(e.currentTarget.dataset.index);
    const column = this.data.relatedColumns[idx] || {};
    const lang = this.lang || "zh";
    rememberRelatedColumnFallback(column, lang);
    wx.switchTab({
      url: "/pages/column/column",
      fail: () => {
        wx.showToast({
          title: lang === "en" ? "Open Columns from the tab bar" : "请从底部“专栏”进入",
          icon: "none",
        });
      },
    });
  },
});
