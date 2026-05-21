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
  const parsed = Number.parseInt(String(value ?? "20"), 10);
  if (!Number.isFinite(parsed)) return 20;
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

function itemDateKeys(item) {
  const dates = new Set();
  for (const key of ["event_date_start", "event_date_end", "event_date_iso_guess"]) {
    const value = isoDate(item[key]);
    if (value) dates.add(value);
  }
  for (const key of ["event_date_iso_guesses", "event_date_text"]) {
    const raw = item[key];
    const values = Array.isArray(raw) ? raw : [raw];
    for (const value of values) {
      const date = isoDate(value);
      if (date) dates.add(date);
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

function hasValue(value) {
  if (Array.isArray(value)) return value.some((item) => String(item || "").trim());
  return Boolean(String(value || "").trim());
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

function duplicateScopeKey(item) {
  return [dateKey(item), cityKey(item), venueKey(item)].join("|");
}

function sourceHash(item) {
  return String(item.source_action?.url_hash || item.source_article?.url_hash || "").trim();
}

function coverKey(item) {
  return String(item.cover_image_url || item.cover_url || item.coverUrl || "")
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
    (hasValue(item.cover_image_url || item.cover_url || item.coverUrl) ? 1 : 0)
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
      output[duplicateIndex] = item;
    }
  }
  return output;
}

async function readJson(baseDir, relativePath) {
  const fullPath = path.resolve(baseDir, relativePath);
  const raw = await readFile(fullPath, "utf8");
  return JSON.parse(raw);
}

export class WeeklyActivityDataStore {
  constructor(options = {}) {
    this.baseDir = options.baseDir || process.env.WEEKLY_ACTIVITY_API_DIR || DEFAULT_API_DIR;
    this.sourceMapDir =
      options.sourceMapDir ||
      process.env.WEEKLY_ACTIVITY_SOURCE_MAP_DIR ||
      path.resolve(this.baseDir, "../source_actions");
  }

  async getManifest() {
    const raw = await readJson(this.baseDir, "manifest.json");
    // Upstream Stage7 pipeline emits camelCase (`schemaVersion`, `generatedAt`, `items_total`)
    // while the miniprogram API contract uses snake_case (`schema_version`, `generated_at`, `item_count`).
    // Normalize here so consumers always see the contract shape regardless of upstream variant.
    return {
      schema_version: raw.schema_version || "weekly_activity_miniprogram_api.v1",
      generated_at: raw.generated_at || raw.generatedAt || null,
      item_count: raw.item_count ?? raw.items_total ?? 0,
      pipeline: raw.pipeline,
    };
  }

  async getCurrent({ cityKey, date, limit, cursor } = {}) {
    const current = await readJson(this.baseDir, "current.json");
    const pageLimit = normalizeLimit(limit);
    const pageCursor = normalizeCursor(cursor);
    const filtered = current.items.filter((item) => {
      if (cityKey && item.city_key !== cityKey && !(item.city_keys || []).includes(cityKey)) {
        return false;
      }
      if (date && !itemMatchesDate(item, date)) {
        return false;
      }
      return item.quality_status === "READY";
    });
    const deduped = dedupeItems(filtered);
    const items = deduped.slice(pageCursor, pageCursor + pageLimit);
    const nextOffset = pageCursor + items.length;

    return {
      schemaVersion: "weekly_activity_api.current_response.v1",
      generatedAt: current.generated_at,
      filters: {
        cityKey: cityKey || null,
        date: date || null,
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
      const cities = new Map();
      for (const item of current.items) {
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
      return await readJson(this.baseDir, "by-date/index.json");
    } catch {
      const current = await readJson(this.baseDir, "current.json");
      const dates = new Map();
      for (const item of current.items) {
        const itemDates = itemDateKeys(item);
        for (const date of itemDates.length ? itemDates : ["unknown"]) {
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
      return detail.item || detail;
    } catch {
      const current = await readJson(this.baseDir, "current.json");
      return current.items.find((item) => item.id === rawId || storageSlug(item.id) === safeId) || null;
    }
  }

  async getItemsByIds(ids) {
    if (!Array.isArray(ids) || ids.length === 0) return [];
    const wanted = ids
      .map((id) => ({ raw: String(id || "").trim(), safe: storageSlug(id) }))
      .filter((entry) => entry.raw && entry.safe);
    if (wanted.length === 0) return [];

    const found = [];
    const remaining = [];
    for (const entry of wanted) {
      try {
        const detail = await readJson(this.baseDir, `by-id/${entry.safe}.json`);
        found.push(detail.item || detail);
      } catch {
        remaining.push(entry);
      }
    }

    if (remaining.length > 0) {
      const current = await readJson(this.baseDir, "current.json");
      const rawIds = new Set(remaining.map((entry) => entry.raw));
      const safeIds = new Set(remaining.map((entry) => entry.safe));
      found.push(...current.items.filter((item) => rawIds.has(item.id) || safeIds.has(storageSlug(item.id))));
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
    const source = item?.cover_image_url || item?.cover_url || item?.coverUrl || "";
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
}
