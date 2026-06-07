function first(value, fallback = "") {
  return Array.isArray(value) ? value[0] || fallback : value || fallback;
}

function joinList(value, fallback = "") {
  if (!Array.isArray(value) || value.length === 0) return fallback;
  return value.filter(Boolean).join(" / ");
}

function isPlainObject(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function isMeaningfulValue(value) {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.some(isMeaningfulValue);
  if (isPlainObject(value)) return Object.values(value).some(isMeaningfulValue);
  return true;
}

function meaningfulArray(value) {
  if (!isMeaningfulValue(value)) return [];
  const raw = Array.isArray(value)
    ? value
    : (typeof value === "string" ? value.split(/[\/,，、|｜]/) : [value]);
  return raw.map((item) => (typeof item === "string" ? item.trim() : item)).filter(isMeaningfulValue);
}

function firstMeaningful(...values) {
  for (const value of values) {
    if (!isMeaningfulValue(value)) continue;
    if (Array.isArray(value)) return meaningfulArray(value);
    return value;
  }
  return "";
}

function mergeNonEmpty(...sources) {
  const output = {};
  for (const source of sources) {
    if (!isPlainObject(source)) continue;
    for (const [key, value] of Object.entries(source)) {
      if (!isMeaningfulValue(value)) continue;
      if (isPlainObject(value) && isPlainObject(output[key])) {
        output[key] = mergeNonEmpty(output[key], value);
      } else if (Array.isArray(value)) {
        const arrayValue = meaningfulArray(value);
        if (arrayValue.length) output[key] = arrayValue;
      } else {
        output[key] = value;
      }
    }
  }
  return output;
}

function canonicalizeItemFields(rawItem = {}) {
  const item = mergeNonEmpty(rawItem);
  const venue = meaningfulArray(firstMeaningful(item.venue, item.venues, item.venue_names));
  const city = meaningfulArray(firstMeaningful(item.city, item.cities, item.city_name, item.cityLabel));
  const lineup = meaningfulArray(firstMeaningful(
    item.lineup_artists,
    item.lineupItems,
    item.lineup_items,
    item.artist_names,
    item.artists,
    item.lineup,
  ));
  const sourceRefId = String(firstMeaningful(item.sourceRefId, item.source_ref_id, item.source_id) || "").trim();
  const sourceHash = String(firstMeaningful(
    item.sourceHash,
    item.source_hash,
    sourceRefId,
    item.source_action?.url_hash,
    item.source_article?.url_hash,
  ) || "").trim();
  const sourceTitle = firstMeaningful(item.sourceTitle, item.source_title, item.source_article?.title);
  const sourceAccountName = firstMeaningful(
    item.sourceAccountName,
    item.source_account_name,
    item.source_account,
    item.source_article?.account_name,
  );
  const sourcePublishedAt = firstMeaningful(
    item.sourcePublishedAt,
    item.source_published_at,
    item.source_article?.published_at,
    item.postDate,
    item.post_date,
  );
  const sourceAction = sourceHash
    ? mergeNonEmpty({ url_hash: sourceHash, available: true }, item.source_action || {})
    : item.source_action;
  const sourceArticle = sourceHash
    ? mergeNonEmpty({
        url_hash: sourceHash,
        title: sourceTitle,
        account_name: sourceAccountName,
        published_at: sourcePublishedAt,
      }, item.source_article || {})
    : item.source_article;

  return mergeNonEmpty(item, {
    title: firstMeaningful(item.title, item.displayTitle, item.display_title, item.title_display, item.title_original),
    display_title: firstMeaningful(item.display_title, item.displayTitle, item.title_display),
    title_display: firstMeaningful(item.title_display, item.displayTitle, item.display_title),
    event_date_start: firstMeaningful(item.event_date_start, item.eventDateStart, item.date, item.dateLabel, item.starts_at),
    city,
    city_key: firstMeaningful(item.city_key, item.cityKey),
    venue,
    venue_name: firstMeaningful(item.venue_name, item.venueLabel, item.venue_label, venue[0]),
    address: firstMeaningful(item.address, item.addressLabel, item.venue_address),
    address_full: firstMeaningful(item.address_full, item.addressFull, item.full_address),
    poster_file_id: firstMeaningful(item.poster_file_id, item.posterFileId, item.cover_file_id, item.coverFileId),
    poster_url: firstMeaningful(item.poster_url, item.posterUrl, item.flyer_url, item.cover_image_url, item.cover_url, item.raw_cover_url, item.coverUrl),
    lineup_artists: lineup,
    sourceHash,
    source_hash: sourceHash,
    sourceRefId: sourceRefId || (sourceHash.startsWith("src:") ? sourceHash : ""),
    source_ref_id: sourceRefId || (sourceHash.startsWith("src:") ? sourceHash : ""),
    sourceTitle,
    source_title: sourceTitle,
    sourceAccountName,
    source_account_name: sourceAccountName,
    sourcePublishedAt,
    source_published_at: sourcePublishedAt,
    event_date_end: firstMeaningful(item.event_date_end, item.eventDateEnd, item.ends_at),
    source_action: sourceAction,
    source_article: sourceArticle,
  });
}

function atlasEventToWeeklyItem(event = {}, options = {}) {
  const venueName = firstMeaningful(options.venueName, event.venueName, event.venue_name);
  const djName = firstMeaningful(event.djName, event.dj_name, event.displayName, event.artistName);
  const sourceRefId = firstMeaningful(event.sourceRefId, event.source_ref_id, event.sourceHash, event.source_hash);
  const sourceHash = firstMeaningful(event.sourceHash, event.source_hash);
  const date = firstMeaningful(event.date, event.eventDateStart, event.startsAt, event.starts_at);
  const title = firstMeaningful(event.title, event.eventTitle, event.event_title, `${venueName || "Atlas"} ${date || ""}`.trim());
  const id = firstMeaningful(event.eventId, event.event_id, `atlas-${String(title || "").replace(/\s+/g, "-")}-${date || ""}`);
  return canonicalizeItemFields({
    id,
    event_id: id,
    displayTitle: title,
    title,
    dateLabel: date,
    event_date_start: date,
    eventDateStart: date,
    lineupLabel: djName,
    lineup_artists: djName ? [djName] : [],
    venueLabel: venueName,
    venue_name: venueName,
    sourceRefId,
    source_ref_id: sourceRefId,
    sourceHash: sourceHash || sourceRefId,
    source_hash: sourceHash || sourceRefId,
    sourceTitle: event.sourceTitle,
    source_title: event.sourceTitle,
    sourceAccountName: event.sourceAccountName,
    source_account_name: event.sourceAccountName,
    sourcePublishedAt: event.sourcePublishedAt,
    source_published_at: event.sourcePublishedAt,
    isAtlasEvent: true,
  });
}

const LINEUP_PHRASE_RE = /(成员|创意|主理|呈现|你的身体|关于|一种|方式|系统|邀请|活动|本周|舞池|俱乐部|公众号|二维码|扫码|购票|票价|报名|厂牌|旗下|阵容|时间|地点|地址|日期|门票|weekly|lineup|presents?|pres\.|recordings|events)/i;
const DISPLAY_URL_RE = /https?:\/\/|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=|from=appmsg|#imgIndex=/i;
const TIME_CONDITIONAL_FREE_RE = /(?:\b[0-2]?\d\s*(?:am|pm)|[0-2]?\d[:：][0-5]\d|凌晨\s*[0-9]{1,2}\s*点(?:半)?)\s*(?:后|之后|以后|前|之前|以前)\s*(?:免费入场|免票入场|免票|free\s*entry)/gi;
const SINGLE_DIGIT_PRICE_RE = /^(?:(?:¥|￥|RMB\s*|CNY\s*)\s*[0-9](?:\.0+)?|[0-9](?:\.0+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny))$/i;
const FREE_ENTRY_RE = /(?:免费入场|免票入场|免票|free\s*entry)/i;
const TICKETING_LABEL_RE = /(预售|早鸟|双人|单人|现场|门票|票价|学生|全价|入场|presale|pre-sale|advance|door|onsite|on\s*site|at\s*door|tickets?|enter)/i;
const TICKETING_TIER_RE = /(预售|早鸟|双人|单人|现场|门票|票价|学生|全价|入场|presale|pre-sale|advance|door|onsite|on\s*site|at\s*door|tickets?|enter)[ \t\u00a0\u3000]*[:：/]?[ \t\u00a0\u3000]*(?:¥|￥|RMB[ \t\u00a0\u3000]*|CNY[ \t\u00a0\u3000]*)?[ \t\u00a0\u3000]*\d+(?:\.\d+)?[ \t\u00a0\u3000]*(?:元|¥|￥|rmb|RMB|CNY|cny)?/gi;
const VISIBLE_AMOUNT_RE = /(?:¥|￥|RMB\s*|CNY\s*)?\s*\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)?/i;
const QR_ONLY_TICKETING_RE = /(芋圆|yuyuan|小程序码|二维码|扫码|购票链接|点击购票|click\s+for\s+tickets?)/i;
const DRINK_SPECIAL_RE = /(金汤力|啤酒|酒水|特调|鸡尾酒|杯|shot|drink|drinks|bottle|套餐|放送)/i;
const TICKETING_CURRENCY_RE = /¥|￥|元|\brmb\b|\bcny\b/i;
const TITLE_STOP_TOKENS = new Set([
  "club",
  "event",
  "events",
  "lineup",
  "party",
  "pres",
  "presented",
  "presents",
  "preview",
  "room",
  "support",
  "weekly",
]);
const CHINESE_TITLE_STOP_TOKENS = new Set(["活动", "派对", "预告", "阵容", "周末", "本周", "今晚", "今夜"]);
const TITLE_BODY_MARKER_RE = /(票务信息|预售票|早鸟票|全价票|双人票|单人票|现场票|点击购票|购票链接|现场周边|周边售卖|海报设计|感谢摄影师|感谢大家|短暂休整|本次巡演签售|ticketing|tickets?|click\s+for\s+tickets?)/i;
const TITLE_STATION_RE = /\s+(上海|深圳|广州|厦门|北京|杭州|成都|重庆|南京|西安|天津|长沙|武汉|广州|佛山|大理)站[:：]/;
const TITLE_MAX_CHARS = 64;

function compactDate(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return raw;
  return `${match[2]}.${match[3]}`;
}

function isoDate(value) {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function dateRangeForItem(item = {}) {
  const guessValues = Array.isArray(item.event_date_iso_guesses)
    ? item.event_date_iso_guesses.map(isoDate).filter(Boolean)
    : [];
  const start = isoDate(firstMeaningful(
    item.event_date_start,
    item.eventDateStart,
    item.dateLabel,
    item.event_date_iso_guess,
    guessValues[0],
  ));
  const end = isoDate(firstMeaningful(
    item.event_date_end,
    item.eventDateEnd,
    guessValues[guessValues.length - 1],
    start,
  ));
  return {
    start,
    end: end && start && end >= start ? end : start,
  };
}

function compactDateRange(start, end) {
  const safeStart = isoDate(start);
  const safeEnd = isoDate(end);
  if (!safeStart) return "";
  if (safeEnd && safeEnd !== safeStart) return `${compactDate(safeStart)}-${compactDate(safeEnd)}`;
  return compactDate(safeStart);
}

function weekdayLabel(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return days[date.getDay()] || "";
}

function weekdayRangeLabel(start, end) {
  const safeStart = isoDate(start);
  const safeEnd = isoDate(end);
  if (!safeStart) return "";
  const startLabel = weekdayLabel(safeStart);
  if (safeEnd && safeEnd !== safeStart) return `${startLabel}-${weekdayLabel(safeEnd)}`;
  return startLabel;
}

function qualityFlags(item = {}) {
  const source = firstMeaningful(item.quality_flags, item.qualityFlags, item.quality_flag);
  return (Array.isArray(source) ? source : [source]).map((value) => String(value || "").trim()).filter(Boolean);
}

function isCalendarPreviewItem(item = {}) {
  const flags = qualityFlags(item).map((value) => value.toLowerCase());
  return (
    flags.includes("calendar_preview") ||
    item.is_calendar_preview === true ||
    item.isCalendarPreview === true ||
    item.content_type === "calendar_preview" ||
    item.contentType === "calendar_preview"
  );
}

const { VERIFIED_ADDRESS_BOOK } = require("./addressBook");
const { VERIFIED_MAP_LOCATION_BOOK } = require("./mapLocationBook");
const { STYLE_RULES, NON_ARTIST_LINEUP_NAMES, TRUSTED_TIME_SOURCES } = require("./styleRules");

function sourceOverviewTitleCandidates(item = {}) {
  const sourceArticle = item.source_article || item.sourceArticle || {};
  return [
    sourceArticle.title,
    sourceArticle.title_display,
    sourceArticle.display_title,
    sourceArticle.original_title,
    item.source_title,
    item.sourceTitle,
    item.source_article_title,
    item.sourceArticleTitle,
    item.original_article_title,
    item.originalArticleTitle,
    item.article_title,
    item.articleTitle,
    item.title_original,
    item.titleOriginal,
    item.title_display,
    item.display_title,
    item.title,
  ].map((value) => String(value || "").replace(/\s+/g, " ").trim()).filter(Boolean);
}

function originalArticleTitle(item = {}) {
  return sourceOverviewTitleCandidates(item)[0] || stripEmoji(item.title) || "Untitled";
}

function isSourceOverviewTitle(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return false;
  const lower = text.toLowerCase();
  if (/\b(?:weekly|monthly)\s+(?:preview|calendar|schedule|guide)\b/.test(lower)) return true;
  return (
    /(?:本周|这周|今周|本月|这个月|当月)\s*(?:活动)?\s*(?:一览|预告|预览|安排|日程|指南|汇总|合集)/.test(text) ||
    /(?:\d{1,2}|[一二三四五六七八九十冬腊正]+)\s*月\s*(?:活动)?\s*(?:一览|预告|预览|安排|日程|指南|汇总|合集)/.test(text)
  );
}

function isSourceOverviewItem(item = {}) {
  return sourceOverviewTitleCandidates(item).some(isSourceOverviewTitle);
}

function isAggregateChildItem(item = {}) {
  return item.aggregation_child === true
    || item.aggregationChild === true
    || String(item.id || item.event_id || item.article_id || "").trim().startsWith("agg-child-");
}

function stripEmoji(value) {
  return String(value || "").replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, "").trim();
}

function isDisplayUrlLine(value) {
  return DISPLAY_URL_RE.test(String(value || ""));
}

function stripLeadingDateWords(value) {
  return String(value || "")
    .replace(/^\s*[「【\[]?\s*(今晚|今夜|本周(?:[一二三四五六日天]|末)?|周末)\s*[」】\]]?\s*/i, "")
    .replace(/^\s*(\d{1,2})[./-](\d{1,2})(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*/i, "")
    .replace(/^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*/, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
}

function charLength(value) {
  return Array.from(String(value || "")).length;
}

function trimChars(value, maxChars) {
  const chars = Array.from(String(value || ""));
  if (chars.length <= maxChars) return String(value || "");
  return chars.slice(0, maxChars).join("").replace(/\s*[｜|·:：,，\-–—、/]+$/g, "").trim();
}

function removeEntityPrefix(title, item) {
  const candidates = candidateNames(item).map(normalizeName).filter(Boolean);
  const parts = String(title || "").split(/[｜|]/).map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) return title;
  const firstPart = normalizeName(parts[0]);
  if (candidates.some((candidate) => firstPart === candidate || candidate.includes(firstPart) || firstPart.includes(candidate))) {
    return parts.slice(1).join(" / ").trim();
  }
  return title;
}

function stripEntityMentionPrefix(title, item) {
  return String(title || "").replace(/^[@＠]\s*([A-Za-z0-9_.\-\s]{2,32})\s+/, (match, handle) => {
    const normalizedHandle = normalizeName(handle);
    if (!normalizedHandle) return match;
    const candidates = candidateNames(item).map(normalizeName).filter(Boolean);
    const isEntityHandle = candidates.some((candidate) =>
      candidate.includes(normalizedHandle) || normalizedHandle.includes(candidate),
    );
    return isEntityHandle ? "" : match;
  }).trim();
}

function isEntityOnlyTitle(title, item) {
  const normalizedTitle = normalizeName(title);
  if (!normalizedTitle) return true;
  const candidates = candidateNames(item).map(normalizeName).filter(Boolean);
  return candidates.some((candidate) => {
    if (!candidate) return false;
    if (normalizedTitle === candidate) return true;
    if (normalizedTitle.length <= 6 && candidate.includes(normalizedTitle)) return true;
    return candidate.length <= 6 && normalizedTitle.includes(candidate);
  });
}

function cutAtMatch(value, re, minIndex = 8) {
  const match = String(value || "").match(re);
  if (!match || typeof match.index !== "number" || match.index < minIndex) return String(value || "");
  return String(value || "").slice(0, match.index).trim();
}

function compactLongTitle(value) {
  let output = String(value || "").replace(/\s+/g, " ").trim();
  if (!output) return "";

  const cancelledWorkMatch = output.match(/^(【本场活动取消】)\s*(?:曾经，?我们把)?\s*(《[^》]{2,42}》)/);
  if (cancelledWorkMatch) {
    output = `${cancelledWorkMatch[1]}${cancelledWorkMatch[2]}`;
  }

  const tourMatch = output.match(/^(.{4,90}?巡演)(?:\s|$)/);
  if (tourMatch && charLength(output) > TITLE_MAX_CHARS && charLength(output) - charLength(tourMatch[1]) > 12) {
    output = tourMatch[1].trim();
  }

  output = cutAtMatch(output, TITLE_BODY_MARKER_RE, 6);
  output = cutAtMatch(output, TITLE_STATION_RE, 10);
  output = cutAtMatch(output, /\s+\d{1,2}[./-]\d{1,2}(?:\s*\([^)]+\))?(?:\s|$)/, 8);

  if (charLength(output) > TITLE_MAX_CHARS) {
    const firstClause = output.split(/[。！？!?；;]/).map((part) => part.trim()).find((part) => charLength(part) >= 8);
    if (firstClause && charLength(firstClause) < charLength(output)) output = firstClause;
  }

  return trimChars(output, TITLE_MAX_CHARS);
}

function cleanTitleCandidate(value, item) {
  let cleaned = stripEmoji(value)
    .replace(/\s+/g, " ")
    .trim();
  cleaned = stripLeadingDateWords(cleaned);
  cleaned = removeEntityPrefix(cleaned, item);
  cleaned = stripEntityMentionPrefix(cleaned, item);
  cleaned = cleaned
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .replace(/\s*[｜|]\s*\d{1,2}\s*月\s*\d{1,2}\s*日?.*$/i, "")
    .replace(/\s+\d{1,2}[./-]\d{1,2}.*$/i, "")
    .trim();
  cleaned = compactLongTitle(cleaned);
  if (!cleaned || isEntityOnlyTitle(cleaned, item)) return "";
  return cleaned;
}

function displayTitle(item) {
  const candidates = [
    item.title_display,
    item.display_title,
    item.title,
    item.title_original,
  ];
  for (const candidate of candidates) {
    const cleaned = cleanTitleCandidate(candidate, item);
    if (cleaned) return cleaned;
  }
  return cleanTitleCandidate(stripEmoji(item.title), { ...item, venue_name: "", venue: [], account: "", promoter: "" }) ||
    stripEmoji(item.title) ||
    "Untitled";
}

function apiBaseUrl() {
  try {
    if (typeof getApp !== "function") return "";
    const cloud = getApp()?.globalData?.cloud || {};
    if (cloud.useMock) return String(cloud.mockBaseUrl || "").replace(/\/$/, "");
    return String(cloud.publicBaseUrl || "").replace(/\/$/, "");
  } catch {
    return "";
  }
}

function appCloudConfig() {
  try {
    if (typeof getApp !== "function") return {};
    return getApp()?.globalData?.cloud || {};
  } catch {
    return {};
  }
}

function normalizePosterSourceUrl(value) {
  const raw = String(value || "")
    .trim()
    .replace(/&amp;/g, "&")
    .replace(/#.*$/, "");
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    if (parsed.hostname === "mmbiz.qpic.cn" && parsed.protocol === "http:") {
      parsed.protocol = "https:";
    }
    return parsed.toString();
  } catch {
    return raw;
  }
}

function isDirectTencentPosterUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && parsed.hostname === "mmbiz.qpic.cn";
  } catch {
    return false;
  }
}

function isPosterProxyUrl(value) {
  return /\/api\/v1\/weekly\/poster\//.test(String(value || ""));
}

function isInternalPosterFileId(value) {
  const text = String(value || "").trim().toLowerCase();
  return Boolean(text) && (
    text.startsWith("cloud://")
    || text.startsWith("cloudbase://")
    || text.startsWith("wxfile://")
  );
}

function posterFileId(item = {}) {
  return String(firstMeaningful(
    item.poster_file_id,
    item.posterFileId,
    item.cover_file_id,
    item.coverFileId,
  ) || "").trim();
}

function posterSourceCandidates(item = {}) {
  return [
    item.poster_url,
    item.posterUrl,
    item.flyer_url,
    item.cover_image_url,
    item.cover_url,
    item.raw_cover_url,
    item.coverUrl,
  ];
}

function firstPosterSourceUrl(item, predicate) {
  for (const candidate of posterSourceCandidates(item)) {
    const url = normalizePosterSourceUrl(candidate);
    if (url && predicate(url)) return url;
  }
  return "";
}

function posterSuppressed(item = {}) {
  return item.poster_suppressed === true
    || item.posterSuppressed === true
    || item.main_poster_suppressed === true
    || item.mainPosterSuppressed === true;
}

function posterUrl(item) {
  if (posterSuppressed(item) || isAggregateChildItem(item)) return "";
  const internalPosterFileId = posterFileId(item);
  if (isInternalPosterFileId(internalPosterFileId)) return internalPosterFileId;
  const cloud = appCloudConfig();
  const directTencentSourceUrl = firstPosterSourceUrl(item, isDirectTencentPosterUrl);
  if (cloud.posterUseRawSourceFirst !== false) {
    if (directTencentSourceUrl) return directTencentSourceUrl;
    const nonProxySourceUrl = firstPosterSourceUrl(item, (url) => !isPosterProxyUrl(url));
    return nonProxySourceUrl;
  }
  const sourceUrl = firstPosterSourceUrl(item, (url) => Boolean(url));
  const baseUrl = apiBaseUrl();
  if (baseUrl && item.id) return `${baseUrl}/api/v1/weekly/poster/${encodeURIComponent(item.id)}`;
  return sourceUrl;
}

function normalizeName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "");
}

function normalizeDedupePart(value) {
  return normalizeName(stripLeadingDateWords(stripEmoji(value)))
    .replace(/[^\w\u4e00-\u9fff]/g, "")
    .trim();
}

function dateKey(item) {
  return String(item.dateLabel || item.event_date_start || item.event_date_iso_guess || first(item.event_date_iso_guesses, "") || "").trim();
}

function cityKey(item) {
  return normalizeDedupePart(item.cityLabel || first(item.city, item.city_key || first(item.city_keys, "")));
}

function venueKey(item) {
  return normalizeDedupePart(
    item.venueLabel || item.venue_name || first(item.venue, "") || item.promoter || item.account,
  );
}

function organizerKeyForItem(item) {
  return (
    normalizeDedupePart(item.organizerKey || item.organizer_key || item.club_profile?.organizer_key) ||
    venueKey(item) ||
    normalizeDedupePart(item.promoter || item.account || item.source_account_name)
  );
}

function sourceHash(item) {
  // Try explicit fields first, then extract from item ID (e.g., "jar:47476d2c96fa61a1:schedule:")
  const explicit = String(firstMeaningful(
    item.sourceHash,
    item.source_hash,
    item.sourceRefId,
    item.source_ref_id,
    item.source_action?.url_hash,
    item.source_article?.url_hash,
  ) || "").trim();
  if (explicit) return explicit;
  const id = String(item.id || "").trim();
  const match = id.match(/[a-f0-9]{16,32}/i);
  return match ? match[0] : "";
}

function coverKey(item) {
  return String(firstMeaningful(item.poster_file_id, item.posterFileId, item.cover_file_id, item.coverFileId, item.poster_url, item.posterUrl, item.flyer_url, item.cover_image_url, item.cover_url, item.raw_cover_url, item.coverUrl) || "")
    .trim()
    .toLowerCase()
    .replace(/\?.*$/, "");
}

function duplicateScopeKey(item) {
  return [dateKey(item), cityKey(item), venueKey(item)].join("|");
}

function titleFingerprint(item) {
  const rawTitle = item.displayTitle || item.title_display || item.display_title || item.title || "";
  let raw = stripLeadingDateWords(stripEmoji(rawTitle));
  raw = raw
    .replace(/\d{4}[./-]\d{1,2}[./-]\d{1,2}/g, "")
    .replace(/\d{1,2}[./-]\d{1,2}/g, "")
    .replace(/\d{1,2}\s*月\s*\d{1,2}\s*日?/g, "")
    .replace(/周[一二三四五六日天]|星期[一二三四五六日天]|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?/gi, "")
    .replace(/\b(room|support|pres|presents|presented|weekly|party|event|events|lineup|preview)\b/gi, "")
    .replace(/(本周|周末|今晚|今夜|活动|预告|呈现|来袭|就在|预热派对|专场|厂牌|派对)/g, "");

  for (const candidate of [
    item.venueLabel,
    item.venue_name,
    first(item.venue, ""),
    item.promoter,
    item.account,
    first(item.city, ""),
  ]) {
    const normalizedCandidate = normalizeDedupePart(candidate);
    if (normalizedCandidate.length >= 3) {
      raw = normalizeDedupePart(raw).replace(new RegExp(normalizedCandidate, "g"), "");
    }
  }

  const fingerprint = normalizeDedupePart(raw);
  if (fingerprint.length < 6) return "";
  return fingerprint;
}

function titleDateTokens(item) {
  const values = [
    displayTitle(item),
    item.title,
    item.title_original,
    item.title_display,
    item.display_title,
  ];
  const tokens = new Set();
  const patterns = [
    /(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)/g,
    /(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?/g,
  ];
  for (const value of values) {
    const text = String(value || "");
    for (const pattern of patterns) {
      pattern.lastIndex = 0;
      let match;
      while ((match = pattern.exec(text))) {
        const month = Number.parseInt(match[1], 10);
        const day = Number.parseInt(match[2], 10);
        if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
          tokens.add(`${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`);
        }
      }
    }
  }
  return tokens;
}

function conflictingTitleDates(left, right) {
  const leftDates = titleDateTokens(left);
  const rightDates = titleDateTokens(right);
  if (!leftDates.size || !rightDates.size) return false;
  for (const date of leftDates) {
    if (rightDates.has(date)) return false;
  }
  return true;
}

function addressKey(item) {
  return normalizeDedupePart(item.address_full || item.address || "");
}

function sameAddress(left, right) {
  const leftAddress = addressKey(left);
  const rightAddress = addressKey(right);
  return Boolean(leftAddress && rightAddress && leftAddress === rightAddress);
}

function trustedTimeKey(item) {
  const source = String(item.event_time_source || item.running_hours_source || "").trim().toLowerCase();
  if (!TRUSTED_TIME_SOURCES.includes(source)) return "";
  return normalizeDedupePart(item.event_time_text || item.running_hours_text || "");
}

function sameTrustedTime(left, right) {
  const leftTime = trustedTimeKey(left);
  const rightTime = trustedTimeKey(right);
  return Boolean(leftTime && rightTime && leftTime === rightTime);
}

function ownerKeys(item) {
  const sourceArticle = item.source_article && typeof item.source_article === "object" ? item.source_article : {};
  return [
    item.promoter,
    item.account_key,
    item.account,
    item.source_account_name,
    sourceArticle.account_name,
  ]
    .map((value) => normalizeDedupePart(value))
    .filter((value) => value.length >= 3);
}

function sameEventOwner(left, right) {
  const rightOwners = new Set(ownerKeys(right));
  return ownerKeys(left).some((owner) => rightOwners.has(owner));
}

function venueScopeMatches(left, right) {
  const leftVenue = venueKey(left);
  const rightVenue = venueKey(right);
  if (leftVenue && rightVenue && leftVenue === rightVenue) return true;
  if (sameAddress(left, right)) return true;
  if (leftVenue && rightVenue) {
    const [shorter, longer] = [leftVenue, rightVenue].sort((a, b) => a.length - b.length);
    if (shorter.length >= 4 && longer.includes(shorter) && sameEventOwner(left, right)) return true;
  }
  return false;
}

function titleAnchorTokens(item) {
  let text = String(displayTitle(item) || item.title || "").toLowerCase();
  text = text
    .replace(/\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日?/g, " ")
    .replace(/周[一二三四五六日天]|星期[一二三四五六日天]|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?/gi, " ");
  for (const candidate of [item.venueLabel, item.venue_name, first(item.venue, ""), item.promoter, item.account, first(item.city, "")]) {
    const raw = String(candidate || "").toLowerCase();
    if (normalizeDedupePart(raw).length >= 3) text = text.replace(raw, " ");
  }

  const tokens = new Set();
  for (const token of text.match(/[a-z0-9][a-z0-9'&.+-]{2,}/gi) || []) {
    const cleaned = token.toLowerCase().replace(/[^a-z0-9]+/g, "");
    if (cleaned.length >= 4 && !TITLE_STOP_TOKENS.has(cleaned)) tokens.add(`a:${cleaned}`);
  }
  for (const chunk of text.match(/[\u4e00-\u9fff]{2,}/g) || []) {
    const cleaned = normalizeDedupePart(chunk);
    if (cleaned.length >= 4 && !CHINESE_TITLE_STOP_TOKENS.has(cleaned)) tokens.add(`c:${cleaned}`);
    if (cleaned.length >= 5) {
      for (const size of [4, 5, 6]) {
        if (cleaned.length < size) continue;
        for (let index = 0; index <= cleaned.length - size; index += 1) {
          const token = cleaned.slice(index, index + size);
          if (!CHINESE_TITLE_STOP_TOKENS.has(token)) tokens.add(`c:${token}`);
        }
      }
    }
  }
  return tokens;
}

function sharedTitleAnchor(left, right) {
  const rightTokens = titleAnchorTokens(right);
  return [...titleAnchorTokens(left)].some((token) => {
    if (!rightTokens.has(token)) return false;
    if (token.startsWith("a:")) return token.slice(2).length >= 4;
    return token.startsWith("c:") && token.slice(2).length >= 4 && !CHINESE_TITLE_STOP_TOKENS.has(token.slice(2));
  });
}

function bigrams(value) {
  const text = String(value || "");
  const grams = new Set();
  if (text.length < 2) {
    if (text) grams.add(text);
    return grams;
  }
  for (let index = 0; index < text.length - 1; index += 1) {
    grams.add(text.slice(index, index + 2));
  }
  return grams;
}

function overlapRatio(left, right) {
  if (!left || !right) return 0;
  if (left === right) return 1;
  if (left.length >= 8 && right.length >= 8 && (left.includes(right) || right.includes(left))) return 1;
  const leftGrams = bigrams(left);
  const rightGrams = bigrams(right);
  const denominator = Math.min(leftGrams.size, rightGrams.size);
  if (!denominator) return 0;
  let overlap = 0;
  for (const gram of leftGrams) {
    if (rightGrams.has(gram)) overlap += 1;
  }
  return overlap / denominator;
}

function titleSimilarity(left, right) {
  return overlapRatio(titleFingerprint(left), titleFingerprint(right));
}

function areLikelyDuplicateItems(left, right) {
  const leftDate = dateKey(left);
  const rightDate = dateKey(right);
  const leftCity = cityKey(left);
  const rightCity = cityKey(right);
  if (!leftDate || leftDate !== rightDate || !leftCity || leftCity !== rightCity) return false;
  if (!venueScopeMatches(left, right)) return false;
  if (conflictingTitleDates(left, right)) return false;
  const similarity = titleSimilarity(left, right);
  const leftSource = sourceHash(left);
  const rightSource = sourceHash(right);
  const leftCover = coverKey(left);
  const rightCover = coverKey(right);
  if (leftCover && leftCover === rightCover && similarity >= 0.5) return true;
  if (leftSource && leftSource === rightSource && similarity >= 0.5) return true;
  if (dedupeKeyForItem(left) === dedupeKeyForItem(right)) return true;
  if (similarity >= 0.86) return true;

  const timeMatches = sameTrustedTime(left, right);
  const addressMatches = sameAddress(left, right);
  const ownerMatches = sameEventOwner(left, right);
  const anchorMatches = sharedTitleAnchor(left, right);
  if (timeMatches && addressMatches && similarity >= 0.3) return true;
  if (timeMatches && (similarity >= 0.42 || anchorMatches)) return true;
  if (addressMatches && similarity >= 0.65) return true;
  if ((addressMatches || ownerMatches) && similarity >= 0.55) return true;
  if (anchorMatches && (addressMatches || ownerMatches || similarity >= 0.25)) return true;
  return false;
}

function sourceLineup(item) {
  return Array.isArray(item.lineup_artists) && item.lineup_artists.length > 0
    ? item.lineup_artists
    : item.lineup;
}

function hasRawLineup(item) {
  return Array.isArray(sourceLineup(item)) && sourceLineup(item).some((name) => String(name || "").trim());
}

function isTrustedTimeSource(item) {
  const source = String(item.event_time_source || item.running_hours_source || "")
    .trim()
    .toLowerCase();
  return TRUSTED_TIME_SOURCES.includes(source);
}

function isSuspiciousLineupName(value) {
  const raw = stripEmoji(value);
  const normalized = normalizeName(raw);
  if (!normalized) return true;
  if (NON_ARTIST_LINEUP_NAMES.includes(normalized)) return true;
  if (/^在\s*/.test(raw) || /^如[A-Za-z]/.test(raw) || /^如[\u4e00-\u9fff]/.test(raw)) return true;
  if (/^(而是|关于|你的身体|本周|活动|时间|地点|地址|阵容)/.test(raw)) return true;
  if (LINEUP_PHRASE_RE.test(raw)) return true;
  if (raw.length > 32) return true;
  if (/[\n\r]/.test(raw)) return true;
  return false;
}

function normalizeStyleSignal(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[＿_]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function directStyleSignals(item) {
  const rawSignals = [
    ...(Array.isArray(item.music_styles) ? item.music_styles : []),
    ...(Array.isArray(item.musicStyles) ? item.musicStyles : []),
    ...(Array.isArray(item.style_tags) ? item.style_tags : []),
    ...(Array.isArray(item.genres) ? item.genres : []),
  ].filter(Boolean);
  return rawSignals.flatMap((value) =>
    String(value || "")
      .split(/[\/,，、;；|｜]+/)
      .map((part) => part.trim())
      .filter(Boolean),
  );
}

function inferMusicStyles(item) {
  // 1) LLM+OCR extracted styles — map through STYLE_RULES, keep unmatched as-is
  const rawSignals = directStyleSignals(item);
  const llmSignals = rawSignals.map(normalizeStyleSignal).filter(Boolean);
  const labels = [];
  const matchedIndices = new Set();

  for (const rule of STYLE_RULES) {
    const matched = rule.aliases.some((alias) => {
      const na = normalizeStyleSignal(alias);
      return llmSignals.some((signal, idx) => {
        if (signal === na || signal === normalizeStyleSignal(rule.label)) {
          matchedIndices.add(idx);
          return true;
        }
        return false;
      });
    });
    if (matched && !labels.includes(rule.label)) labels.push(rule.label);
    if (labels.length >= 6) break;
  }

  // Keep unmatched LLM signals (may be niche/underground genres not in STYLE_RULES)
  for (let i = 0; i < rawSignals.length && labels.length < 6; i++) {
    const raw = String(rawSignals[i] || "").trim();
    if (!matchedIndices.has(i) && raw && !labels.some(l => normalizeStyleSignal(l) === normalizeStyleSignal(raw))) {
      labels.push(raw);
    }
  }

  return labels.slice(0, 6);
}

function candidateNames(item) {
  const signals = itemTextSignals(item).map(normalizeName).filter(Boolean);
  const addressBookAliases = VERIFIED_ADDRESS_BOOK
    .filter((entry) => entry.keys.some((key) => signals.some((signal) => signal.includes(normalizeName(key)))))
    .flatMap((entry) => entry.keys);
  return [
    item.promoter,
    item.account,
    item.address,
    item.address_full,
    item.venue_name,
    ...(Array.isArray(item.venue) ? item.venue : []),
    ...(Array.isArray(item.city) ? item.city : []),
    ...addressBookAliases,
  ].filter(Boolean);
}

function isSameEntity(value, candidate) {
  const normalizedValue = normalizeName(value);
  const normalizedCandidate = normalizeName(candidate);
  if (!normalizedValue || !normalizedCandidate) return false;
  if (normalizedValue === normalizedCandidate) return true;
  if (normalizedValue.length >= 3 && normalizedCandidate.includes(normalizedValue)) return true;
  return normalizedCandidate.length >= 3 && normalizedValue.includes(normalizedCandidate);
}

function cleanLineup(item) {
  const rawLineup = sourceLineup(item);
  if (!Array.isArray(rawLineup)) return [];
  const suspiciousCount = rawLineup.filter(isSuspiciousLineupName).length;
  if (suspiciousCount >= 2 || (suspiciousCount > 0 && rawLineup.length >= 4)) return [];
  const candidates = candidateNames(item);
  const seen = new Set();
  return rawLineup.filter((name) => {
    const normalized = normalizeName(name);
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    if (isSuspiciousLineupName(name)) return false;
    if (NON_ARTIST_LINEUP_NAMES.includes(normalized)) return false;
    return !candidates.some((candidate) => isSameEntity(name, candidate));
  });
}

function itemTextSignals(item) {
  return [
    item.title,
    item.promoter,
    item.account,
    item.address,
    item.address_full,
    item.venue_name,
    ...(Array.isArray(item.venue) ? item.venue : []),
    ...(Array.isArray(item.evidence) ? item.evidence : []),
  ].filter(Boolean);
}

function verifiedAddress(item) {
  const address = String(item.address || "").trim();
  const addressFull = String(item.address_full || "").trim();
  if (address && addressFull && normalizeDedupePart(address) !== normalizeDedupePart(addressFull)) {
    const venue = item.venue_name || first(item.venue, "") || item.promoter || item.account || "";
    const city = first(item.city, item.city_key || first(item.city_keys, "")) || "";
    const verifiedVenue = findVerifiedMapEntry([`${city}|${venue}`, `${venue}|${city}`], { uniqueOnly: true });
    if (verifiedVenue?.address) return verifiedVenue.address;
    if (String(item.address_source || "").trim() === "manual_registry") return address;
  }
  if (addressFull) return addressFull;
  if (address) return address;
  const signals = itemTextSignals(item).map(normalizeName).filter(Boolean);
  const match = VERIFIED_ADDRESS_BOOK.find((entry) =>
    entry.keys.some((key) => signals.some((signal) => signal.includes(normalizeName(key)))),
  );
  return match?.address || "";
}

function normalizeHour(hour, meridiem = "") {
  let value = Number.parseInt(String(hour), 10);
  if (!Number.isFinite(value)) return "";
  const marker = meridiem.toLowerCase();
  if (marker === "pm" && value < 12) value += 12;
  if (marker === "am" && value === 12) value = 0;
  return String(value).padStart(2, "0");
}

function chineseTimeToClock(prefix, hour, minutePart = "") {
  let value = Number.parseInt(String(hour), 10);
  if (!Number.isFinite(value) || value > 24) return "";
  if (/下午|晚上|晚间|今晚|夜里/.test(prefix || "") && value >= 1 && value < 12) value += 12;
  if (/凌晨/.test(prefix || "") && value === 12) value = 0;
  const minutes = minutePart === "半" ? "30" : (minutePart || "").replace(/\D/g, "").padStart(2, "0") || "00";
  return `${String(value).padStart(2, "0")}:${minutes}`;
}

function extractEventTime(item) {
  if (item.event_time_text) return item.event_time_text;
  const text = [
    ...(Array.isArray(item.event_date_text) ? item.event_date_text : []),
    item.title,
    ...(Array.isArray(item.evidence) ? item.evidence : []),
  ]
    .filter(Boolean)
    .join(" | ");

  const rangeMatch = text.match(/\b([01]?\d|2[0-3])[:：]([0-5]\d)\s*(?:[-–—~至到]\s*([01]?\d|2[0-3])[:：]([0-5]\d))?\s*(AM|PM|am|pm)?\b/);
  if (rangeMatch) {
    const start = `${normalizeHour(rangeMatch[1], rangeMatch[5])}:${rangeMatch[2]}`;
    if (rangeMatch[3]) return `${start}-${normalizeHour(rangeMatch[3], rangeMatch[5])}:${rangeMatch[4]}`;
    return start;
  }

  const chineseMatch = text.match(/(凌晨|早上|上午|中午|下午|晚上|晚间|今晚|夜里)?\s*([01]?\d|2[0-3])\s*点(半|[0-5]\d分?)?/);
  if (chineseMatch) return chineseTimeToClock(chineseMatch[1], chineseMatch[2], chineseMatch[3]);

  return "";
}

function rawBioLines(item) {
  if (Array.isArray(item.dj_bio_lines) && item.dj_bio_lines.length > 0) {
    return item.dj_bio_lines
      .map((line) => String(line).trim())
      .filter(Boolean)
      .filter((line) => !isDisplayUrlLine(line))
      .slice(0, 4);
  }
  if (!Array.isArray(item.evidence)) return [];
  const cleanLineupNames = cleanLineup(item).map(normalizeName).filter(Boolean);
  const title = normalizeName(item.title);
  const cleanTitle = normalizeName(displayTitle(item));
  const account = normalizeName(item.account);
  const promoter = normalizeName(item.promoter);
  const city = normalizeName(first(item.city, ""));
  const venue = normalizeName(first(item.venue, ""));
  if (cleanLineupNames.length === 0) return [];
  return item.evidence
    .filter(Boolean)
    .map((line) => String(line).trim())
    .filter((line) => !isDisplayUrlLine(line))
    .filter((line) => !/^(来源公众号|公众号)[:：]/.test(line))
    .filter((line) => !/已关注|二维码|购票|点击|扫码|小程序/.test(line))
    .filter((line) => {
      const normalized = normalizeName(line);
      if (!normalized || normalized === title || normalized === cleanTitle) return false;
      if ([account, promoter, city, venue].filter(Boolean).includes(normalized)) return false;
      return cleanLineupNames.some((name) => normalized.includes(name));
    })
    .filter((line) => /dj|producer|artist|厂牌|发行|主理|来自|现居|音乐|舞曲|电子|场景|club|house|techno|bass|trax|break/i.test(line))
    .slice(0, 4);
}

function atlasArtistItems(item) {
  const rows = Array.isArray(item.weeklyAtlas?.lineupResolved) ? item.weeklyAtlas.lineupResolved : [];
  return rows
    .filter((row) => row && (row.displayTier === "show" || row.displayTier === "show_with_hint"))
    .map((row) => {
      const candidateNames = Array.isArray(row.candidates)
        ? row.candidates.map((candidate) => candidate.canonicalName).filter(Boolean).slice(0, 3)
        : [];
      return {
        raw: row.raw || "",
        artistId: row.displayTier === "show" ? row.artistId || "" : "",
        name: row.canonicalName || row.raw || candidateNames[0] || "",
        matchMethod: row.matchMethod || "",
        matchScore: Number(row.matchScore || 0),
        displayTier: row.displayTier,
        isVerified: row.displayTier === "show" && Boolean(row.artistId),
        isHint: row.displayTier === "show_with_hint",
        hintLabel: candidateNames.join(" / "),
      };
    })
    .filter((row) => row.name || row.raw || row.hintLabel);
}

function cleanDescriptionLines(item, fallbackLines = []) {
  const rawLines = Array.isArray(item.description_original_lines) && item.description_original_lines.length > 0
    ? item.description_original_lines
    : fallbackLines;
  const blocked = [
    item.title,
    item.title_original,
    displayTitle(item),
    item.account,
    item.promoter,
    item.venue_name,
    verifiedAddress(item),
    ...(Array.isArray(item.venue) ? item.venue : []),
    ...(Array.isArray(item.city) ? item.city : []),
  ].map(normalizeName).filter(Boolean);

  return rawLines
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .filter((line) => !isDisplayUrlLine(line))
    .filter((line) => !/^[-—–_＝=]{3,}$/.test(line))
    .filter((line) => !/^(来源|公众号|日期|时间|地点|地址|场地|俱乐部|票价|门票|预售|现场|购票|报名|link|address|date|time|venue|tickets?)\s*[:：]/i.test(line))
    .filter((line) => !/^(📅|⏰|🎫|📍|地址|地点|时间|日期)/.test(line))
    .filter((line) => {
      const normalized = normalizeName(line);
      if (!normalized) return false;
      if (blocked.includes(normalized)) return false;
      return !blocked.some((value) => value.length >= 8 && normalized.includes(value));
    })
    .slice(0, 6);
}

function stringValues(value, limit = 40) {
  const out = [];
  const visit = (input) => {
    if (out.length >= limit) return;
    if (typeof input === "string") {
      const cleaned = input.replace(/\s+/g, " ").trim();
      if (cleaned) out.push(cleaned);
      return;
    }
    if (Array.isArray(input)) {
      input.forEach(visit);
      return;
    }
    if (input && typeof input === "object") {
      ["quote", "text", "raw", "value", "ticketing_text", "price_text", "description", "ocr_text", "content", "digest", "summary_digest", "body_text", "body_text_excerpt", "raw_digest", "_source_queue_text"]
        .forEach((key) => visit(input[key]));
    }
  };
  visit(value);
  return out.slice(0, limit);
}

function cleanSoundSystemValue(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .replace(/^(?:音响系统|音响|sound\s*system|soundsystem|audio\s*system)\s*[:：\-–—]?\s*/i, "")
    .trim();
}

function soundSystemItemsForItem(item) {
  const rawItems = [
    ...stringValues(item.sound_system),
    ...stringValues(item.sound_systems),
    ...stringValues(item.soundSystem),
    ...stringValues(item.sound_system_text),
    ...stringValues(item.audio_system),
    ...stringValues(item.audioSystem),
  ];
  const out = [];
  const seen = new Set();
  for (const raw of rawItems) {
    const parts = String(raw || "").split(/[、,，;；|｜/]+/);
    for (const part of parts) {
      const cleaned = cleanSoundSystemValue(part);
      const key = normalizeName(cleaned);
      if (!key || key === normalizeName("音响效果很好") || key === normalizeName("声音很棒")) continue;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(cleaned);
      if (out.length >= 4) return out;
    }
  }
  return out;
}

function soundSystemEvidenceForItem(item) {
  return [
    ...stringValues(item.sound_system_evidence),
    ...stringValues(item.audio_system_evidence),
  ].slice(0, 4);
}

function ticketingSourceText(item) {
  return [
    ...stringValues(item.ticketing_text),
    ...stringValues(item.ticketing),
    ...stringValues(item.price_text),
    ...stringValues(item.price),
    ...stringValues(item.evidence),
    ...stringValues(item.description_original_lines),
    ...stringValues(item.source_evidence),
    ...stringValues(item.source_evidence_text),
    ...stringValues(item.digest),
    ...stringValues(item.summary_digest),
    ...stringValues(item.body_text),
    ...stringValues(item.body_text_excerpt),
    ...stringValues(item.raw_digest),
    ...stringValues(item._source_queue_text),
  ].join("\n");
}

function timeConditionalFreeRules(item) {
  const source = ticketingSourceText(item).normalize("NFKC");
  const values = [];
  const seen = new Set();
  for (const match of source.matchAll(TIME_CONDITIONAL_FREE_RE)) {
    const value = String(match[0] || "").replace(/\s+/g, " ").trim();
    const key = value.toLowerCase();
    if (key && !seen.has(key)) {
      seen.add(key);
      values.push(value);
    }
  }
  return values;
}

function normalizeTicketingValue(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/￥/g, "¥")
    .replace(/\s+(元|¥)$/i, "¥")
    .replace(/\s+(rmb|cny)$/i, (_, unit) => unit.toUpperCase())
    .replace(/\s*¥\b/g, "¥");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function looksLikeDrinkPrice(value, sourceText) {
  const cleaned = normalizeTicketingValue(value);
  const amount = cleaned.match(/\d+(?:\.\d+)?/);
  if (!amount) return false;
  const normalizedSource = String(sourceText || "").normalize("NFKC");
  const re = new RegExp(escapeRegExp(amount[0]), "g");
  for (const match of normalizedSource.matchAll(re)) {
    const start = Math.max(0, match.index - 16);
    const end = Math.min(normalizedSource.length, match.index + amount[0].length + 24);
    const local = normalizedSource.slice(start, end);
    if (DRINK_SPECIAL_RE.test(local) && !TICKETING_LABEL_RE.test(local)) return true;
  }
  return false;
}

function looksLikeYearAsTicketPrice(value) {
  const cleaned = normalizeTicketingValue(value);
  if (TICKETING_CURRENCY_RE.test(cleaned)) return false;
  const amount = cleaned.match(/\d+(?:\.\d+)?/);
  if (!amount) return false;
  const number = Number(amount[0]);
  return Number.isInteger(number) && number >= 1900 && number <= 2099;
}

function qrOnlyTicketingText(value) {
  const cleaned = normalizeTicketingValue(value);
  return QR_ONLY_TICKETING_RE.test(cleaned) && !VISIBLE_AMOUNT_RE.test(cleaned) && !FREE_ENTRY_RE.test(cleaned);
}

function sourceTicketingItems(source) {
  const normalized = String(source || "").normalize("NFKC");
  const out = [];
  const seen = new Set();
  const add = (value) => {
    const cleaned = normalizeTicketingValue(value);
    const key = cleaned.toLowerCase();
    if (key && !seen.has(key)) {
      seen.add(key);
      out.push(cleaned);
    }
  };

  for (const match of normalized.matchAll(TICKETING_TIER_RE)) {
    const value = String(match[0] || "");
    const amount = value.match(/\d+(?:\.\d+)?/);
    if (amount && Number(amount[0]) < 10) continue;
    if (looksLikeYearAsTicketPrice(value)) continue;
    if (looksLikeDrinkPrice(value, normalized)) continue;
    add(value);
  }

  const timed = [];
  for (const match of normalized.matchAll(TIME_CONDITIONAL_FREE_RE)) {
    const value = String(match[0] || "");
    timed.push(value);
    add(value);
  }

  if (timed.length === 0) {
    const free = normalized.match(FREE_ENTRY_RE);
    if (free) add(free[0]);
  }
  return out.slice(0, 8);
}

function cleanPriceItems(item) {
  const rawItems = stringValues(item.price);
  const source = ticketingSourceText(item).normalize("NFKC");
  const sourceItems = sourceTicketingItems(source);
  if (sourceItems.length > 0) return sourceItems;
  const timeFreeRules = timeConditionalFreeRules(item);
  const freeContext = FREE_ENTRY_RE.test(source) || rawItems.some((value) => FREE_ENTRY_RE.test(value));
  const out = [];
  const seen = new Set();
  const add = (value) => {
    const cleaned = normalizeTicketingValue(value);
    const key = cleaned.toLowerCase();
    if (key && !seen.has(key)) {
      seen.add(key);
      out.push(cleaned);
    }
  };

  rawItems.forEach((value) => {
    const cleaned = normalizeTicketingValue(value);
    if (!cleaned) return;
    if (qrOnlyTicketingText(cleaned)) return;
    if (looksLikeYearAsTicketPrice(cleaned)) return;
    if (looksLikeDrinkPrice(cleaned, source)) return;
    if (SINGLE_DIGIT_PRICE_RE.test(cleaned) && freeContext) return;
    if (timeFreeRules.length > 0 && FREE_ENTRY_RE.test(cleaned) && !/\d/.test(cleaned)) return;
    add(cleaned);
  });
  timeFreeRules.forEach(add);
  return out.slice(0, 8);
}

function numericCoordinate(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function firstDefined(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "");
}

function coordinateSystem(value, fallback = "GCJ-02") {
  const raw = value === null || value === undefined || value === "" ? fallback : value;
  const normalized = String(raw || "").trim().toUpperCase().replace(/_/g, "-");
  if (normalized === "GCJ02") return "GCJ-02";
  if (normalized === "GCJ-02LL") return "GCJ-02";
  if (normalized === "TENCENT" || normalized === "QQMAP" || normalized === "AMAP" || normalized === "GAODE") return "GCJ-02";
  return normalized;
}

const TAXI_GRADE_GEO_SOURCES = new Set([
  "amap_geocoder",
  "amap_geocoder_crosscheck",
  "amap_place_search",
  "amap_place_search_crosscheck",
  "deepseek_web_resource_crosscheck",
  "frontend_verified_map_location_book",
  "manual_verified_map_location_book",
  "qqmap_geocoder",
  "qqmap_place_search",
  "tencent_geocoder",
  "tencent_place_search",
  "tencent_place_search_crosscheck",
  "venue_registry_verified",
]);

function normalizeGeoSourceToken(value) {
  return String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function hasTrustedTaxiGradeGeoSource(item) {
  const verification = item.geo_verification && typeof item.geo_verification === "object" ? item.geo_verification : {};
  return [
    item.geo_source,
    item.geo_provider,
    item.coordinate_source,
    item.map_source,
    verification.source,
    verification.provider,
  ].some((value) => TAXI_GRADE_GEO_SOURCES.has(normalizeGeoSourceToken(value)));
}

function hasTaxiGradeAddress(item, labels, pair) {
  return Boolean(String(
    labels.addressLabel ||
    item.address_full ||
    item.address ||
    item.venue_address ||
    pair?.address ||
    ""
  ).trim());
}

function inChinaTaxiBounds(pair) {
  const latitude = numericCoordinate(pair?.latitude);
  const longitude = numericCoordinate(pair?.longitude);
  return (
    latitude !== null &&
    longitude !== null &&
    latitude >= 18 &&
    latitude <= 54.5 &&
    longitude >= 73 &&
    longitude <= 135.5
  );
}

function hasTaxiGradeMapEvidence(item, labels, pair, options = {}) {
  if (!validMapPair(pair)) return false;
  if (!inChinaTaxiBounds(pair)) return false;
  if (!hasTaxiGradeAddress(item, labels, pair)) return false;
  if (options.verifiedMapBook) return true;
  return hasTrustedTaxiGradeGeoSource(item);
}

function coordinateNumbers(value) {
  if (Array.isArray(value)) {
    const numbers = value.map(numericCoordinate).filter((number) => number !== null);
    return numbers.length >= 2 ? numbers.slice(0, 2) : null;
  }
  if (typeof value === "string") {
    const numbers = value
      .match(/-?\d+(?:\.\d+)?/g)
      ?.map(numericCoordinate)
      .filter((number) => number !== null);
    return numbers && numbers.length >= 2 ? numbers.slice(0, 2) : null;
  }
  if (value && typeof value === "object") {
    const lat = numericCoordinate(firstDefined(value.latitude, value.lat, value.y));
    const lng = numericCoordinate(firstDefined(value.longitude, value.lng, value.lon, value.x));
    if (lat !== null && lng !== null) return [lat, lng];
  }
  return null;
}

function coordinatePairFromValue(value, order = "auto") {
  const numbers = coordinateNumbers(value);
  if (!numbers) return null;
  const [firstNumber, secondNumber] = numbers;
  const firstLooksLng = Math.abs(firstNumber) > 90 && Math.abs(firstNumber) <= 180 && Math.abs(secondNumber) <= 90;
  const secondLooksLng = Math.abs(secondNumber) > 90 && Math.abs(secondNumber) <= 180 && Math.abs(firstNumber) <= 90;
  if (order === "lnglat" || firstLooksLng) return { latitude: secondNumber, longitude: firstNumber };
  if (order === "latlng" || secondLooksLng) return { latitude: firstNumber, longitude: secondNumber };
  return { latitude: firstNumber, longitude: secondNumber };
}

function coordinateCandidateFromValue(value, system, fallbackSystem, order) {
  const pair = coordinatePairFromValue(value, order);
  if (!pair) return null;
  return { ...pair, system, fallbackSystem };
}

function coordinatePair(item) {
  const genericSystem = item.geo_coord_system || item.geo_coordinate_system || item.coordinate_system || item.coord_system;
  const nestedSources = [
    item.mapLocation,
    item.map_location,
    item.location,
    item.venue_location,
    item.geo,
    item.coordinates,
    item.coordinate,
    item.coord,
    item.point,
    item.position,
    item.map_point,
    item.mapPosition,
    item.map_position,
    item.tencentLocation,
    item.tencent_location,
    item.qqmapLocation,
    item.qqmap_location,
    item.amapLocation,
    item.amap_location,
    item.geocode,
    item.geocode_result,
    item.geocodeResult,
  ].filter((source) => source && typeof source === "object" && !Array.isArray(source));
  const nestedCandidates = nestedSources.flatMap((source) => {
    const nestedSystem = source.geo_coord_system || source.geo_coordinate_system || source.coordinate_system || source.coord_system || source.coordinate_type || source.coord_type || source.type || genericSystem;
    return [
      { latitude: source.geo_lat, longitude: source.geo_lng, system: nestedSystem, fallbackSystem: "GCJ-02" },
      {
        latitude: firstDefined(source.geo_gcj02_lat, source.gcj02_lat, source.gcj02_latitude, source.latitude_gcj02, source.lat_gcj02, source.gcj_lat, source.gcj_latitude),
        longitude: firstDefined(source.geo_gcj02_lng, source.gcj02_lng, source.gcj02_longitude, source.longitude_gcj02, source.lng_gcj02, source.gcj_lng, source.gcj_longitude),
        system: "GCJ-02",
        fallbackSystem: "GCJ-02",
      },
      {
        latitude: firstDefined(source.latitude, source.lat, source.map_lat, source.tencent_lat, source.qqmap_lat, source.amap_lat, source.location_lat, source.venue_lat, source.y),
        longitude: firstDefined(source.longitude, source.lng, source.lon, source.map_lng, source.map_lon, source.tencent_lng, source.qqmap_lng, source.amap_lng, source.location_lng, source.venue_lng, source.x),
        system: nestedSystem,
        fallbackSystem: "GCJ-02",
      },
      coordinateCandidateFromValue(firstDefined(source.location, source.coordinate, source.coordinates, source.coord, source.point, source.position, source.value), nestedSystem, "GCJ-02", "auto"),
      coordinateCandidateFromValue(firstDefined(source.latlng, source.lat_lng), nestedSystem, "GCJ-02", "latlng"),
      coordinateCandidateFromValue(firstDefined(source.lnglat, source.lng_lat), nestedSystem, "GCJ-02", "lnglat"),
    ].filter(Boolean);
  });
  const candidates = [
    { latitude: item.geo_lat, longitude: item.geo_lng, system: genericSystem, fallbackSystem: "GCJ-02" },
    { latitude: item.geo_gcj02_lat, longitude: item.geo_gcj02_lng, system: "GCJ-02", fallbackSystem: "GCJ-02" },
    { latitude: item.gcj02_lat, longitude: item.gcj02_lng, system: "GCJ-02", fallbackSystem: "GCJ-02" },
    {
      latitude: firstDefined(item.gcj02_latitude, item.latitude_gcj02, item.lat_gcj02, item.gcj_lat, item.gcj_latitude),
      longitude: firstDefined(item.gcj02_longitude, item.longitude_gcj02, item.lng_gcj02, item.gcj_lng, item.gcj_longitude),
      system: "GCJ-02",
      fallbackSystem: "GCJ-02",
    },
    { latitude: item.lat, longitude: firstDefined(item.lng, item.lon), system: genericSystem, fallbackSystem: "" },
    { latitude: item.latitude, longitude: item.longitude, system: genericSystem, fallbackSystem: "" },
    { latitude: item.venue_lat, longitude: item.venue_lng, system: genericSystem, fallbackSystem: "GCJ-02" },
    { latitude: item.map_lat, longitude: firstDefined(item.map_lng, item.map_lon), system: "GCJ-02", fallbackSystem: "GCJ-02" },
    { latitude: item.tencent_lat, longitude: item.tencent_lng, system: "GCJ-02", fallbackSystem: "GCJ-02" },
    { latitude: item.qqmap_lat, longitude: item.qqmap_lng, system: "GCJ-02", fallbackSystem: "GCJ-02" },
    { latitude: item.amap_lat, longitude: item.amap_lng, system: "GCJ-02", fallbackSystem: "GCJ-02" },
    coordinateCandidateFromValue(firstDefined(item.map_location, item.mapLocation, item.location, item.coordinate, item.coordinates, item.coord, item.point, item.position, item.tencentLocation, item.tencent_location, item.qqmapLocation, item.qqmap_location, item.amapLocation, item.amap_location), genericSystem, "GCJ-02", "auto"),
    coordinateCandidateFromValue(firstDefined(item.latlng, item.lat_lng), genericSystem, "GCJ-02", "latlng"),
    coordinateCandidateFromValue(firstDefined(item.lnglat, item.lng_lat), genericSystem, "GCJ-02", "lnglat"),
    ...nestedCandidates,
  ].filter(Boolean);
  for (const candidate of candidates) {
    const hasLatitude = candidate.latitude !== null && candidate.latitude !== undefined && candidate.latitude !== "";
    const hasLongitude = candidate.longitude !== null && candidate.longitude !== undefined && candidate.longitude !== "";
    if (!hasLatitude && !hasLongitude) continue;
    if (!hasLatitude || !hasLongitude) continue;
    const system = coordinateSystem(candidate.system, candidate.fallbackSystem);
    if (system !== "GCJ-02") continue;
    return {
      latitude: numericCoordinate(candidate.latitude),
      longitude: numericCoordinate(candidate.longitude),
    };
  }
  return null;
}

function hasCoordinateSignals(item) {
  return [
    item.geo_lat,
    item.geo_lng,
    item.geo_gcj02_lat,
    item.geo_gcj02_lng,
    item.gcj02_lat,
    item.gcj02_lng,
    item.lat,
    item.lng,
    item.lon,
    item.latitude,
    item.longitude,
    item.venue_lat,
    item.venue_lng,
    item.map_lat,
    item.map_lng,
    item.map_lon,
    item.tencent_lat,
    item.tencent_lng,
    item.qqmap_lat,
    item.qqmap_lng,
    item.amap_lat,
    item.amap_lng,
    item.mapLocation,
    item.map_location,
    item.location,
    item.venue_location,
    item.geo,
    item.coordinates,
    item.coordinate,
    item.coord,
    item.point,
    item.position,
    item.tencentLocation,
    item.tencent_location,
    item.qqmapLocation,
    item.qqmap_location,
    item.amapLocation,
    item.amap_location,
    item.latlng,
    item.lat_lng,
    item.lnglat,
    item.lng_lat,
  ].some((value) => value !== null && value !== undefined && value !== "");
}

function sameVerifiedMapPoint(left, right) {
  return (
    Number(left.latitude) === Number(right.latitude) &&
    Number(left.longitude) === Number(right.longitude)
  );
}

function findVerifiedMapEntry(keys, options = {}) {
  const normalizedKeys = keys.map(normalizeDedupePart).filter(Boolean);
  if (normalizedKeys.length === 0) return null;
  const matches = [];
  for (const entry of VERIFIED_MAP_LOCATION_BOOK) {
    const entryKeys = (entry.keys || []).map(normalizeDedupePart).filter(Boolean);
    if (entryKeys.some((key) => normalizedKeys.includes(key))) matches.push(entry);
  }
  if (matches.length === 0) return null;
  if (options.uniqueOnly) {
    const firstMatch = matches[0];
    if (!matches.every((entry) => sameVerifiedMapPoint(entry, firstMatch))) return null;
  }
  return matches[0];
}

function verifiedMapLocationForItem(item, labels) {
  const venue = labels.venueLabel || item.venue_name || first(item.venue, "") || item.promoter || item.account || "";
  const city = labels.cityLabel || first(item.city, item.city_key || first(item.city_keys, "")) || "";
  const addressKeys = [
    labels.addressLabel,
    item.address_full,
    item.address,
    item.clubProfile?.addressLabel,
    item.club_profile?.address,
  ].filter(Boolean);
  const addressMatch = findVerifiedMapEntry(addressKeys);
  const entry = addressMatch || findVerifiedMapEntry([
    `${city}|${venue}`,
    `${venue}|${city}`,
    `${item.city_key || ""}|${venue}`,
  ], { uniqueOnly: true });
  if (!entry) return null;
  return {
    latitude: Number(entry.latitude),
    longitude: Number(entry.longitude),
    name: venue || entry.name || labels.titleLabel || "",
    address: labels.addressLabel || entry.address || labels.placeLabel || "",
  };
}

function validMapPair(pair) {
  if (!pair) return false;
  const latitude = numericCoordinate(pair.latitude);
  const longitude = numericCoordinate(pair.longitude);
  return (
    latitude !== null &&
    longitude !== null &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180 &&
    !(latitude === 0 && longitude === 0)
  );
}

function mapLocationForItem(item, labels) {
  const explicitPair = coordinatePair(item);
  const verifiedPair = verifiedMapLocationForItem(item, labels);
  const verifiedTaxiGrade = hasTaxiGradeMapEvidence(item, labels, verifiedPair, { verifiedMapBook: true });
  const explicitTaxiGrade = hasTaxiGradeMapEvidence(item, labels, explicitPair);
  const pair = verifiedTaxiGrade ? verifiedPair : (explicitTaxiGrade ? explicitPair : null);
  if (!pair) return null;
  const { latitude, longitude } = pair;
  if (latitude === null || longitude === null) return null;
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;
  if (latitude === 0 && longitude === 0) return null;
  return {
    latitude,
    longitude,
    name: labels.venueLabel || item.promoter || item.account || labels.titleLabel || "",
    address: labels.addressLabel || labels.placeLabel || "",
  };
}

function compactItem(item) {
  item = canonicalizeItemFields(item);
  const isSourceOverview = isSourceOverviewItem(item);
  const verifiedAddressLabel = verifiedAddress(item);
  const venueLabel = item.venue_name || first(item.venue, "");
  const cityLabel = first(item.city, item.city_key === "unknown" ? "" : item.city_key || "");
  const addressLabel = verifiedAddressLabel || item.address || "";
  const placeLabel = addressLabel || venueLabel || cityLabel;
  const isShanghai = normalizeName(cityLabel) === normalizeName("上海") || normalizeName(item.city_key) === "shanghai";
  const cardLocationLabel = isShanghai
    ? (venueLabel || item.promoter || item.account || cityLabel || "")
    : (cityLabel || venueLabel || item.promoter || item.account || "");
  const cleanedLineup = cleanLineup(item);
  const bioLines = rawBioLines(item);
  const rawTimeLabel = extractEventTime(item);
  const timeLabel = isTrustedTimeSource(item) ? rawTimeLabel : "";
  const musicStyles = inferMusicStyles(item);
  const dateRange = dateRangeForItem(item);
  const primaryDate = dateRange.start || item.event_date_iso_guess || "";
  const dateLabel = primaryDate || first(item.event_date_text, "");
  const dateRangeLabel = dateRange.start && dateRange.end !== dateRange.start ? `${dateRange.start} - ${dateRange.end}` : dateLabel;
  const dateRangeCompact = compactDateRange(dateRange.start, dateRange.end) || compactDate(dateLabel);
  const weekdayRange = weekdayRangeLabel(dateRange.start, dateRange.end) || weekdayLabel(dateLabel);
  const isCalendarPreview = isCalendarPreviewItem(item) || isSourceOverview;
  const calendarPreviewLabel = isCalendarPreview ? "活动一览" : "";
  const metaParts = [cityLabel, dateRangeLabel].filter(Boolean);
  const coverUrl = posterUrl(item);
  const internalPosterFileId = posterFileId(item);
  const sourceActionEnabled = item.source_action?.available !== false && !isAggregateChildItem(item);
  const sourceHashVal = sourceActionEnabled
    ? (item.source_action?.url_hash || item.source_article?.url_hash || item.sourceHash || item.source_hash || "")
    : "";
  const sourceHash = sourceHashVal || (sourceActionEnabled && item.id && (item.id.match(/[a-f0-9]{16,32}/i) || [])[0]) || "";
  const organizerKey = organizerKeyForItem({ ...item, venueLabel });
  const upstreamClubProfile = item.clubProfile || item.club_profile || {};
  const interestSeed = `${item.id || item.article_id || item.title || ""}`.split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const descText = String(item.description_text || "").trim();
  const rawDescriptionLines = cleanDescriptionLines(item, bioLines);
  const descriptionLines = descText ? [descText].concat(rawDescriptionLines) : rawDescriptionLines;
  const atlasArtists = atlasArtistItems(item);
  const priceItems = cleanPriceItems(item);
  const titleLabel = isSourceOverview ? originalArticleTitle(item) : displayTitle(item);
  const mapLocation = mapLocationForItem(item, { venueLabel, addressLabel, placeLabel, titleLabel });
  const soundSystemItems = soundSystemItemsForItem(item);
  const soundSystemEvidence = soundSystemEvidenceForItem(item);
  return {
    ...item,
    isSourceOverview,
    price: isSourceOverview ? [] : priceItems,
    coverUrl,
    posterFileId: internalPosterFileId,
    sourceHash,
    hasSource: Boolean(sourceHash && sourceActionEnabled),
    rawCityLabel: cityLabel,
    rawCardLocationLabel: cardLocationLabel,
    rawPriceItems: priceItems,
    cityLabel,
    displayTitle: titleLabel,
    dateLabel: isSourceOverview ? "" : dateLabel,
    dateRangeLabel: isSourceOverview ? "" : dateRangeLabel,
    dateRangeCompact: isSourceOverview ? "" : dateRangeCompact,
    dateCompact: isSourceOverview ? "" : dateRangeCompact,
    weekdayLabel: isSourceOverview ? "" : weekdayRange,
    detailMetaLine: isSourceOverview ? "" : metaParts.join(" · "),
    isCalendarPreview,
    calendarPreviewLabel,
    cardLocationLabel: isSourceOverview ? "" : cardLocationLabel,
    timeLabel: isSourceOverview ? "" : timeLabel,
    hasTime: isSourceOverview ? false : Boolean(timeLabel),
    hasTrustedTime: isSourceOverview ? false : Boolean(timeLabel),
    venueLabel,
    organizerKey,
    clubProfile: {
      schemaVersion: "weekly_club_profile.v1",
      organizerKey,
      displayName: firstMeaningful(upstreamClubProfile.displayName, upstreamClubProfile.display_name, venueLabel, item.promoter, item.account),
      cityLabel,
      addressLabel: firstMeaningful(upstreamClubProfile.addressLabel, upstreamClubProfile.address, addressLabel),
    },
    addressLabel,
    placeLabel,
    hasPlace: isSourceOverview ? false : Boolean(placeLabel),
    hasVenue: isSourceOverview ? false : Boolean(venueLabel),
    hasAddress: isSourceOverview ? false : Boolean(addressLabel),
    mapLocation: isSourceOverview ? null : mapLocation,
    hasMapLocation: isSourceOverview ? false : Boolean(mapLocation),
    musicStyles: isSourceOverview ? [] : musicStyles,
    styleLabel: isSourceOverview ? "" : joinList(musicStyles),
    hasStyle: isSourceOverview ? false : musicStyles.length > 0,
    hasPrice: isSourceOverview ? false : priceItems.length > 0,
    soundSystemItems: isSourceOverview ? [] : soundSystemItems,
    soundSystemLabel: isSourceOverview ? "" : joinList(soundSystemItems),
    hasSoundSystem: isSourceOverview ? false : soundSystemItems.length > 0,
    soundSystemEvidence: isSourceOverview ? [] : soundSystemEvidence,
    lineupItems: isSourceOverview ? [] : cleanedLineup,
    lineupLabel: isSourceOverview ? "" : joinList(cleanedLineup),
    hasLineup: isSourceOverview ? false : cleanedLineup.length > 0,
    lineupHint: "点击海报跳转公众号原文查看",
    hasLineupHint: isSourceOverview ? false : hasRawLineup(item) && cleanedLineup.length === 0,
    bioLines: isSourceOverview ? [] : bioLines,
    hasBio: isSourceOverview ? false : bioLines.length > 0,
    atlasArtistItems: isSourceOverview ? [] : atlasArtists,
    hasAtlasArtistItems: isSourceOverview ? false : atlasArtists.length > 0,
    descriptionLines: isSourceOverview ? [] : descriptionLines,
    descriptionLead: isSourceOverview ? "" : descriptionLines[0] || "",
    hasDescription: isSourceOverview ? false : descriptionLines.length > 0,
    interestLabel: String(24 + (interestSeed % 78)),
  };
}

function dedupeKeyForItem(item) {
  const title = normalizeDedupePart(item.displayTitle || displayTitle(item));
  const date = dateKey(item);
  const city = cityKey(item);
  const venue = venueKey(item);
  return [title, date, city, venue].join("|");
}

function itemQualityScore(item) {
  return (
    (item.hasTrustedTime ? 16 : 0) +
    (item.hasAddress ? 8 : 0) +
    (item.hasDescription ? 5 : 0) +
    (item.hasSource ? 4 : 0) +
    (item.hasLineup ? 3 : 0) +
    (item.hasStyle ? 2 : 0) +
    (item.coverUrl ? 1 : 0)
  );
}

function dedupeItems(items) {
  const output = [];
  for (const item of items || []) {
    const duplicateIndex = output.findIndex((current) => areLikelyDuplicateItems(current, item));
    if (duplicateIndex === -1) {
      output.push(item);
      continue;
    }
    if (itemQualityScore(item) > itemQualityScore(output[duplicateIndex])) {
      output[duplicateIndex] = mergeNonEmpty(output[duplicateIndex], item);
    } else {
      output[duplicateIndex] = mergeNonEmpty(item, output[duplicateIndex]);
    }
  }
  return output;
}

module.exports = {
  areLikelyDuplicateItems,
  atlasEventToWeeklyItem,
  atlasArtistItems,
  canonicalizeItemFields,
  cleanLineup,
  compactDate,
  compactDateRange,
  compactItem,
  dateRangeForItem,
  dedupeItems,
  dedupeKeyForItem,
  displayTitle,
  extractEventTime,
  first,
  firstMeaningful,
  inferMusicStyles,
  isDisplayUrlLine,
  isCalendarPreviewItem,
  isSourceOverviewItem,
  isMeaningfulValue,
  joinList,
  mergeNonEmpty,
  weekdayLabel,
};
