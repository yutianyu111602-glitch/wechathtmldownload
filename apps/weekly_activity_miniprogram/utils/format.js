function first(value, fallback = "") {
  return Array.isArray(value) ? value[0] || fallback : value || fallback;
}

function joinList(value, fallback = "") {
  if (!Array.isArray(value) || value.length === 0) return fallback;
  return value.filter(Boolean).join(" / ");
}

const VERIFIED_ADDRESS_BOOK = [
  {
    keys: ["potent", "potentclub"],
    address: "上海市黄浦区淮海中路523号",
  },
  {
    keys: ["dadabarbeijing", "dada北京", "dadabeijing", "dada酒吧日坛国际贸易中心a座店"],
    address: "北京市朝阳区南营房胡同日坛国际贸易中心A座北门B1层",
  },
  {
    keys: ["莫须有工厂", "groundlessfactory", "groundless factory", "798cube莫须有工厂"],
    address: "北京市朝阳区酒仙桥路2号798艺术区706路B06-2",
  },
];

const STYLE_RULES = [
  { label: "hip-hop", aliases: ["hiphop", "hip hop", "hip-hop", "说唱", "嘻哈", "rap", "trap"] },
  { label: "techno", aliases: ["techno", "工业", "industrial techno"] },
  { label: "4x4", aliases: ["4x4", "four on the floor", "four-on-the-floor"] },
  { label: "house", aliases: ["house", "浩室"] },
  { label: "club trax", aliases: ["club trax", "club tracks", "club music", "club edits", "club edit"] },
  { label: "electro", aliases: ["electro", "电子放克"] },
  { label: "bass", aliases: ["bass", "低音"] },
  { label: "drum & bass", aliases: ["drum and bass", "drum&bass", "dnb", "d&b"] },
  { label: "breaks", aliases: ["breakbeat", "breaks", "碎拍"] },
  { label: "trance", aliases: ["trance"] },
  { label: "disco", aliases: ["disco", "迪斯科"] },
  { label: "ambient", aliases: ["ambient", "氛围"] },
];

const NON_ARTIST_LINEUP_NAMES = [
  "aurora",
  "aurorabj",
  "lineup",
  "support",
  "nighttour",
  "夜游",
  "阵容",
];

const TRUSTED_TIME_SOURCES = [
  "source_text",
  "article_text",
  "official_text",
  "poster_ocr",
  "poster_text",
  "manual_verified",
];

const LINEUP_PHRASE_RE = /(成员|创意|主理|呈现|你的身体|关于|一种|方式|系统|邀请|活动|本周|舞池|俱乐部|公众号|二维码|扫码|购票|票价|报名|厂牌|旗下|阵容|时间|地点|地址|日期|门票|weekly|lineup|presents?|pres\.|recordings|events)/i;
const DISPLAY_URL_RE = /https?:\/\/|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=|from=appmsg|#imgIndex=/i;
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

function compactDate(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return raw;
  return `${match[2]}.${match[3]}`;
}

function weekdayLabel(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return days[date.getDay()] || "";
}

function stripEmoji(value) {
  return String(value || "").replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, "").trim();
}

function isDisplayUrlLine(value) {
  return DISPLAY_URL_RE.test(String(value || ""));
}

function stripLeadingDateWords(value) {
  return String(value || "")
    .replace(/^\s*[「【\[]?\s*(今晚|今夜|本周|周末)\s*[」】\]]?\s*/i, "")
    .replace(/^\s*(\d{1,2})[./-](\d{1,2})(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*/i, "")
    .replace(/^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*/, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
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

function displayTitle(item) {
  if (item.title_display || item.display_title) return stripEmoji(item.title_display || item.display_title);
  const cleaned = removeEntityPrefix(stripLeadingDateWords(stripEmoji(item.title)), item)
    .replace(/\s+\d{1,2}[./-]\d{1,2}.*$/i, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
  return cleaned || stripEmoji(item.title) || "Untitled";
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

function posterUrl(item) {
  const raw = item.cover_image_url || item.cover_url || item.coverUrl || "";
  if (!raw) return "";
  const baseUrl = apiBaseUrl();
  if (baseUrl && item.id) return `${baseUrl}/api/v1/weekly/poster/${encodeURIComponent(item.id)}`;
  return raw;
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

function sourceHash(item) {
  return String(item.sourceHash || item.source_action?.url_hash || item.source_article?.url_hash || "").trim();
}

function coverKey(item) {
  return String(item.coverUrl || item.cover_image_url || item.cover_url || item.coverUrl || "")
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
  const signals = directStyleSignals(item).map(normalizeStyleSignal).filter(Boolean);
  const labels = [];
  for (const rule of STYLE_RULES) {
    const matched = rule.aliases.some((alias) => {
      const normalizedAlias = normalizeStyleSignal(alias);
      return signals.some((signal) => signal === normalizedAlias || signal === normalizeStyleSignal(rule.label));
    });
    if (matched && !labels.includes(rule.label)) labels.push(rule.label);
    if (labels.length >= 4) break;
  }
  return labels;
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
  if (item.address_full) return item.address_full;
  if (item.address) return item.address;
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

function compactItem(item) {
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
  const isoDate = item.event_date_start || item.event_date_iso_guess || "";
  const dateLabel = isoDate || first(item.event_date_text, "");
  const metaParts = [cityLabel, dateLabel].filter(Boolean);
  const coverUrl = posterUrl(item);
  const sourceHash = item.source_action?.url_hash || item.source_article?.url_hash || "";
  const interestSeed = `${item.id || item.article_id || item.title || ""}`.split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const descriptionLines = cleanDescriptionLines(item, bioLines);
  const atlasArtists = atlasArtistItems(item);
  return {
    ...item,
    coverUrl,
    sourceHash,
    hasSource: Boolean(sourceHash && item.source_action?.available !== false),
    cityLabel,
    displayTitle: displayTitle(item),
    dateLabel,
    dateCompact: compactDate(dateLabel),
    weekdayLabel: weekdayLabel(dateLabel),
    detailMetaLine: metaParts.join(" · "),
    cardLocationLabel,
    timeLabel,
    hasTime: Boolean(timeLabel),
    hasTrustedTime: Boolean(timeLabel),
    venueLabel,
    addressLabel,
    placeLabel,
    hasPlace: Boolean(placeLabel),
    hasVenue: Boolean(venueLabel),
    hasAddress: Boolean(addressLabel),
    musicStyles,
    styleLabel: joinList(musicStyles),
    hasStyle: musicStyles.length > 0,
    hasPrice: Array.isArray(item.price) && item.price.length > 0,
    lineupItems: cleanedLineup,
    lineupLabel: joinList(cleanedLineup),
    hasLineup: cleanedLineup.length > 0,
    lineupHint: "点击海报跳转公众号原文查看",
    hasLineupHint: hasRawLineup(item) && cleanedLineup.length === 0,
    bioLines,
    hasBio: bioLines.length > 0,
    atlasArtistItems: atlasArtists,
    hasAtlasArtistItems: atlasArtists.length > 0,
    descriptionLines,
    descriptionLead: descriptionLines[0] || "",
    hasDescription: descriptionLines.length > 0,
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
      output[duplicateIndex] = item;
    }
  }
  return output;
}

module.exports = {
  areLikelyDuplicateItems,
  atlasArtistItems,
  cleanLineup,
  compactDate,
  compactItem,
  dedupeItems,
  dedupeKeyForItem,
  displayTitle,
  extractEventTime,
  first,
  inferMusicStyles,
  isDisplayUrlLine,
  joinList,
  weekdayLabel,
};
