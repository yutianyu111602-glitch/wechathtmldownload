const { requestApi } = require("../../utils/api");
const { compactItem, dedupeItems } = require("../../utils/format");
const { HAPTIC, createScrollHapticState, nextScrollHaptic, vibrateLight } = require("../../utils/haptics");
const { applyLanguageChrome, compactDate, localizeItems, normalizeLang, text, translateCity, dateDisplay, weekdayLabel } = require("../../utils/i18n");
const { buildPosterPool } = require("../../utils/posterPool");
const { openSourceByHash } = require("../../utils/sourceAction");
const { withListLocationLabels } = require("../../utils/listDisplay");
const { filterItemsByPreviewRange, itemDateBounds, itemMatchesDateKey, normalizeRange } = require("../../utils/datePreview");
const { filterItemsByActiveFilters, filterItemsByCityKey, filterItemsByDateKey, dateKeysForFilter, itemMatchesCityKey, normalizeIsoDate, keyFromDate } = require("../../services/homeFilters");
const { buildIndexShare, buildIndexTimeline, enableShareMenu } = require("../../utils/share");
const { posterFallbackState, posterImageErrorFallback, resolvePosterUrlsForItems } = require("../../utils/cloudPosterUrls");

const LOAD_HINT_SCHEDULE = [
  {
    ms: 1800,
    progress: 12,
    stepKey: "loadingConnecting",
    hintKey: "loadingConnectingHint",
  },
  {
    ms: 5200,
    progress: 16,
    stepKey: "loadingFallback",
    hintKey: "loadingFallbackHint",
  },
  {
    ms: 11000,
    progress: 18,
    stepKey: "loadingStillWaiting",
    hintKey: "loadingStillWaitingHint",
  },
];
const LOAD_RETRY_DELAYS_MS = [1200, 2600, 4200];
const MAX_SILENT_LOAD_RETRIES = LOAD_RETRY_DELAYS_MS.length;
const BUSY_TOAST_COOLDOWN_MS = 2200;
const MIN_BACKGROUND_REFRESH_INTERVAL_MS = 120000;
const FILTER_META_TIMEOUT_MS = 5000;
const POSTER_WARM_LIMIT = 6;

function toIndexListItem(item) {
  if (!item || typeof item !== "object") return item;
  return {
    id: item.id || "",
    sourceHash: item.hasSource === false ? "" : (item.sourceHash || ""),
    coverUrl: item.coverUrl || "",
    posterFileId: item.posterFileId || item.poster_file_id || item.coverFileId || item.cover_file_id || "",
    posterTempUrl: item.posterTempUrl || "",
    displayTitle: item.displayTitle || item.title || "",
    dateLabel: item.dateLabel || "",
    dateRangeLabel: item.dateRangeLabel || item.dateLabel || "",
    dateRangeCompact: item.dateRangeCompact || item.dateCompact || "",
    dateCompact: item.dateCompact || "",
    event_date_start: item.event_date_start || item.dateLabel || "",
    event_date_end: item.event_date_end || "",
    event_date_iso_guesses: Array.isArray(item.event_date_iso_guesses) ? item.event_date_iso_guesses : [],
    post_date: item.post_date || "",
    weekdayLabel: item.weekdayLabel || "",
    isCalendarPreview: Boolean(item.isCalendarPreview),
    isSourceOverview: Boolean(item.isSourceOverview),
    calendarPreviewLabel: item.calendarPreviewLabel || "",
    cardLocationLabel: item.cardLocationLabel || "",
    city_key: item.city_key || "",
    city_keys: Array.isArray(item.city_keys) ? item.city_keys : (item.city_key ? [item.city_key] : []),
    cityLabel: item.cityLabel || "",
    venueLabel: item.venueLabel || item.venue_name || "",
    promoter: item.promoter || item.account || "",
    listLocationLabel: item.listLocationLabel || item.cardLocationLabel || item.cityLabel || "",
    hasStyle: Boolean(item.hasStyle),
    styleLabel: item.styleLabel || "",
    hasLineup: Boolean(item.hasLineup),
    lineupLabel: item.lineupLabel || "",
    lineupItems: Array.isArray(item.lineupItems) ? item.lineupItems : [],
    hasLineupHint: Boolean(item.hasLineupHint),
    lineupHint: item.lineupHint || "",
    hasAddress: Boolean(item.hasAddress),
    hasDescription: Boolean(item.hasDescription),
    hasPrice: Boolean(item.hasPrice),
  };
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

function pushUniqueLimited(list, value, limit = 24) {
  const next = Array.isArray(list) ? list.slice() : [];
  const textValue = String(value || "").trim();
  if (!textValue || next.includes(textValue)) return next;
  next.push(textValue);
  return next.slice(-limit);
}


function buildCityFiltersFallback(items, lang, allCitiesLabel) {
  const bucket = new Map();
  for (const item of items || []) {
    const key = String(item?.city_key || "").trim();
    if (!key || isUnknownValue(key)) continue;
    const rawLabel = String(item?.cityLabel || item?.city || key);
    if (isUnknownValue(rawLabel)) continue;
    const label = translateCity(rawLabel, lang, key);
    const current = bucket.get(key) || { key, label, count: 0 };
    current.count += 1;
    if (!current.label || isUnknownValue(current.label)) current.label = label;
    bucket.set(key, current);
  }
  const rows = Array.from(bucket.values()).sort((a, b) => b.count - a.count || String(a.label).localeCompare(String(b.label)));
  return [{ key: "", label: allCitiesLabel, count: "" }, ...rows.map((row) => ({ key: row.key, label: row.label, count: row.count }))];
}

function dateKeySetFromIndex(payload) {
  const dates = Array.isArray(payload?.dates) ? payload.dates : [];
  const keys = new Set();
  for (const entry of dates) {
    const key = normalizeIsoDate(entry?.date || entry?.key);
    if (key) keys.add(key);
  }
  return keys.size ? keys : null;
}

function buildDateFiltersFallback(items, lang, allDatesLabel, allowedDateKeys = null) {
  const bucket = new Map();
  const allowedKeys = allowedDateKeys && allowedDateKeys.size ? allowedDateKeys : null;
  for (const item of items || []) {
    for (const key of dateKeysForFilter(item)) {
      if (!key || isUnknownValue(key)) continue;
      if (allowedKeys && !allowedKeys.has(key)) continue;
      const current = bucket.get(key) || { key, count: 0 };
      current.count += 1;
      bucket.set(key, current);
    }
  }
  const rows = Array.from(bucket.values()).sort((a, b) => String(a.key).localeCompare(String(b.key)));
  return [{ key: "", label: allDatesLabel, count: "" }, ...rows.map((row) => ({ key: row.key, label: dateDisplay(row.key, lang), fullLabel: row.key, count: row.count }))];
}

function groupItems(items, lang, selectedDate = "") {
  const groups = [];
  const byDate = new Map();
  for (const item of items) {
    const isSourceOverview = Boolean(item.isSourceOverview);
    const key = isSourceOverview
      ? `source-overview:${item.id || groups.length}`
      : (selectedDate && itemMatchesDateKey(item, selectedDate) ? selectedDate : item.dateLabel || "");
    if (!byDate.has(key)) {
      const group = {
        key,
        date: isSourceOverview ? "" : compactDate(key) || item.dateCompact || key,
        weekday: isSourceOverview ? "" : weekdayLabel(key, lang) || item.weekdayLabel || "",
        isSourceOverviewGroup: isSourceOverview,
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
  const saturday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + daysToSaturday);
  const keys = [-1, 0, 1].map((offset) => {
    const date = new Date(saturday);
    date.setDate(saturday.getDate() + offset);
    return keyFromDate(date);
  });
  return keys.find((key) => dateFilters.find((item) => item.key === key)) || "";
}

function withFilterMetaTimeout(promise, label) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject({ error: { code: "FILTER_META_TIMEOUT", label } });
    }, FILTER_META_TIMEOUT_MS);
    promise.then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

function warmPosterImages(items, limit = POSTER_WARM_LIMIT) {
  if (typeof wx === "undefined" || typeof wx.getImageInfo !== "function") return;
  const seen = new Set();
  const posters = (Array.isArray(items) ? items : [])
    .map((item) => String(item?.coverUrl || "").trim())
    .filter((src) => {
      if (!src || seen.has(src)) return false;
      seen.add(src);
      return true;
    })
    .slice(0, limit);
  if (!posters.length) return;
  setTimeout(() => {
    posters.forEach((src) => {
      wx.getImageInfo({ src, success() {}, fail() {} });
    });
  }, 0);
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

function viewStateForItems(items, tab, posterSourceItems, selectedCity, lang, previewRange, selectedDate = "") {
  const rangedItems = filterItemsByPreviewRange(items, previewRange);
  const rangedPosterItems = filterItemsByPreviewRange(posterSourceItems, previewRange);
  const viewItems = withListLocationLabels(viewItemsForTab(rangedItems, tab), selectedCity);
  const broadPosterItems = posterSourceItems && posterSourceItems.length
    ? viewItemsForTab(rangedPosterItems, tab)
    : viewItems;
  return {
    viewItems,
    popularItems: buildPosterPool(viewItems, broadPosterItems, tab),
    groups: groupItems(viewItems, lang, selectedDate),
  };
}

function buildIndexViewData(items, posterSourceItems, activeTab, selectedCity, lang, previewRange, selectedDate = "") {
  const compactItems = Array.isArray(items) ? items : [];
  const compactPosterItems = Array.isArray(posterSourceItems) ? posterSourceItems : [];
  const projectedItems = compactItems.map(toIndexListItem);
  const projectedPosterItems = compactPosterItems.map(toIndexListItem);
  const safeRange = normalizeRange(previewRange);
  return {
    items: projectedItems,
    previewRange: safeRange,
    ...viewStateForItems(projectedItems, activeTab, projectedPosterItems, selectedCity, lang, safeRange, selectedDate),
  };
}

async function resolveIndexViewPosters(viewData) {
  if (!viewData || !Array.isArray(viewData.popularItems) || !viewData.popularItems.length) return viewData;
  const popularItems = await resolvePosterUrlsForItems(viewData.popularItems);
  return {
    ...viewData,
    popularItems,
  };
}

function applyPosterErrorMask(viewData, failedPosterIds) {
  const failed = new Set((Array.isArray(failedPosterIds) ? failedPosterIds : []).map((id) => String(id || "")).filter(Boolean));
  if (!failed.size || !Array.isArray(viewData?.popularItems)) return viewData;
  return {
    ...viewData,
    popularItems: viewData.popularItems.map((item) => {
      const id = String(item?.id || "");
      if (!id || !failed.has(id)) return item;
      return {
        ...item,
        coverUrl: "",
        posterLoadFailed: true,
      };
    }),
  };
}

Page({
  data: {
    lang: "zh",
    t: text("index", "zh"),
    loading: true,
    loadingProgress: 0,
    loadingStep: "连接活动源",
    loadingHint: "请稍等，不用重复点击。",
    cacheNotice: "",
    error: "",
    errorHint: "",
    activeTab: "all",
    previewRange: "all",
    items: [],
    totalItems: 0,
    viewItems: [],
    popularItems: [],
    groups: [],
    cityTitle: "China",
    heroTitle: "本周电音活动查询",
    datePillLabel: "Today",
    cityPillLabel: "China",
    cityFilters: [{ key: "", label: text("index", "zh").allCities }],
    dateFilters: [{ key: "", label: text("index", "zh").allDates }],
    selectedCity: "",
    selectedDate: "",
    draftCity: "",
    draftDate: "",
    showDateModal: false,
    showLocationModal: false,
    posterImageLoadCount: 0,
    posterImageErrorCount: 0,
    posterImageLoadedIds: [],
    posterImageErrorUrls: [],
    posterImageFailedIds: [],
  },
  posterSourceItems: [],
  _fullItems: [],
  feedHapticState: createScrollHapticState(),
  feedTouchHapticState: createScrollHapticState(),
  posterHapticState: createScrollHapticState(),
  lastHapticAt: 0,
  ignoreFeedHapticUntil: 0,
  isLoadingRequest: false,
  pendingLoadOptions: null,
  loadSeq: 0,
  loadingHintTimers: null,
  backgroundRefreshTimer: null,
  backgroundRefreshAttempts: 0,
  retryToastAt: 0,
  lastBackgroundRefreshAt: 0,

  onLoad(query = {}) {
    enableShareMenu();
    const lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    const selectedCity = safeDecode(query.city || "");
    const selectedDate = safeDecode(query.date || "");
    wx.setStorageSync("weeklyActivityLang", lang);
    applyLanguageChrome("index", lang);
    this.setData({
      lang,
      t: text("index", lang),
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

  onUnload() {
    this.clearLoadingHintTimers();
    this.clearBackgroundRefreshTimer();
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

  onFeedTouchStart(event) {
    const touch = event.touches && event.touches[0];
    const y = Number(touch && touch.clientY);
    if (!Number.isFinite(y)) return;
    this.feedTouchHapticState = createScrollHapticState(y, Date.now());
  },

  onFeedTouchMove(event) {
    if (this.data.loading || this.data.error || this.data.totalItems === 0) return;
    const now = Date.now();
    if (now < this.ignoreFeedHapticUntil) return;
    const touch = event.touches && event.touches[0];
    const y = Number(touch && touch.clientY);
    if (!Number.isFinite(y)) return;
    const haptic = nextScrollHaptic(this.feedTouchHapticState, y, now, HAPTIC.feed);
    if (haptic.shouldPulse) vibrateLight();
  },

  onPosterStripScroll(event) {
    const scrollLeft = Number(event.detail?.scrollLeft || 0);
    if (!Number.isFinite(scrollLeft) || this.data.popularItems.length < 2) return;
    const haptic = nextScrollHaptic(this.posterHapticState, scrollLeft, Date.now(), HAPTIC.poster);
    if (haptic.shouldPulse) vibrateLight();
  },

  onPosterImageLoad(event) {
    const id = event.currentTarget?.dataset?.id || "";
    this.setData({
      posterImageLoadCount: Number(this.data.posterImageLoadCount || 0) + 1,
      posterImageLoadedIds: pushUniqueLimited(this.data.posterImageLoadedIds, id),
    });
  },

  async onPosterImageError(event) {
    const id = String(event.currentTarget?.dataset?.id || "").trim();
    const src = event.currentTarget?.dataset?.src || "";
    const target = (this.data.popularItems || []).find((item) => id && String(item?.id || "") === id);
    const fallback = await posterImageErrorFallback(target, src);
    let usedCloudFallback = false;
    let shouldMarkFailed = false;
    const popularItems = (this.data.popularItems || []).map((item) => {
      if (!id || String(item?.id || "") !== id) return item;
      if (fallback) {
        usedCloudFallback = true;
        return {
          ...item,
          ...posterFallbackState(item, fallback),
        };
      }
      shouldMarkFailed = true;
      return {
        ...item,
        coverUrl: "",
        posterLoadFailed: true,
      };
    });
    const failedPosterIds = shouldMarkFailed
      ? pushUniqueLimited(this.data.posterImageFailedIds, id, 64)
      : this.data.posterImageFailedIds;
    this.setData({
      posterImageErrorCount: Number(this.data.posterImageErrorCount || 0) + 1,
      posterImageErrorUrls: pushUniqueLimited(this.data.posterImageErrorUrls, src, 12),
      posterImageFailedIds: failedPosterIds,
      popularItems,
    });
    if (usedCloudFallback) warmPosterImages(popularItems.filter((item) => String(item.id || "") === id), 1);
  },

  onPageScroll(event) {
    if (this.data.loading || this.data.error || this.data.totalItems === 0) return;
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
    let fromCache = false;
    let fromSnapshot = false;
    const allItems = [];
    for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
      const current = await requestApi("/api/v1/weekly/current", {
        cityKey: opts.cityKey !== undefined ? opts.cityKey : this.data.selectedCity,
        date: opts.date !== undefined ? opts.date : this.data.selectedDate,
        lookbackDays: opts.lookbackDays !== undefined ? opts.lookbackDays : 0,
        limit,
        cursor,
      });
      if (current.__fromCache) fromCache = true;
      if (current.__fromSnapshot) fromSnapshot = true;
      const pageItems = current.items || [];
      allItems.push(...pageItems);
      total = Number(current.page?.total || total || allItems.length);
      const loaded = total ? Math.min(allItems.length, total) : allItems.length;
      if (opts.updateProgress !== false) {
        const progress = 22 + Math.min(42, Math.round((loaded / Math.max(total || loaded || 1, 1)) * 42));
        this.setLoadingProgress(progress, `${labels.loadingEvents} ${loaded}/${total || loaded}`, opts.loadSeq);
      }
      const nextCursor = current.page?.nextCursor;
      if (nextCursor === null || nextCursor === undefined || nextCursor === "") break;
      const parsedNext = Number(nextCursor);
      if (!Number.isFinite(parsedNext) || parsedNext <= Number(cursor)) break;
      cursor = parsedNext;
    }
    return { items: allItems, total: total || allItems.length, fromCache, fromSnapshot };
  },

  async loadData(options) {
    const opts = options || {};
    const backgroundRefresh = opts.backgroundRefresh === true;
    if (opts.haptic && !backgroundRefresh) {
      this.lightHaptic();
      this.suppressFeedHaptic();
    }
    if (this.isLoadingRequest) {
      if (backgroundRefresh) {
        return { skipped: true };
      }
      this.pendingLoadOptions = { ...(this.pendingLoadOptions || {}), ...opts, haptic: false };
      this.showBusyToast();
      if (opts.stopPullDownRefresh && wx.stopPullDownRefresh) {
        wx.stopPullDownRefresh();
      }
      return { skipped: true };
    }
    this.isLoadingRequest = true;
    this.pendingLoadOptions = null;
    this.loadSeq = (this.loadSeq || 0) + 1;
    const loadSeq = this.loadSeq;
    const labels = this.data.t;
    this.clearLoadingHintTimers();
    if (!backgroundRefresh) {
      this.clearBackgroundRefreshTimer();
      this.backgroundRefreshAttempts = 0;
      this.setData({
        loading: true,
        loadingProgress: 8,
        loadingStep: labels.loadingStart,
        loadingHint: labels.loadingStartHint,
        cacheNotice: "",
        error: "",
        errorHint: "",
      });
      this.scheduleLoadingHints(labels, loadSeq);
    }
    let retryOptions = null;
    let retryDelay = 0;
    try {
      const selectedCityKey = opts.cityKey !== undefined ? opts.cityKey : this.data.selectedCity;
      const selectedDateKey = opts.date !== undefined ? opts.date : this.data.selectedDate;
      const currentPromise = this.fetchAllCurrentItems(labels, { cityKey: "", date: "", lookbackDays: 0, loadSeq });
      const citiesPromise = withFilterMetaTimeout(requestApi("/api/v1/weekly/cities"), "cities");
      const datesPromise = withFilterMetaTimeout(requestApi("/api/v1/weekly/dates"), "dates");
      const current = await currentPromise;
      this.setLoadingProgress(78, labels.loadingClean, loadSeq, labels.loadingCleanHint);
      const [citiesResult, datesResult] = await Promise.allSettled([citiesPromise, datesPromise]);
      if (loadSeq !== this.loadSeq) return null;
      this.setLoadingProgress(84, labels.loadingClean, loadSeq, labels.loadingCleanHint);
      const lang = this.data.lang;
      const filterMetadataSlow = citiesResult.status !== "fulfilled" || datesResult.status !== "fulfilled";
      const usedCache = Boolean(current.fromCache);
      const usedSnapshot = Boolean(current.fromSnapshot);
      const items = localizeItems(dedupeItems((current.items || []).map(compactItem)), lang);
      this.posterSourceItems = items;
      const filterSourceItems = this.posterSourceItems.length ? this.posterSourceItems : items;
      const cacheNotice = usedCache
        ? labels.loadingCachedNotice
        : usedSnapshot
          ? labels.loadingOfflineNotice
          : (filterMetadataSlow ? labels.loadingFallbackHint : "");
      const cityFilterSourceItems = filterSourceItems;
      const cityFilters = buildCityFiltersFallback(cityFilterSourceItems, lang, this.data.t.allCities);
      const selectedCity = cityFilters.find((item) => item.key === selectedCityKey) || cityFilters[0];
      const resolvedCityKey = selectedCity.key ? selectedCityKey : "";
      const dateFilterSourceItems = resolvedCityKey
        ? filterItemsByCityKey(filterSourceItems, resolvedCityKey)
        : filterSourceItems;
      const dateIndexKeys = datesResult.status === "fulfilled" ? dateKeySetFromIndex(datesResult.value) : null;
      const dateFilters = buildDateFiltersFallback(dateFilterSourceItems, lang, this.data.t.allDates, dateIndexKeys);
      const selectedDate = dateFilters.find((item) => item.key === selectedDateKey) || dateFilters[0];
      const resolvedDateKey = selectedDate.key ? selectedDateKey : "";
      const displayItems = filterItemsByActiveFilters(filterSourceItems, resolvedCityKey, resolvedDateKey);
      const nextViewData = applyPosterErrorMask(buildIndexViewData(
        displayItems,
        filterSourceItems,
        this.data.activeTab,
        resolvedCityKey,
        lang,
        this.data.previewRange,
        resolvedDateKey,
      ), []);
      this.setLoadingProgress(90, labels.loadingClean, loadSeq, labels.loadingCleanHint);
      const resolvedViewData = await resolveIndexViewPosters(nextViewData);
      if (loadSeq !== this.loadSeq) return null;
      const { items: _unused, ...lightViewData } = resolvedViewData;
      this._fullItems = resolvedViewData.items || [];
      this.setData({
        ...lightViewData,
        selectedCity: resolvedCityKey,
        selectedDate: resolvedDateKey,
        draftCity: resolvedCityKey,
        draftDate: resolvedDateKey,
        totalItems: displayItems.length,
        cityFilters,
        dateFilters,
        cityTitle: selectedCity.key ? selectedCity.label : this.data.t.china,
        heroTitle: selectedCity.key ? selectedCity.label : this.data.t.heroTitle,
        cityPillLabel: cleanFilterLabel(selectedCity.label, this.data.t.allCities),
        datePillLabel: selectedDate.label || this.data.t.allDates,
        loadingProgress: 100,
        loadingStep: labels.loadingReady,
        loadingHint: "",
        cacheNotice,
        loading: false,
        posterImageLoadCount: 0,
        posterImageErrorCount: 0,
        posterImageLoadedIds: [],
        posterImageErrorUrls: [],
        posterImageFailedIds: [],
      });
      warmPosterImages(resolvedViewData.popularItems);
      if (usedCache || usedSnapshot) {
        this.scheduleBackgroundRefresh();
      } else {
        this.clearBackgroundRefreshTimer();
        this.backgroundRefreshAttempts = 0;
      }
    } catch (error) {
      if (loadSeq !== this.loadSeq) return null;
      console.error("[weekly] loadData failed", error);
      if (backgroundRefresh) {
        this.scheduleBackgroundRefresh();
        return null;
      }
      const retryCount = Math.max(0, Number(opts.silentRetryCount || 0));
      if (retryCount < MAX_SILENT_LOAD_RETRIES) {
        retryDelay = LOAD_RETRY_DELAYS_MS[retryCount] || LOAD_RETRY_DELAYS_MS[LOAD_RETRY_DELAYS_MS.length - 1];
        retryOptions = { ...opts, haptic: false, stopPullDownRefresh: false, silentRetryCount: retryCount + 1 };
        this.setData({
          loading: true,
          loadingProgress: Math.max(Number(this.data.loadingProgress) || 0, 18),
          loadingStep: labels.loadingRetrying,
          loadingHint: labels.loadingRetryHint,
          error: "",
          errorHint: "",
        });
      } else {
        this.setData({
          loading: false,
          error: this.data.t.loadFailed,
          errorHint: this.data.t.loadFailedHint,
        });
      }
    } finally {
      this.clearLoadingHintTimers();
      if (loadSeq === this.loadSeq) {
        this.isLoadingRequest = false;
      }
      const pending = this.pendingLoadOptions;
      this.pendingLoadOptions = null;
      if (opts.stopPullDownRefresh && wx.stopPullDownRefresh) {
        wx.stopPullDownRefresh();
      }
      if (pending && loadSeq === this.loadSeq) {
        setTimeout(() => this.loadData(pending), 0);
      } else if (retryOptions && loadSeq === this.loadSeq) {
        setTimeout(() => this.loadData(retryOptions), retryDelay);
      }
    }
  },

  scheduleBackgroundRefresh() {
    if (this.backgroundRefreshAttempts >= MAX_SILENT_LOAD_RETRIES) return;
    const now = Date.now();
    if (now - this.lastBackgroundRefreshAt < MIN_BACKGROUND_REFRESH_INTERVAL_MS) return;
    this.clearBackgroundRefreshTimer();
    this.lastBackgroundRefreshAt = now;
    const retryIndex = this.backgroundRefreshAttempts;
    const delay = LOAD_RETRY_DELAYS_MS[retryIndex] || LOAD_RETRY_DELAYS_MS[LOAD_RETRY_DELAYS_MS.length - 1];
    this.backgroundRefreshAttempts += 1;
    this.backgroundRefreshTimer = setTimeout(() => {
      this.backgroundRefreshTimer = null;
      this.loadData({
        haptic: false,
        stopPullDownRefresh: false,
        silentRetryCount: 0,
        backgroundRefresh: true,
      });
    }, delay);
  },

  clearBackgroundRefreshTimer() {
    if (this.backgroundRefreshTimer) {
      clearTimeout(this.backgroundRefreshTimer);
      this.backgroundRefreshTimer = null;
    }
  },

  onPullDownRefresh() {
    this.loadData({ haptic: true, stopPullDownRefresh: true });
  },

  retryLoadData() {
    if (this.isLoadingRequest || this.data.loading) {
      this.showBusyToast();
      return;
    }
    this.loadData({ haptic: true });
  },

  refreshViewItems() {
    const nextViewData = applyPosterErrorMask(buildIndexViewData(
        this._fullItems,
        this.posterSourceItems,
        this.data.activeTab,
        this.data.selectedCity,
        this.data.lang,
        this.data.previewRange,
        this.data.selectedDate,
      ), this.data.posterImageFailedIds);
    resolveIndexViewPosters(nextViewData)
      .then((resolvedViewData) => this.setData(resolvedViewData))
      .catch(() => this.setData(nextViewData));
  },

  setLoadingProgress(progress, step, loadSeq, hint) {
    if (loadSeq && loadSeq !== this.loadSeq) return;
    if (!this.data.loading) return;
    const nextProgress = Math.max(Number(progress) || 0, Number(this.data.loadingProgress) || 0);
    const patch = {
      loadingProgress: Math.min(nextProgress, 100),
      loadingStep: step || this.data.loadingStep,
    };
    if (hint !== undefined) {
      patch.loadingHint = hint;
    }
    this.setData(patch);
  },

  scheduleLoadingHints(labels, loadSeq) {
    this.clearLoadingHintTimers();
    this.loadingHintTimers = LOAD_HINT_SCHEDULE.map((item) => setTimeout(() => {
      this.setLoadingProgress(item.progress, labels[item.stepKey], loadSeq, labels[item.hintKey]);
    }, item.ms));
  },

  clearLoadingHintTimers() {
    const timers = this.loadingHintTimers || [];
    timers.forEach((timer) => clearTimeout(timer));
    this.loadingHintTimers = [];
  },

  showBusyToast() {
    const now = Date.now();
    if (now - this.retryToastAt < BUSY_TOAST_COOLDOWN_MS) return;
    this.retryToastAt = now;
    if (wx.showToast) {
      wx.showToast({
        title: this.data.t.retryBusy,
        icon: "none",
        duration: 1800,
      });
    }
  },

  toggleLang() {
    const lang = this.data.lang === "en" ? "zh" : "en";
    wx.setStorageSync("weeklyActivityLang", lang);
    applyLanguageChrome("index", lang);
    this.setData({ lang, t: text("index", lang) });
    this.loadData();
  },

  setTab(event) {
    const activeTab = event.currentTarget.dataset.tab || "all";
    if (activeTab !== this.data.activeTab) {
      this.lightHaptic(HAPTIC.tabInterval);
      this.suppressFeedHaptic(1400);
    }
    const nextViewData = applyPosterErrorMask(buildIndexViewData(
      this._fullItems,
      this.posterSourceItems,
      activeTab,
      this.data.selectedCity,
      this.data.lang,
      this.data.previewRange,
      this.data.selectedDate,
    ), this.data.posterImageFailedIds);
    this.setData({ activeTab, ...nextViewData });
    resolveIndexViewPosters(nextViewData)
      .then((resolvedViewData) => {
        if (this.data.activeTab === activeTab) this.setData(resolvedViewData);
      })
      .catch(() => {});
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
    this.loadData({ haptic: true, date: key });
  },

  chooseDraftCity(event) {
    const key = event.currentTarget.dataset.key || "";
    this.setData({
      draftCity: key,
      selectedCity: key,
      showLocationModal: false,
    });
    this.loadData({ haptic: true, cityKey: key });
  },

  resetDate() {
    this.setData({
      draftDate: "",
      selectedDate: "",
      showDateModal: false,
    });
    this.loadData({ haptic: true, date: "" });
  },

  resetLocation() {
    this.setData({
      draftCity: "",
      selectedCity: "",
      showLocationModal: false,
    });
    this.loadData({ haptic: true, cityKey: "" });
  },

  chooseThisWeekend() {
    const key = pickWeekendDate(this.data.dateFilters, 0);
    this.setData({
      draftDate: key,
      selectedDate: key,
      showDateModal: false,
    });
    this.loadData({ haptic: true, date: key });
  },

  chooseNextWeekend() {
    const key = pickWeekendDate(this.data.dateFilters, 1);
    this.setData({
      draftDate: key,
      selectedDate: key,
      showDateModal: false,
    });
    this.loadData({ haptic: true, date: key });
  },

  applyDate() {
    const key = this.data.draftDate || "";
    this.setData({
      selectedDate: key,
      showDateModal: false,
    });
    this.loadData({ haptic: true, date: key });
  },

  applyLocation() {
    const key = this.data.draftCity || "";
    this.setData({
      selectedCity: key,
      showLocationModal: false,
    });
    this.loadData({ haptic: true, cityKey: key });
  },

  openDetail(event) {
    vibrateLight("light");
    const id = encodeURIComponent(event.currentTarget.dataset.id || "");
    const lang = encodeURIComponent(this.data.lang || "zh");
    wx.navigateTo({
      url: `/pages/detail/detail?id=${id}&lang=${lang}`,
    });
  },

  openArtist(e) {
    vibrateLight("light");
    const name = e.currentTarget.dataset.name;
    if (name) {
      wx.navigateTo({
        url: `/pages/artist/artist?name=${encodeURIComponent(name)}&lang=${this.data.lang || "zh"}`,
      });
    }
  },

  openMap() {
    vibrateLight("light");
    wx.navigateTo({ url: `/pages/map/map?lang=${this.data.lang}` });
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
