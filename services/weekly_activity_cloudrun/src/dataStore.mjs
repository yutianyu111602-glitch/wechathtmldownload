import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isElectronicMusicRelevantItem } from "./electronicRelevance.mjs";
import dateVisibility from "./dateVisibility.cjs";

const {
  isoDate,
  itemDateKeys,
  itemIsCurrentOrFuture,
  itemMatchesDateKey,
  itemMatchesDateWindow,
  normalizeDateWindow,
} = dateVisibility;

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_API_DIR = path.resolve(moduleDir, "../data/current_release");
const SOURCE_HASH_RE = /^[a-f0-9]{16,64}$/i;
const TRUSTED_TIME_SOURCES = new Set([
  "source_text",
  "article_text",
  "official_text",
  "poster_ocr",
  "poster_text",
  "manual_verified",
]);
const TITLE_STOP_TOKENS = new Set([
  "ambient",
  "anniversary",
  "bass",
  "bird",
  "club",
  "disco",
  "early",
  "electro",
  "event",
  "events",
  "hip",
  "hiphop",
  "hop",
  "house",
  "lineup",
  "official",
  "party",
  "pres",
  "presented",
  "presents",
  "preview",
  "room",
  "support",
  "techno",
  "ticket",
  "tickets",
  "tonight",
  "trance",
  "weekly",
  "year",
  "years",
]);
const CHINESE_TITLE_STOP_TOKENS = new Set(["活动", "派对", "预告", "阵容", "周末", "本周", "今晚", "今夜"]);

export function storageSlug(value) {
  const raw = String(value || "").trim().toLowerCase().replace(/\s+/g, "-");
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

function boolOrNull(value) {
  if (value === true || value === false) return value;
  const text = String(value ?? "").trim().toLowerCase();
  if (text === "true") return true;
  if (text === "false") return false;
  return null;
}

function stringOrNull(value) {
  const text = String(value ?? "").trim();
  return text || null;
}

export function generationIdOf(value) {
  return stringOrNull(value?.generationId || value?.generation_id);
}

function generationHandshakeError(currentId, manifestId) {
  return Object.assign(
    new Error(`weekly package generation mismatch: current=${currentId || "<missing>"} manifest=${manifestId || "<missing>"}`),
    {
      code: "WEEKLY_GENERATION_HANDSHAKE_FAILED",
      currentGenerationId: currentId,
      manifestGenerationId: manifestId,
    },
  );
}

function assertPackageGeneration(current, manifest) {
  const currentId = generationIdOf(current);
  const manifestId = generationIdOf(manifest);
  if (!currentId && !manifestId) {
    if (current && manifest) {
      const currentAt = stringOrNull(current.generated_at || current.generatedAt);
      const manifestAt = stringOrNull(manifest.generated_at || manifest.generatedAt);
      if (!currentAt || !manifestAt || currentAt !== manifestAt) {
        throw generationHandshakeError(currentAt, manifestAt);
      }
    }
    return null;
  }
  if (!currentId || !manifestId || currentId !== manifestId) {
    throw generationHandshakeError(currentId, manifestId);
  }
  return currentId;
}

function generatedAtOf(value) {
  return stringOrNull(value?.generatedAt || value?.generated_at);
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function requestedGenerationError(requested, active) {
  return Object.assign(
    new Error(`weekly requested generation mismatch: requested=${requested || "<missing>"} active=${active || "<legacy>"}`),
    {
      code: "WEEKLY_REQUEST_GENERATION_MISMATCH",
      requestedGenerationId: requested,
      activeGenerationId: active,
    },
  );
}

function detailMatchesPackage(detail, packageState, currentItem) {
  const detailId = generationIdOf(detail);
  if (packageState.generationId) {
    if (detailId !== packageState.generationId) return false;
  } else if (detailId || generatedAtOf(detail) !== packageState.generatedAt) {
    return false;
  }
  const detailItem = detail?.item || detail;
  return Boolean(currentItem && canonicalJson(detailItem) === canonicalJson(currentItem));
}

function withPackageIdentity(item, packageState) {
  if (!item) return null;
  return {
    ...withPublicDetailItem(item),
    generatedAt: packageState.generatedAt,
    generation_id: packageState.generationId,
    generationId: packageState.generationId,
  };
}

function safeSanjiSourceContract(raw) {
  const contract = raw && typeof raw.sanji_source_contract === "object" && raw.sanji_source_contract
    ? raw.sanji_source_contract
    : {};
  const sourceMode = stringOrNull(raw?.source_mode || contract.source_mode);
  const directRssFeedFetch = boolOrNull(raw?.direct_rss_feed_fetch ?? contract.direct_rss_feed_fetch);
  const sanjiDbSnapshotExport = boolOrNull(raw?.sanji_db_snapshot_export ?? contract.sanji_db_snapshot_export);
  const sanjiDesktopRefreshInvoked = boolOrNull(
    raw?.sanji_desktop_refresh_invoked ?? contract.sanji_desktop_refresh_invoked,
  );
  if (!sourceMode && directRssFeedFetch === null && sanjiDbSnapshotExport === null && sanjiDesktopRefreshInvoked === null) {
    return null;
  }
  return {
    schema_version: stringOrNull(contract.schema_version) || "weekly_sanji_source_contract.public.v1",
    source_mode: sourceMode,
    source: stringOrNull(contract.source),
    generated_at: stringOrNull(contract.generated_at),
    exported_rows: Number(contract.exported_rows || 0),
    prefetch_queue_rows: Number(contract.prefetch_queue_rows || 0),
    direct_rss_feed_fetch: directRssFeedFetch,
    sanji_db_snapshot_export: sanjiDbSnapshotExport,
    sanji_desktop_refresh_invoked: sanjiDesktopRefreshInvoked,
  };
}

const itemMatchesDate = itemMatchesDateKey;

function itemCityKeys(item = {}) {
  const values = [item.city_key, item.cityKey]
    .concat(Array.isArray(item.city_keys) ? item.city_keys : [])
    .concat(Array.isArray(item.cityKeys) ? item.cityKeys : []);
  return [...new Set(values.map((value) => String(value || "").trim().toLowerCase()).filter(Boolean))];
}

function itemCityLabel(item, key, index) {
  const labels = Array.isArray(item.city) ? item.city : [item.city];
  return String(labels[index] || (index === 0 ? (item.city_name || item.cityName) : "") || key);
}

function mergeDuplicateCityFields(fallbackItem, preferredItem, mergedItem) {
  const preferredKeys = itemCityKeys(preferredItem);
  const fallbackKeys = itemCityKeys(fallbackItem);
  const keys = [...new Set(preferredKeys.concat(fallbackKeys))];
  if (!keys.length) return mergedItem;
  const labelsByKey = new Map();
  for (const source of [fallbackItem, preferredItem]) {
    const sourceKeys = itemCityKeys(source);
    sourceKeys.forEach((key, index) => {
      const label = itemCityLabel(source, key, index).trim();
      if (label) labelsByKey.set(key, label);
    });
  }
  const primaryKey = String(preferredItem?.city_key || preferredItem?.cityKey || keys[0]).trim().toLowerCase();
  const orderedKeys = primaryKey && keys.includes(primaryKey)
    ? [primaryKey, ...keys.filter((key) => key !== primaryKey)]
    : keys;
  return {
    ...mergedItem,
    city_key: primaryKey || orderedKeys[0],
    city_keys: orderedKeys,
    city: orderedKeys.map((key) => labelsByKey.get(key) || key),
    ...(Object.hasOwn(fallbackItem || {}, "cityKeys") || Object.hasOwn(preferredItem || {}, "cityKeys")
      ? { cityKeys: orderedKeys }
      : {}),
  };
}

function normalizeVisibilityScope(value) {
  const scope = String(value || "").trim().toLowerCase();
  return scope === "package" || scope === "package_window" || scope === "all" ? "package" : "current";
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
  // Product rule: last night's events stay current until 07:00 next morning.
  const parsed = Number.parseInt(value ?? "7", 10);
  if (!Number.isFinite(parsed)) return 7;
  return Math.max(0, Math.min(12, parsed));
}

const DEFAULT_CURRENT_LOOKBACK_DAYS = 0;

function normalizeLookbackDays(value, fallback = 0) {
  const parsed = Number.parseInt(value ?? String(fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(45, parsed));
}

function currentShanghaiBusinessDateKey(now = new Date(), cutoffHour = 7) {
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

function hasValue(value) {
  if (Array.isArray(value)) return value.some((item) => String(item || "").trim());
  return Boolean(String(value || "").trim());
}

function isPlainObject(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function normalizeClubOverviews(raw) {
  const byClub = {};
  const kindCounts = {};
  let overviewCount = 0;
  const rawByClub = isPlainObject(raw?.by_club) ? raw.by_club : {};

  for (const [rawClub, rawItems] of Object.entries(rawByClub)) {
    const club = String(rawClub || "").trim();
    if (!club || !Array.isArray(rawItems)) continue;
    const items = rawItems
      .filter(isPlainObject)
      .map((item) => ({
        record_type: stringOrNull(item.record_type) || "club_overview_parent",
        parent_aggregate: item.parent_aggregate !== false,
        include_in_activity_feed: item.include_in_activity_feed === true,
        club: stringOrNull(item.club) || club,
        title: stringOrNull(item.title) || "",
        publish_date: isoDate(item.publish_date) || null,
        original_url: stringOrNull(item.original_url) || "",
        cover_url: stringOrNull(item.cover_url) || "",
        window_kind: stringOrNull(item.window_kind) || "other",
        window_label: stringOrNull(item.window_label) || "",
        window_start: isoDate(item.window_start) || null,
        window_end: isoDate(item.window_end) || null,
      }))
      .filter((item) => item.original_url && item.cover_url);
    if (!items.length) continue;
    byClub[club] = items;
    overviewCount += items.length;
    for (const item of items) {
      kindCounts[item.window_kind] = (kindCounts[item.window_kind] || 0) + 1;
    }
  }

  return {
    schema_version: "club_overviews.v1",
    generated_at: stringOrNull(raw?.generated_at),
    as_of_date: isoDate(raw?.as_of_date) || null,
    source: stringOrNull(raw?.source),
    club_count: Object.keys(byClub).length,
    overview_count: overviewCount,
    kind_counts: kindCounts,
    by_club: byClub,
  };
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
  if (!text || localPathReason(text)) return "";
  return text.length > maxChars ? `${text.slice(0, maxChars).trim()}...` : text;
}

const INTERNAL_ONLY_PUBLIC_KEYS = new Set([
  "_source_url",
  "_source_aliases",
  "_score_confidence",
  "source_url",
  "raw_source_url",
  "sourceUrl",
  "confidence",
  "llm_confidence",
  "recommendation_reason",
  "article_dir",
  "source_evidence_path",
  "poster_vl_images",
  "emergency_qwen36_lineup_patch",
  "llm_input_path",
  "meta_path",
  "poster_ocr_path",
  "raw_html_path",
  "assets_json_path",
  "cache_article_dir",
  "local_path",
]);
const PUBLIC_URL_RE = /^(?:https?:\/\/|cloud:\/\/)\S+$/i;
const PUBLIC_ROUTE_RE = /^\/(?:api|assets?|static|images?|media|atlas|weekly|by-(?:id|city|date)|events?|artists?|venues?)(?:\/\S*)?$/i;
const FILE_URL_RE = /^file:(?:\/\/)?/i;
const WINDOWS_ABSOLUTE_PATH_RE = /(?:^|[\s"'=([{])(?:[a-z]:[\\/]|\\\\[^\\/\s]+[\\/][^\\/\s]+)/i;
const KNOWN_LOCAL_POSIX_ROOT_RE = /(?:^|[\s"'=([{])\/(?:home|mnt|srv|opt|tmp|var|root|Users|Volumes|workspace)(?:\/|$)/i;
const POSIX_ABSOLUTE_PATH_RE = /(?:^|[\s"'=([{])\/(?!\/)[^\s"'=()\[\]{}/]+(?:\/[^\s"'=()\[\]{}/]+)+/;

function isPublicRoute(text) {
  return !text.includes("\\") && PUBLIC_ROUTE_RE.test(text) && text.split("/").every((segment) => ![".", ".."].includes(segment));
}

function localPathReason(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (FILE_URL_RE.test(text)) return "file_url";
  if (WINDOWS_ABSOLUTE_PATH_RE.test(text)) return "windows_absolute_path";
  if (KNOWN_LOCAL_POSIX_ROOT_RE.test(text)) return "posix_absolute_path";
  if (isPublicRoute(text)) return "";
  if (POSIX_ABSOLUTE_PATH_RE.test(text)) return "posix_absolute_path";
  if (PUBLIC_URL_RE.test(text)) return "";
  return "";
}

function publicHttpUrl(value) {
  const text = String(value || "").trim();
  if (!text || localPathReason(text) || text.includes("\\")) return "";
  try {
    const parsed = new URL(text);
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) return "";
    if (parsed.username || parsed.password) return "";
    const hostname = parsed.hostname.toLowerCase().replace(/\.$/, "");
    if (hostname === "localhost" || hostname === "localhost.localdomain" || hostname.endsWith(".localhost")) return "";
    return text;
  } catch {
    return "";
  }
}

function scrubPublicValue(value) {
  if (typeof value === "string") return localPathReason(value) ? undefined : value;
  if (Array.isArray(value)) {
    return value.map(scrubPublicValue).filter((child) => child !== undefined);
  }
  if (value && typeof value === "object") {
    const output = {};
    for (const [key, child] of Object.entries(value)) {
      if (localPathReason(key)) continue;
      if (INTERNAL_ONLY_PUBLIC_KEYS.has(key)) continue;
      const cleaned = scrubPublicValue(child);
      if (cleaned !== undefined) output[key] = cleaned;
    }
    return output;
  }
  return value;
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
      const cleaned = scrubPublicValue(value[field]);
      if (cleaned !== undefined) output[field] = cleaned;
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
      const cleaned = scrubPublicValue(item[key]);
      if (cleaned !== undefined) output[key] = cleaned;
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

const DETAIL_COMPAT_FIELDS = [
  ...LIST_COMPAT_FIELDS,
  "schema_version",
  "content_type",
  "is_calendar_preview",
  "aggregation_child",
  "event_id",
  "article_id",
  "queue_id",
  "organizer_key",
  "club_profile",
  "posterUrl",
  "posterFileId",
  "cover_file_id",
  "coverFileId",
  "cloudFileId",
  "poster_storage",
  "posterStorage",
  "poster_cloud_path",
  "poster",
  "raw_cover_url",
  "poster_migrated_at",
  "poster_public_source_hash",
  "poster_suppressed",
  "poster_suppressed_reason",
  "main_poster_suppressed",
  "mainPosterSuppressed",
  "poster_selection_evidence",
  "posterSelectionEvidence",
  "poster_vl_lineup",
  "posterVlLineup",
  "poster_vl_lineup_evidence",
  "posterVlLineupEvidence",
  "event_date_range_explicit",
  "date_range_explicit",
  "is_date_range",
  "time_verification",
  "address_verification",
  "venue_verification",
  "geo_source",
  "geo_provider",
  "geo_reliability",
  "geo_level",
  "geo_provider_title",
  "geo_provider_address",
  "geo_reverse_address",
  "geo_verified_at",
  "geo_candidate_id",
  "geo_locked",
  "geo_override_reason",
  "map_search_aliases",
  "geo_search_aliases",
  "poi_aliases",
  "map_poi_name",
  "poi_id",
  "place_fields_locked",
  "lineup_display_hint",
  "lineup_quality",
  "evidence",
  "source_evidence",
  "source_evidence_text",
  "sound_system_evidence",
  "description",
  "digest",
  "summary",
  "summary_digest",
  "dj_bio_lines",
  "artist_profiles",
  "atlas_artists",
  "dj_discovery_sections",
  "dj_external_links",
  "sound_system",
  "sound_systems",
  "sound_system_text",
  "merge_provenance",
  "field_evidence_refs",
  "aggregation_source_kind",
  "dedupe_key",
  "discovery_source",
  "extraction_model",
  "metadata_enriched_at",
  "detail_path",
  "detail_url",
];

function withPublicDetailItem(rawItem) {
  const item = withClubProfile(rawItem);
  if (!item || typeof item !== "object") return item;
  const output = {};
  for (const key of DETAIL_COMPAT_FIELDS) {
    if (INTERNAL_ONLY_PUBLIC_KEYS.has(key)) continue;
    if (item[key] === undefined || item[key] === null || item[key] === "") continue;
    const cleaned = scrubPublicValue(item[key]);
    if (cleaned !== undefined) output[key] = cleaned;
  }
  const sourceAction = pickObjectFields(item.source_action, [
    "type", "label", "available", "url_hash", "disabled_reason",
  ]) || {};
  const sourceActionUrl = publicHttpUrl(item.source_action?.url);
  if (sourceActionUrl) sourceAction.url = sourceActionUrl;
  if (Object.keys(sourceAction).length > 0) output.source_action = sourceAction;
  const sourceArticle = pickObjectFields(item.source_article, [
    "url_hash", "title", "account_name", "published_at",
  ]) || {};
  const sourceArticleUrl = publicHttpUrl(item.source_article?.url);
  if (sourceArticleUrl) sourceArticle.url = sourceArticleUrl;
  if (Object.keys(sourceArticle).length > 0) output.source_article = sourceArticle;
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
      seen.set(
        duplicateKey,
        mergeDuplicateCityFields(seen.get(duplicateKey), item, mergeNonEmpty(seen.get(duplicateKey), item)),
      );
    } else {
      seen.set(
        duplicateKey,
        mergeDuplicateCityFields(item, seen.get(duplicateKey), mergeNonEmpty(item, seen.get(duplicateKey))),
      );
    }
  }
  return Array.from(seen.values());
}

// mtime-validated in-memory cache for the static release JSON package.
// current.json is 1.27MB and was re-read+parsed on every request before.
// The release dir only changes on deploy (new container) or test fixture edits,
// both of which change mtime, so the cache stays correct and never serves stale data.
// readJson results are never mutated by callers (verified: dedupe/sort/map build
// new arrays/objects), so returning the cached reference is safe.
const _jsonCache = new Map(); // fullPath -> { mtimeMs, data }

async function readJson(baseDir, relativePath) {
  const fullPath = path.resolve(baseDir, relativePath);
  // Prevent path traversal: resolved path must stay within baseDir
  const normalizedBase = path.resolve(baseDir);
  if (!fullPath.startsWith(normalizedBase + path.sep) && fullPath !== normalizedBase) {
    throw Object.assign(new Error(`Path traversal blocked: ${relativePath}`), { code: "PATH_TRAVERSAL" });
  }
  let mtimeMs = 0;
  try {
    mtimeMs = (await stat(fullPath)).mtimeMs;
    const cached = _jsonCache.get(fullPath);
    if (cached && cached.mtimeMs === mtimeMs) {
      return cached.data;
    }
  } catch {
    // stat failed (missing file etc.) — fall through so readFile throws the real error
  }
  const raw = await readFile(fullPath, "utf8");
  const data = JSON.parse(raw);
  if (mtimeMs) {
    _jsonCache.set(fullPath, { mtimeMs, data });
  }
  return data;
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
      let current = null;
      try {
        current = await readJson(this.baseDir, "current.json");
      } catch {
        current = null;
      }
      const generationId = assertPackageGeneration(current, raw);
      const expectedSchema = "weekly_activity_miniprogram_api.v1";
      if (raw.schema_version && raw.schema_version !== expectedSchema) {
        console.warn(
          `[dataStore] manifest schema drift: got "${raw.schema_version}", expected "${expectedSchema}"`,
        );
      }
      const sourceContract = safeSanjiSourceContract(raw);
      return {
        schema_version: raw.schema_version || expectedSchema,
        generated_at: raw.generated_at || raw.generatedAt || null,
        generation_id: generationId,
        generationId,
        item_count: raw.item_count ?? raw.items_total ?? 0,
        window_start: raw.window_start || raw.windowStart || null,
        window_end: raw.window_end || raw.windowEnd || null,
        pipeline: raw.pipeline,
        source_mode: sourceContract?.source_mode || null,
        direct_rss_feed_fetch: sourceContract?.direct_rss_feed_fetch ?? null,
        sanji_db_snapshot_export: sourceContract?.sanji_db_snapshot_export ?? null,
        sanji_desktop_refresh_invoked: sourceContract?.sanji_desktop_refresh_invoked ?? null,
        sanji_source_contract: sourceContract,
        field_resource_repair: raw.field_resource_repair || null,
        geocode_enrichment: raw.geocode_enrichment || null,
        id_consistency_repair: raw.id_consistency_repair || null,
      };
    } catch (err) {
      if (err?.code === "WEEKLY_GENERATION_HANDSHAKE_FAILED") throw err;
      console.error("[dataStore] getManifest failed:", err.message);
      throw Object.assign(new Error("weekly manifest is unavailable"), {
        code: "WEEKLY_MANIFEST_UNAVAILABLE",
        cause: err,
      });
    }
  }

  async getClubOverviews() {
    try {
      const raw = await readJson(this.baseDir, "club_overviews.json");
      if (raw?.schema_version && raw.schema_version !== "club_overviews.v1") {
        console.warn(
          `[dataStore] club_overviews.json schema drift: got "${raw.schema_version}", expected "club_overviews.v1"`,
        );
      }
      return normalizeClubOverviews(raw);
    } catch (err) {
      console.warn("[dataStore] club_overviews.json unavailable:", err.message);
      return normalizeClubOverviews(null);
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

  async getVisibleProjection({ cityKey, date, dateStart, dateEnd, lookbackDays, scope } = {}) {
    const current = await readJson(this.baseDir, "current.json");
    let manifest = null;
    try {
      manifest = await readJson(this.baseDir, "manifest.json");
    } catch {
      manifest = null;
    }
    const generationId = assertPackageGeneration(current, manifest);
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
    const visibilityScope = normalizeVisibilityScope(scope);
    const normalizedCityKey = String(cityKey || "").trim().toLowerCase();
    const exactDate = isoDate(date);
    const window = exactDate
      ? { dateStart: exactDate, dateEnd: exactDate }
      : normalizeDateWindow(dateStart, dateEnd);
    const today = this.todayDateKey();
    const lookback = normalizeLookbackDays(lookbackDays, DEFAULT_CURRENT_LOOKBACK_DAYS);
    const currentThreshold = !exactDate && !window.dateStart && lookback > 0 ? addDays(today, -lookback) : today;
    const filtered = (Array.isArray(current.items) ? current.items : []).filter((item) => {
      if (normalizedCityKey && normalizedCityKey !== "all" && !itemCityKeys(item).includes(normalizedCityKey)) return false;
      if (exactDate && !itemMatchesDate(item, exactDate)) return false;
      if (!exactDate && window.dateStart && !itemMatchesDateWindow(item, window.dateStart, window.dateEnd)) return false;
      if (visibilityScope === "current" && !exactDate && !window.dateStart && !itemIsCurrentOrFuture(item, currentThreshold)) {
        return false;
      }
      return item.quality_status === "READY" && isElectronicMusicRelevantItem(item);
    });
    const items = dedupeItems(filtered);
    items.sort((a, b) => {
      const aKey = isoDate(a.event_date_start) || itemDateKeys(a)[0] || "9999-12-31";
      const bKey = isoDate(b.event_date_start) || itemDateKeys(b)[0] || "9999-12-31";
      return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
    });
    return {
      current,
      generationId,
      items,
      filters: {
        scope: visibilityScope,
        cityKey: normalizedCityKey || null,
        date: exactDate || null,
        dateStart: window.dateStart || null,
        dateEnd: window.dateEnd || null,
        lookbackDays: visibilityScope === "current" && !exactDate && !window.dateStart ? (lookback || null) : null,
        today: today || null,
      },
    };
  }

  async getCurrent({ cityKey, date, dateStart, dateEnd, limit, cursor, lookbackDays, scope } = {}) {
    let current;
    let projection;
    try {
      projection = await this.getVisibleProjection({ cityKey, date, dateStart, dateEnd, lookbackDays, scope });
      current = projection.current;
    } catch (err) {
      if (err?.code === "WEEKLY_GENERATION_HANDSHAKE_FAILED") throw err;
      console.error("[dataStore] getCurrent failed to read current.json:", err.message);
      throw Object.assign(new Error("weekly current package is unavailable"), {
        code: "WEEKLY_CURRENT_UNAVAILABLE",
        cause: err,
      });
    }
    const pageLimit = normalizeLimit(limit);
    const pageCursor = normalizeCursor(cursor);
    const deduped = projection.items;
    const items = deduped.slice(pageCursor, pageCursor + pageLimit).map(withListCompatItem);
    const nextOffset = pageCursor + items.length;

    return {
      schemaVersion: "weekly_activity_api.current_response.v1",
      generatedAt: current.generated_at,
      generationId: projection.generationId,
      filters: projection.filters,
      page: {
        limit: pageLimit,
        cursor: String(pageCursor),
        nextCursor: nextOffset < deduped.length ? String(nextOffset) : null,
        total: deduped.length,
      },
      items,
    };
  }

  async getCities({ date, dateStart, dateEnd, lookbackDays, scope } = {}) {
    const projection = await this.getVisibleProjection({ date, dateStart, dateEnd, lookbackDays, scope });
    const cities = new Map();
    for (const item of projection.items) {
      const cityKeys = itemCityKeys(item);
      for (let index = 0; index < cityKeys.length; index += 1) {
        const key = cityKeys[index];
        const itemCount = (cities.get(key)?.item_count || 0) + 1;
        cities.set(key, {
          city_key: key,
          city: itemCityLabel(item, key, index),
          count: itemCount,
          item_count: itemCount,
          path: `by-city/${key}.json`,
        });
      }
    }
    return {
      schema_version: "weekly_activity_miniprogram_city_index.v2",
      generated_at: projection.current.generated_at || null,
      generation_id: projection.generationId,
      generationId: projection.generationId,
      scope: projection.filters.scope,
      filters: projection.filters,
      city_count: cities.size,
      item_count: projection.items.length,
      cities: [...cities.values()].sort((a, b) => b.item_count - a.item_count || a.city_key.localeCompare(b.city_key)),
    };
  }

  async getDates({ cityKey, date, dateStart, dateEnd, lookbackDays, scope } = {}) {
    const projection = await this.getVisibleProjection({ cityKey, date, dateStart, dateEnd, lookbackDays, scope });
    const dates = new Map();
    const windowStart = projection.filters.dateStart;
    const windowEnd = projection.filters.dateEnd;
    const currentFloor = projection.filters.scope === "current" && !windowStart
      ? (projection.filters.lookbackDays ? addDays(projection.filters.today, -projection.filters.lookbackDays) : projection.filters.today)
      : null;
    for (const item of projection.items) {
      for (const key of itemDateKeys(item)) {
        if (windowStart && (key < windowStart || key > windowEnd)) continue;
        if (currentFloor && key < currentFloor) continue;
        const itemCount = (dates.get(key)?.item_count || 0) + 1;
        dates.set(key, {
          date: key,
          count: itemCount,
          item_count: itemCount,
          path: `by-date/${key}.json`,
        });
      }
    }
    const entries = [...dates.values()].sort((a, b) => a.date.localeCompare(b.date));
    return {
      schema_version: "weekly_activity_miniprogram_date_index.v2",
      generated_at: projection.current.generated_at || null,
      generation_id: projection.generationId,
      generationId: projection.generationId,
      scope: projection.filters.scope,
      filters: projection.filters,
      date_count: entries.length,
      item_count: projection.items.length,
      dates: entries,
    };
  }

  async getPackageState({
    generationId,
    generation_id: generationIdSnake,
    generatedAt: requestedGeneratedAt,
    generated_at: requestedGeneratedAtSnake,
  } = {}) {
    const current = await readJson(this.baseDir, "current.json");
    let manifest = null;
    try {
      manifest = await readJson(this.baseDir, "manifest.json");
    } catch {
      manifest = null;
    }
    const activeGenerationId = assertPackageGeneration(current, manifest);
    const generatedAt = generatedAtOf(current) || generatedAtOf(manifest);
    if (!activeGenerationId && !generatedAt) {
      throw generationHandshakeError(null, null);
    }
    const requested = stringOrNull(generationId || generationIdSnake);
    if (requested && requested !== activeGenerationId) {
      throw requestedGenerationError(requested, activeGenerationId);
    }
    const requestedAt = stringOrNull(requestedGeneratedAt || requestedGeneratedAtSnake);
    if (requestedAt && (activeGenerationId || requestedAt !== generatedAt)) {
      throw requestedGenerationError(requestedAt, activeGenerationId || generatedAt);
    }
    return {
      current,
      manifest,
      generationId: activeGenerationId,
      generatedAt,
    };
  }

  async getReadiness() {
    const packageState = await this.getPackageState();
    if (!packageState.generationId) {
      throw Object.assign(new Error("weekly package has no deterministic generation"), {
        code: "WEEKLY_GENERATION_REQUIRED",
      });
    }
    const items = Array.isArray(packageState.current?.items) ? packageState.current.items : [];
    if (items.length === 0) {
      throw Object.assign(new Error("weekly package is empty"), { code: "WEEKLY_PACKAGE_EMPTY" });
    }
    const currentCount = Number(packageState.current?.item_count);
    const manifestCount = Number(packageState.manifest?.item_count ?? packageState.manifest?.items_total);
    if (!Number.isFinite(currentCount) || currentCount !== items.length || !Number.isFinite(manifestCount) || manifestCount !== items.length) {
      throw Object.assign(new Error("weekly package item count mismatch"), {
        code: "WEEKLY_PACKAGE_COUNT_MISMATCH",
      });
    }
    const ids = items.map((item) => String(item?.id || "").trim());
    const uniqueIds = new Set(ids);
    if (ids.some((id) => !id) || uniqueIds.size !== ids.length) {
      throw Object.assign(new Error("weekly package IDs are missing or duplicated"), {
        code: "WEEKLY_PACKAGE_ID_CLOSURE_FAILED",
      });
    }

    let derivedDetailCount = 0;
    for (const item of items) {
      const detail = await readJson(this.baseDir, `by-id/${storageSlug(item.id)}.json`);
      if (!detailMatchesPackage(detail, packageState, item)) {
        throw Object.assign(new Error(`weekly detail closure mismatch for ${item.id}`), {
          code: "WEEKLY_DETAIL_CLOSURE_FAILED",
        });
      }
      derivedDetailCount += 1;
    }

    const itemIdDigest = createHash("sha256")
      .update([...uniqueIds].sort().join("\n"), "utf8")
      .digest("hex");
    return {
      ok: true,
      service: "weekly-api",
      generationId: packageState.generationId,
      generatedAt: packageState.generatedAt,
      packageItemCount: items.length,
      derivedDetailCount,
      itemIdDigest,
    };
  }

  async getItem(id, options = {}) {
    const rawId = String(id || "").trim();
    const safeId = storageSlug(rawId);
    if (!safeId) return null;
    const packageState = await this.getPackageState(options);
    const currentItems = Array.isArray(packageState.current.items) ? packageState.current.items : [];
    const currentItem = currentItems.find(
      (entry) => entry.id === rawId || storageSlug(entry.id) === safeId,
    ) || null;
    try {
      const detail = await readJson(this.baseDir, `by-id/${safeId}.json`);
      if (detailMatchesPackage(detail, packageState, currentItem)) {
        return withPackageIdentity(detail.item || detail, packageState);
      }
    } catch {
      // A missing/corrupt detail route is safe to recover from current.json;
      // package handshake errors occur before this block and are never hidden.
    }
    return withPackageIdentity(currentItem, packageState);
  }

  async getItemsByIds(ids, options = {}) {
    const packageState = await this.getPackageState(options);
    const wanted = Array.isArray(ids)
      ? ids
        .map((id) => ({ raw: String(id || "").trim(), safe: storageSlug(id) }))
        .filter((entry) => entry.raw && entry.safe)
      : [];
    const currentItems = Array.isArray(packageState.current.items) ? packageState.current.items : [];
    const currentByRaw = new Map(currentItems.map((item) => [String(item.id || ""), item]));
    const currentBySafe = new Map(currentItems.map((item) => [storageSlug(item.id), item]));
    const found = await Promise.all(wanted.map(async (entry) => {
      const currentItem = currentByRaw.get(entry.raw) || currentBySafe.get(entry.safe) || null;
      try {
        const detail = await readJson(this.baseDir, `by-id/${entry.safe}.json`);
        if (detailMatchesPackage(detail, packageState, currentItem)) {
          return withPackageIdentity(detail.item || detail, packageState);
        }
      } catch {
        // Fall through to the validated current generation.
      }
      return withPackageIdentity(currentItem, packageState);
    }));
    return {
      items: found.filter(Boolean),
      generatedAt: packageState.generatedAt,
      generation_id: packageState.generationId,
      generationId: packageState.generationId,
    };
  }

  async getLlmSummary() {
    try {
      return scrubPublicValue(await readJson(this.baseDir, "llm/weekly_summary.json")) || null;
    } catch {
      return null;
    }
  }

  async getLlmEnrichmentIndex() {
    try {
      return scrubPublicValue(await readJson(this.baseDir, "llm/enrichment_index.json")) || null;
    } catch {
      return null;
    }
  }

  async getLlmEnrichment(id) {
    const safeId = storageSlug(id);
    if (!safeId) return null;

    try {
      return scrubPublicValue(await readJson(this.baseDir, `llm/enrichments/${safeId}.json`)) || null;
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
    const publicUrl = publicHttpUrl(source?.url);
    if (!publicUrl) return null;
    return {
      schemaVersion: "weekly_activity_api.source_action.v1",
      type: source.type || "wechat_article",
      mode: "webview",
      url: publicUrl,
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
