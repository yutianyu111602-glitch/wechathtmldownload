import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_API_DIR = path.resolve(moduleDir, "../data/current_release");
const SOURCE_HASH_RE = /^[a-f0-9]{16,64}$/i;
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TRUSTED_TIME_SOURCES = new Set([
  "source_text",
  "article_text",
  "official_text",
  "poster_ocr",
  "poster_text",
  "manual_verified",
]);
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

export function storageSlug(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return "";
  let out = "";
  for (const char of raw) {
    if (/^[a-z0-9_-]$/.test(char)) {
      out += char;
    } else {
      out += `u${char.codePointAt(0).toString(16)}`;
    }
  }
  return out.replace(/-+/g, "-").replace(/^[-_]+|[-_]+$/g, "");
}

function normalizeLimit(value) {
  const parsed = Number.parseInt(String(value ?? "100"), 10);
  if (!Number.isFinite(parsed)) return 100;
  return Math.min(Math.max(parsed, 1), 100);
}

function normalizeCursor(value) {
  const parsed = Number.parseInt(String(value ?? "0"), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return parsed;
}

function first(value, fallback = "") {
  return Array.isArray(value) ? value[0] || fallback : value || fallback;
}

function isoDate(value) {
  const text = String(value || "").trim();
  return ISO_DATE_RE.test(text) ? text : "";
}

function addDateRange(dates, start, end) {
  if (!start || !end || start > end) return;
  const startMs = Date.parse(`${start}T00:00:00Z`);
  const endMs = Date.parse(`${end}T00:00:00Z`);
  const dayMs = 24 * 60 * 60 * 1000;
  const days = Math.round((endMs - startMs) / dayMs);
  if (!Number.isFinite(days) || days < 1 || days > 31) return;
  for (let offset = 1; offset < days; offset += 1) {
    dates.add(new Date(startMs + offset * dayMs).toISOString().slice(0, 10));
  }
}

function directItemDateValues(item) {
  return [
    item.event_date_start,
    item.event_date_end,
    item.event_date_iso_guess,
  ].map(isoDate).filter(Boolean);
}

function itemDateKeys(item) {
  const dates = new Set();
  for (const key of ["event_date_start", "event_date_end", "event_date_iso_guess"]) {
    const value = isoDate(item[key]);
    if (value) dates.add(value);
  }
  if (directItemDateValues(item).length === 0) {
    for (const key of ["event_date_iso_guesses", "event_date_text"]) {
      const raw = item[key];
      const values = Array.isArray(raw) ? raw : [raw];
      for (const value of values) {
        const date = isoDate(value);
        if (date) dates.add(date);
      }
    }
  }
  addDateRange(dates, isoDate(item.event_date_start), isoDate(item.event_date_end));
  return [...dates].sort();
}

function itemMatchesDate(item, date) {
  const target = isoDate(date);
  if (!target) return true;
  const dates = itemDateKeys(item);
  if (dates.includes(target)) return true;
  const start = isoDate(item.event_date_start) || dates[0] || "";
  const end = isoDate(item.event_date_end) || dates[dates.length - 1] || start;
  return Boolean(start && end && start <= target && target <= end);
}

function currentShanghaiDateParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    date: `${byType.year}-${byType.month}-${byType.day}`,
    hour: Number.parseInt(byType.hour || "0", 10),
  };
}

function addDays(dateKey, days) {
  const date = isoDate(dateKey);
  if (!date) return "";
  const [year, month, day] = date.split("-").map((part) => Number.parseInt(part, 10));
  const value = new Date(Date.UTC(year, month - 1, day));
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function normalizeLateNightCutoffHour(value) {
  const parsed = Number.parseInt(value ?? "6", 10);
  if (!Number.isFinite(parsed)) return 6;
  return Math.max(0, Math.min(12, parsed));
}

const DEFAULT_CURRENT_LOOKBACK_DAYS = 0;

function normalizeLookbackDays(value, fallback = 0) {
  const parsed = Number.parseInt(value ?? String(fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(45, parsed));
}

function currentShanghaiBusinessDateKey(now = new Date(), cutoffHour = 6) {
  const parts = currentShanghaiDateParts(now);
  if (cutoffHour > 0 && Number.isFinite(parts.hour) && parts.hour < cutoffHour) {
    return addDays(parts.date, -1);
  }
  return parts.date;
}

function nowFromOverride(value) {
  if (!value) return new Date();
  const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function itemIsCurrentOrFuture(item, today) {
  const target = isoDate(today);
  if (!target) return true;
  const dates = itemDateKeys(item);
  const start = isoDate(item.event_date_start) || dates[0] || "";
  const end = isoDate(item.event_date_end) || dates[dates.length - 1] || start;
  if (!start && !end) return true;
  return (end || start) >= target;
}

function hasValue(value) {
  if (Array.isArray(value)) return value.some((item) => String(item || "").trim());
  return Boolean(String(value || "").trim());
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

function stripEmoji(value) {
  return String(value || "").replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, "").trim();
}

function stripLeadingDateWords(value) {
  return String(value || "")
    .replace(/^\s*[「【\[]?\s*(今晚|今夜|本周|周末)\s*[」】\]]?\s*/i, "")
    .replace(/^\s*(\d{1,2})[./-](\d{1,2})(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*/i, "")
    .replace(/^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*/, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
}

function normalizeDedupePart(value) {
  return String(stripLeadingDateWords(stripEmoji(value)) || "")
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "")
    .replace(/[^\w\u4e00-\u9fff]/g, "")
    .trim();
}

function dedupeKeyForItem(item) {
  const title = normalizeDedupePart(item.title_display || item.display_title || item.title);
  const date = dateKey(item);
  const city = cityKey(item);
  const venue = venueKey(item);
  return [title, date, city, venue].join("|");
}

function dateKey(item) {
  return String(item.event_date_start || item.event_date_iso_guess || first(item.event_date_iso_guesses, "") || "").trim();
}

function cityKey(item) {
  return normalizeDedupePart(first(item.city, item.city_key || first(item.city_keys, "")));
}

function venueKey(item) {
  return normalizeDedupePart(item.venue_name || first(item.venue, "") || item.promoter || item.account);
}

function organizerLabel(item) {
  return String(
    item.venue_name ||
      first(item.venue, "") ||
      item.promoter ||
      item.account ||
      item.source_account_name ||
      item.source_article?.account_name ||
      "",
  ).trim();
}

function organizerKeyForItem(item) {
  return normalizeDedupePart(item.organizer_key || item.organizerKey || organizerLabel(item));
}

function withClubProfile(item) {
  if (!item || typeof item !== "object") return item;
  const organizerKey = organizerKeyForItem(item);
  const displayName = organizerLabel(item);
  const cityLabel = first(item.city, item.city_key || first(item.city_keys, ""));
  const addressLabel = firstMeaningful(item.address, item.club_profile?.address, item.address_full);
  return mergeNonEmpty(item, {
    organizer_key: organizerKey,
    club_profile: {
      schema_version: "weekly_club_profile.v1",
      organizer_key: organizerKey,
      display_name: displayName,
      city: cityLabel,
      address: addressLabel,
    },
  });
}

function compactText(value, maxChars = 220) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.length > maxChars ? `${text.slice(0, maxChars).trim()}...` : text;
}

function compactTextList(value, { limit = 6, maxChars = 220 } = {}) {
  const values = Array.isArray(value) ? value : value ? [value] : [];
  return values
    .map((entry) => compactText(entry, maxChars))
    .filter(Boolean)
    .slice(0, limit);
}

function pickObjectFields(value, fields) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const output = {};
  for (const field of fields) {
    if (value[field] !== undefined && value[field] !== null && value[field] !== "") {
      output[field] = value[field];
    }
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

const LIST_COMPAT_FIELDS = [
  "id",
  "title",
  "title_display",
  "display_title",
  "title_original",
  "city_key",
  "city_keys",
  "city",
  "city_name",
  "event_date_start",
  "event_date_end",
  "event_date_iso_guess",
  "event_date_iso_guesses",
  "event_date_text",
  "event_time_text",
  "event_time_source",
  "running_hours_text",
  "running_hours_source",
  "time_start",
  "time_end",
  "post_date",
  "source_published_at",
  "quality_status",
  "quality_flags",
  "publish_status",
  "promoter",
  "account",
  "account_key",
  "source_account_name",
  "venue",
  "venue_name",
  "venue_id",
  "address",
  "address_full",
  "address_source",
  "venue_lat",
  "venue_lng",
  "geo_lat",
  "geo_lng",
  "geo_coord_system",
  "geo_coordinate_system",
  "geo_gcj02_lat",
  "geo_gcj02_lng",
  "gcj02_lat",
  "gcj02_lng",
  "latitude",
  "longitude",
  "coordinate_system",
  "coord_system",
  "map_location",
  "coordinates",
  "tencent_location",
  "cover_url",
  "cover_image_url",
  "coverUrl",
  "poster_url",
  "poster_file_id",
  "poster_source",
  "flyer_url",
  "description_text",
  "description_original_lines",
  "lineup",
  "lineup_artists",
  "lineup_text",
  "music_styles",
  "style_tags",
  "genres",
  "price",
  "price_text",
  "ticketing",
  "ticketing_text",
  "ticket_price",
  "ticketing_tiers",
  "sourceHash",
  "source_hash",
  "sourceRefId",
  "source_ref_id",
  "sourceTitle",
  "source_title",
  "sourceAccountName",
  "source_account_name",
  "sourcePublishedAt",
  "source_published_at",

];

function withListCompatItem(rawItem) {
  const item = withClubProfile(rawItem);
  if (!item || typeof item !== "object") return item;
  const output = {};
  for (const key of LIST_COMPAT_FIELDS) {
    if (item[key] !== undefined && item[key] !== null && item[key] !== "") {
      output[key] = item[key];
    }
  }
  output.organizer_key = item.organizer_key;

  const sourceAction = pickObjectFields(item.source_action, ["available", "url_hash"]);
  if (sourceAction) output.source_action = sourceAction;
  const sourceArticle = pickObjectFields(item.source_article, ["url_hash", "title", "account_name", "published_at"]);
  if (sourceArticle) output.source_article = sourceArticle;

  if (Array.isArray(item.evidence)) output.evidence = compactTextList(item.evidence, { limit: 3, maxChars: 160 });
  if (Array.isArray(item.description_original_lines)) {
    output.description_original_lines = compactTextList(item.description_original_lines, { limit: 2, maxChars: 160 });
  }
  if (Array.isArray(item.source_evidence)) {
    output.source_evidence = compactTextList(item.source_evidence, { limit: 2, maxChars: 160 });
  }
  if (Array.isArray(item.sound_system_evidence)) {
    output.sound_system_evidence = compactTextList(item.sound_system_evidence, { limit: 4, maxChars: 180 });
  }
  for (const key of ["description", "digest", "summary", "summary_digest", "source_evidence_text"]) {
    if (typeof item[key] === "string") output[key] = compactText(item[key], 260);
  }
  return output;
}

function duplicateScopeKey(item) {
  return [dateKey(item), cityKey(item), venueKey(item)].join("|");
}

function sourceHash(item) {
  return String(firstMeaningful(
    item.sourceHash,
    item.source_hash,
    item.sourceRefId,
    item.source_ref_id,
    item.source_action?.url_hash,
    item.source_article?.url_hash,
  ) || "").trim();
}

function coverKey(item) {
  return String(firstMeaningful(item.poster_file_id, item.posterFileId, item.cover_file_id, item.coverFileId, item.poster_url, item.flyer_url, item.cover_image_url, item.cover_url, item.coverUrl) || "")
    .trim()
    .toLowerCase()
    .replace(/\?.*$/, "");
}

function titleFingerprint(item) {
  let raw = stripLeadingDateWords(stripEmoji(item.title_display || item.display_title || item.title || ""));
  raw = raw
    .replace(/\d{4}[./-]\d{1,2}[./-]\d{1,2}/g, "")
    .replace(/\d{1,2}[./-]\d{1,2}/g, "")
    .replace(/\d{1,2}\s*月\s*\d{1,2}\s*日?/g, "")
    .replace(/周[一二三四五六日天]|星期[一二三四五六日天]|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?/gi, "")
    .replace(/\b(room|support|pres|presents|presented|weekly|party|event|events|lineup|preview)\b/gi, "")
    .replace(/(本周|周末|今晚|今夜|活动|预告|呈现|来袭|就在|预热派对|专场|厂牌|派对)/g, "");
  for (const candidate of [item.venue_name, first(item.venue, ""), item.promoter, item.account, first(item.city, "")]) {
    const normalizedCandidate = normalizeDedupePart(candidate);
    if (normalizedCandidate.length >= 3) {
      raw = normalizeDedupePart(raw).replace(new RegExp(normalizedCandidate, "g"), "");
    }
  }
  const fingerprint = normalizeDedupePart(raw);
  return fingerprint.length >= 6 ? fingerprint : "";
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

function titleDateTokens(item) {
  const values = [
    item.title_display || item.display_title || item.title,
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
  if (!TRUSTED_TIME_SOURCES.has(source)) return "";
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
  let text = String(item.title_display || item.display_title || item.title || "").toLowerCase();
  text = text
    .replace(/\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{1,2}[./-]\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日?/g, " ")
    .replace(/周[一二三四五六日天]|星期[一二三四五六日天]|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?/gi, " ");
  for (const candidate of [item.venue_name, first(item.venue, ""), item.promoter, item.account, first(item.city, "")]) {
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

function areLikelyDuplicateItems(left, right) {
  const leftDate = dateKey(left);
  const rightDate = dateKey(right);
  const leftCity = cityKey(left);
  const rightCity = cityKey(right);
  if (!leftDate || leftDate !== rightDate || !leftCity || leftCity !== rightCity) return false;
  if (!venueScopeMatches(left, right)) return false;
  if (conflictingTitleDates(left, right)) return false;
  const similarity = titleSimilarity(left, right);
  const leftCover = coverKey(left);
  const rightCover = coverKey(right);
  if (leftCover && leftCover === rightCover && similarity >= 0.5) return true;
  const leftSource = sourceHash(left);
  const rightSource = sourceHash(right);
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

function itemQualityScore(item) {
  const timeSource = String(item.event_time_source || item.running_hours_source || "").trim().toLowerCase();
  return (
    (TRUSTED_TIME_SOURCES.has(timeSource) && hasValue(item.event_time_text || item.running_hours_text) ? 16 : 0) +
    (hasValue(item.address || item.address_full) ? 8 : 0) +
    (hasValue(item.description_original_lines || item.description) ? 5 : 0) +
    (hasValue(item.source_action?.url_hash || item.source_article?.url_hash) ? 4 : 0) +
    (hasValue(item.lineup_artists || item.lineup) ? 3 : 0) +
    (hasValue(item.music_styles || item.style_tags || item.genres) ? 2 : 0) +
    (hasValue(item.poster_file_id || item.posterFileId || item.cover_file_id || item.coverFileId || item.cover_image_url || item.cover_url || item.coverUrl) ? 1 : 0)
  );
}

function dedupeKey(item) {
  return dedupeKeyForItem(item) || `${dateKey(item)}||${cityKey(item)}||${String(item.id || "").slice(0, 32)}`;
}

function findDuplicateKey(seenMap, item) {
  for (const [key, existing] of seenMap) {
    if (areLikelyDuplicateItems(existing, item)) return key;
  }
  return null;
}

function dedupeItems(items) {
  const seen = new Map(); // key -> item
  for (const item of items || []) {
    const duplicateKey = findDuplicateKey(seen, item);
    if (!duplicateKey) {
      const key = dedupeKey(item);
      seen.set(key, item);
      continue;
    }
    if (itemQualityScore(item) > itemQualityScore(seen.get(duplicateKey))) {
      seen.set(duplicateKey, mergeNonEmpty(seen.get(duplicateKey), item));
    } else {
      seen.set(duplicateKey, mergeNonEmpty(item, seen.get(duplicateKey)));
    }
  }
  return Array.from(seen.values());
}

async function readJson(baseDir, relativePath) {
  const fullPath = path.resolve(baseDir, relativePath);
  // Prevent path traversal: resolved path must stay within baseDir
  const normalizedBase = path.resolve(baseDir);
  if (!fullPath.startsWith(normalizedBase + path.sep) && fullPath !== normalizedBase) {
    throw Object.assign(new Error(`Path traversal blocked: ${relativePath}`), { code: "PATH_TRAVERSAL" });
  }
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw);
}

export class WeeklyActivityDataStore {
  constructor(options = {}) {
    this.env = options.env || process.env;
    this.baseDir = options.baseDir || process.env.WEEKLY_ACTIVITY_API_DIR || DEFAULT_API_DIR;
    this.sourceMapDir =
      options.sourceMapDir ||
      process.env.WEEKLY_ACTIVITY_SOURCE_MAP_DIR ||
      path.resolve(this.baseDir, "../source_actions");
    this.todayOverride = isoDate(options.today || this.env.WEEKLY_ACTIVITY_TODAY || "");
    this.nowOverride = options.now || this.env.WEEKLY_ACTIVITY_NOW || "";
    this.lateNightCutoffHour = normalizeLateNightCutoffHour(
      options.lateNightCutoffHour ?? this.env.WEEKLY_ACTIVITY_LATE_NIGHT_CUTOFF_HOUR,
    );
  }

  todayDateKey() {
    return this.todayOverride || currentShanghaiBusinessDateKey(nowFromOverride(this.nowOverride), this.lateNightCutoffHour);
  }

  async getManifest() {
    try {
      const raw = await readJson(this.baseDir, "manifest.json");
      const expectedSchema = "weekly_activity_miniprogram_api.v1";
      if (raw.schema_version && raw.schema_version !== expectedSchema) {
        console.warn(
          `[dataStore] manifest schema drift: got "${raw.schema_version}", expected "${expectedSchema}"`,
        );
      }
      return {
        schema_version: raw.schema_version || expectedSchema,
        generated_at: raw.generated_at || raw.generatedAt || null,
        item_count: raw.item_count ?? raw.items_total ?? 0,
        pipeline: raw.pipeline,
        field_resource_repair: raw.field_resource_repair || null,
        geocode_enrichment: raw.geocode_enrichment || null,
        id_consistency_repair: raw.id_consistency_repair || null,
      };
    } catch (err) {
      console.error("[dataStore] getManifest failed:", err.message);
      return {
        schema_version: "weekly_activity_miniprogram_api.v1",
        generated_at: null,
        item_count: 0,
      };
    }
  }

  async getColumnItems({ tag, lang } = {}) {
    const COLUMN_JSON = path.resolve(this.baseDir, "column.json");
    try {
      const raw = await readFile(COLUMN_JSON, "utf8");
      const data = JSON.parse(raw);
      let items = Array.isArray(data.items) ? data.items : [];
      if (tag && tag !== "all") {
        items = items.filter((item) => item.tag === tag);
      }
      return {
        schema_version: "weekly_activity_miniprogram_column.v1",
        generated_at: data.generated_at || null,
        item_count: items.length,
        items,
      };
    } catch {
      return {
        schema_version: "weekly_activity_miniprogram_column.v1",
        generated_at: null,
        item_count: 0,
        items: [],
      };
    }
  }

  async getCurrent({ cityKey, date, limit, cursor, lookbackDays } = {}) {
    let current;
    try {
      current = await readJson(this.baseDir, "current.json");
      const expectedCurrentSchema = "weekly_activity_miniprogram_current.v1";
      if (current.schema_version && current.schema_version !== expectedCurrentSchema) {
        console.warn(
          `[dataStore] current.json schema drift: got "${current.schema_version}", expected "${expectedCurrentSchema}"`,
        );
      }
      if (Array.isArray(current.items) && Number.isFinite(current.item_count) && current.item_count !== current.items.length) {
        console.warn(
          `[dataStore] current.json count mismatch: item_count=${current.item_count} but items.length=${current.items.length}`,
        );
      }
    } catch (err) {
      console.error("[dataStore] getCurrent failed to read current.json:", err.message);
      return {
        schemaVersion: "weekly_activity_api.current_response.v1",
        generatedAt: null,
        filters: { cityKey: cityKey || null, date: date || null, lookbackDays: lookbackDays || null },
        page: { limit: normalizeLimit(limit), cursor: "0", nextCursor: null, total: 0 },
        items: [],
      };
    }
    const pageLimit = normalizeLimit(limit);
    const pageCursor = normalizeCursor(cursor);
    const today = this.todayDateKey();
    const lookback = normalizeLookbackDays(lookbackDays, DEFAULT_CURRENT_LOOKBACK_DAYS);
    const currentThreshold = !date && lookback > 0 ? addDays(today, -lookback) : today;
    const filtered = current.items.filter((item) => {
      if (cityKey && item.city_key !== cityKey && !(item.city_keys || []).includes(cityKey)) {
        return false;
      }
      if (date && !itemMatchesDate(item, date)) {
        return false;
      }
      if (!date && !itemIsCurrentOrFuture(item, currentThreshold)) {
        return false;
      }
      return item.quality_status === "READY";
    });
    const deduped = dedupeItems(filtered);
    const items = deduped.slice(pageCursor, pageCursor + pageLimit).map(withListCompatItem);
    const nextOffset = pageCursor + items.length;

    return {
      schemaVersion: "weekly_activity_api.current_response.v1",
      generatedAt: current.generated_at,
      filters: {
        cityKey: cityKey || null,
        date: date || null,
        lookbackDays: lookback || null,
      },
      page: {
        limit: pageLimit,
        cursor: String(pageCursor),
        nextCursor: nextOffset < deduped.length ? String(nextOffset) : null,
        total: deduped.length,
      },
      items,
    };
  }

  async getCities() {
    try {
      return await readJson(this.baseDir, "by-city/index.json");
    } catch {
      const current = await readJson(this.baseDir, "current.json");
      const today = this.todayDateKey();
      const cities = new Map();
      for (const item of current.items) {
        if (!itemIsCurrentOrFuture(item, today)) continue;
        if (item.quality_status !== "READY") continue;
        const key = item.city_key || "unknown";
        const label = (item.city || [])[0] || key;
        cities.set(key, {
          city_key: key,
          city: label,
          item_count: (cities.get(key)?.item_count || 0) + 1,
          path: `by-city/${key}.json`,
        });
      }
      return {
        schema_version: "weekly_activity_miniprogram_city_index.v1",
        generated_at: current.generated_at,
        item_count: cities.size,
        cities: [...cities.values()],
      };
    }
  }

  async getDates() {
    try {
      const today = this.todayDateKey();
      const payload = await readJson(this.baseDir, "by-date/index.json");
      const dates = (payload.dates || []).filter((entry) => {
        const dateValue = isoDate(entry.date);
        return !today || !dateValue || dateValue >= today;
      });
      return {
        ...payload,
        date_count: dates.length,
        item_count: dates.length,
        dates,
      };
    } catch {
      const current = await readJson(this.baseDir, "current.json");
      const today = this.todayDateKey();
      const dates = new Map();
      for (const item of current.items) {
        const itemDates = itemDateKeys(item);
        for (const date of itemDates.length ? itemDates : ["unknown"]) {
          const dateValue = isoDate(date);
          if (today && dateValue && dateValue < today) continue;
          dates.set(date, {
            date,
            item_count: (dates.get(date)?.item_count || 0) + 1,
            path: `by-date/${date}.json`,
          });
        }
      }
      return {
        schema_version: "weekly_activity_miniprogram_date_index.v1",
        generated_at: current.generated_at,
        item_count: dates.size,
        dates: [...dates.values()].sort((a, b) => a.date.localeCompare(b.date)),
      };
    }
  }

  async getItem(id) {
    const rawId = String(id || "").trim();
    const safeId = storageSlug(rawId);
    if (!safeId) return null;

    try {
      const detail = await readJson(this.baseDir, `by-id/${safeId}.json`);
      return withClubProfile(detail.item || detail);
    } catch {
      const current = await readJson(this.baseDir, "current.json");
      const item = current.items.find((entry) => entry.id === rawId || storageSlug(entry.id) === safeId) || null;
      return item ? withClubProfile(item) : null;
    }
  }

  async getItemsByIds(ids) {
    if (!Array.isArray(ids) || ids.length === 0) return [];
    const wanted = ids
      .map((id) => ({ raw: String(id || "").trim(), safe: storageSlug(id) }))
      .filter((entry) => entry.raw && entry.safe);
    if (wanted.length === 0) return [];

    const results = await Promise.allSettled(
      wanted.map((entry) =>
        readJson(this.baseDir, `by-id/${entry.safe}.json`).then(
          (detail) => ({ ok: true, entry, detail }),
        ),
      ),
    );
    const found = [];
    const remaining = [];
    for (const result of results) {
      if (result.status === "fulfilled" && result.value?.ok) {
        found.push(withClubProfile(result.value.detail.item || result.value.detail));
      } else {
        remaining.push(result.status === "fulfilled" ? result.value.entry : result.reason?.entry || wanted[results.indexOf(result)]);
      }
    }

    if (remaining.length > 0) {
      const current = await readJson(this.baseDir, "current.json");
      const rawIds = new Set(remaining.map((entry) => entry.raw));
      const safeIds = new Set(remaining.map((entry) => entry.safe));
      found.push(
        ...current.items
          .filter((item) => rawIds.has(item.id) || safeIds.has(storageSlug(item.id)))
          .map(withClubProfile),
      );
    }
    return found;
  }

  async getLlmSummary() {
    try {
      return await readJson(this.baseDir, "llm/weekly_summary.json");
    } catch {
      return null;
    }
  }

  async getLlmEnrichmentIndex() {
    try {
      return await readJson(this.baseDir, "llm/enrichment_index.json");
    } catch {
      return null;
    }
  }

  async getLlmEnrichment(id) {
    const safeId = storageSlug(id);
    if (!safeId) return null;

    try {
      return await readJson(this.baseDir, `llm/enrichments/${safeId}.json`);
    } catch {
      return null;
    }
  }

  async getAtlasEvent(eventId) {
    const rawId = String(eventId || "").trim();
    if (!rawId) return null;

    let snapshot;
    try {
      snapshot = await readJson(this.baseDir, "weekly_entity_snapshot.json");
    } catch {
      return null;
    }

    const profileById = new Map(
      (Array.isArray(snapshot.artist_profiles) ? snapshot.artist_profiles : [])
        .filter((profile) => profile && profile.artist_id)
        .map((profile) => [profile.artist_id, profile]),
    );
    const rows = (Array.isArray(snapshot.lineup_resolved) ? snapshot.lineup_resolved : [])
      .filter((row) => row.event_id === rawId)
      .map((row) => {
        const isVerified = row.match_method === "alias_exact" && row.artist_id && row.verified === true;
        const isHint = row.match_method === "fuzzy_multiple";
        return {
          raw: row.raw || "",
          artistId: isVerified ? row.artist_id : null,
          canonicalName: isVerified ? row.canonical_name || "" : null,
          matchMethod: row.match_method || "no_match",
          matchScore: Number.isFinite(Number(row.match_score)) ? Number(row.match_score) : 0,
          displayTier: isVerified ? "show" : isHint ? "show_with_hint" : "hide",
          candidates: isHint && Array.isArray(row.candidates)
            ? row.candidates.map((candidate) => ({
                canonicalName: candidate.canonical_name || "",
                score: Number.isFinite(Number(candidate.score)) ? Number(candidate.score) : 0,
              }))
            : [],
        };
      });

    const artistProfiles = rows
      .filter((row) => row.artistId && profileById.has(row.artistId))
      .map((row) => {
        const profile = profileById.get(row.artistId);
        return {
          artistId: profile.artist_id,
          canonicalName: profile.canonical_name || row.canonicalName || "",
          verified: profile.verified === true,
          source: profile.source || "atlas_alias_export",
        };
      });

    return {
      schemaVersion: "weekly_activity_api.atlas_event.v1",
      eventId: rawId,
      generatedAt: snapshot.generated_at || null,
      publishPackage: snapshot.publish_package || "",
      lineupResolved: rows,
      artistProfiles,
      safety: {
        graphWriteExecuted: false,
        qdrantWriteExecuted: false,
        productionWriteExecuted: false,
        fuzzyCandidateIdsExposed: false,
      },
    };
  }

  async getPosterSource(id) {
    const item = await this.getItem(id);
    // 优先级: poster_url > flyer_url > cover_image_url > cover_url
    const source = item?.poster_url || item?.flyer_url || item?.cover_image_url || item?.cover_url || item?.coverUrl || "";
    if (!source || !/^https?:\/\//i.test(source)) return null;
    return source;
  }

  async getSourceAction(urlHash) {
    const safeHash = String(urlHash || "").trim();
    if (!SOURCE_HASH_RE.test(safeHash)) return null;
    let payload;
    try {
      payload = await readJson(this.sourceMapDir, "source_url_map.json");
    } catch {
      return null;
    }
    const source = payload.sources?.[safeHash] || null;
    if (!source?.url) return null;
    return {
      schemaVersion: "weekly_activity_api.source_action.v1",
      type: source.type || "wechat_article",
      mode: "webview",
      url: source.url,
      accountName: source.account_name || "",
      publishedAt: source.published_at || "",
      eventId: source.event_id || "",
    };
  }

  /**
   * Find current_release items that reference a DJ name in lineup_artists
   * and return their yuanbao enrichment fields.
   */
  async getDjEnrichmentFromCurrent({ djName, djAliases = [], limit = 20 } = {}) {
    const query = String(djName || "").trim().toLowerCase();
    const aliases = (Array.isArray(djAliases) ? djAliases : []).map((a) => String(a || "").trim().toLowerCase()).filter(Boolean);
    if (!query && !aliases.length) return { items: [], bios: [], profiles: [] };

    try {
      const current = await readJson(this.baseDir, "current.json");
      const matches = [];

      for (const item of current.items || []) {
        const lineup = Array.isArray(item.lineup_artists) ? item.lineup_artists : [];
        const hasMatch = lineup.some((artist) => {
          const a = String(artist || "").trim().toLowerCase();
          if (!a) return false;
          if (a.includes(query) || query.includes(a)) return true;
          return aliases.some((alias) => a.includes(alias) || alias.includes(a));
        });
        if (!hasMatch) continue;

        const match = {
          id: item.id || "",
          title: item.title_display || item.title || "",
          city: item.city_name || (item.city || [])[0] || "",
          venue: item.venue_name || "",
          event_date_start: item.event_date_start || "",
          event_date_end: item.event_date_end || "",
          poster_file_id: item.poster_file_id || "",
          cloudFileId: item.cloudFileId || "",
        };

        // Attach yuanbao enrichment fields if present
        const enrichment = {};
        if (Array.isArray(item.dj_bio_lines) && item.dj_bio_lines.length) {
          enrichment.dj_bio_lines = item.dj_bio_lines;
        }
        if (Array.isArray(item.artist_profiles) && item.artist_profiles.length) {
          // Filter to profiles matching this DJ
          enrichment.artist_profiles = item.artist_profiles.filter((p) => {
            const pn = String(p?.name || "").trim().toLowerCase();
            if (!pn) return false;
            return pn.includes(query) || query.includes(pn) ||
              aliases.some((a) => pn.includes(a) || a.includes(pn));
          });
          if (!enrichment.artist_profiles.length) delete enrichment.artist_profiles;
        }
        if (item.historical_context) {
          enrichment.historical_context = item.historical_context;
        }
        if (item.extraction_metadata) {
          enrichment.extraction_metadata = item.extraction_metadata;
        }

        if (Object.keys(enrichment).length) {
          match.enrichment = enrichment;
        }

        matches.push(match);
        if (matches.length >= limit) break;
      }

      // Collect unique bios and profiles across all matches
      const bios = [];
      const profiles = [];
      const seenBios = new Set();
      const seenProfiles = new Set();
      for (const m of matches) {
        if (m.enrichment?.dj_bio_lines) {
          for (const line of m.enrichment.dj_bio_lines) {
            const key = String(line).slice(0, 80);
            if (!seenBios.has(key)) {
              seenBios.add(key);
              bios.push(line);
            }
          }
        }
        if (m.enrichment?.artist_profiles) {
          for (const p of m.enrichment.artist_profiles) {
            const key = `${p.name || ""}|${p.role || ""}`;
            if (!seenProfiles.has(key)) {
              seenProfiles.add(key);
              profiles.push(p);
            }
          }
        }
      }

      return { items: matches, bios: bios.slice(0, limit), profiles: profiles.slice(0, limit) };
    } catch (err) {
      console.error("[dataStore] getDjEnrichmentFromCurrent failed:", err.message);
      return { items: [], bios: [], profiles: [] };
    }
  }
}
