import path from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(moduleDir, "../../..");
const DEFAULT_SQLITE_DB = path.resolve(
  REPO_ROOT,
  "tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite",
);
const DEFAULT_SERVING_SQLITE_DB = path.resolve(
  REPO_ROOT,
  "reports/atlas_serving_activity_current_time_dedupe_strict_20260525-1625/atlas_serving.sqlite",
);
const KIND_TABLE = {
  articles: "articles",
  entities: "entities",
  events: "events",
};
const KIND_FTS = {
  articles: "article_fts",
  entities: "entity_fts",
  events: "event_fts",
};
const ID_FIELDS = {
  articles: ["article_id", "article_uid"],
  entities: ["eid"],
  events: ["evid"],
};
const ALLOWED_ADJUDICATION_ACTIONS = new Set(["accept", "reject", "needs_more_source", "hold", "review_only"]);
const ALLOWED_GEOCODE_REVIEW_ACTIONS = new Set(["accept", "reject", "needs_more_source", "hold", "review_only"]);
const GRAPH_EDGE_LIMIT = 120;
const SERVING_SUBJECT_TYPES = new Set(["dj", "venue", "organizer", "radio", "event"]);
const PROFILE_ALIAS_ENTITY_TYPES = new Set(["organization", "label", "brand", "group", "project", "venue", "club", "place", "location"]);
const PUBLIC_CITY_AS_PLACE_LABELS = new Set([
  "上海",
  "上海市",
  "北京",
  "北京市",
  "广州",
  "广州市",
  "深圳",
  "深圳市",
  "成都",
  "成都市",
  "武汉",
  "武汉市",
  "厦门",
  "厦门市",
  "昆明",
  "昆明市",
  "杭州",
  "杭州市",
  "重庆",
  "重庆市",
  "长沙",
  "长沙市",
  "西安",
  "西安市",
  "南京",
  "南京市",
  "苏州",
  "苏州市",
  "宁波",
  "宁波市",
  "天津",
  "天津市",
  "福州",
  "福州市",
  "青岛",
  "青岛市",
  "郑州",
  "郑州市",
  "沈阳",
  "沈阳市",
  "大连",
  "大连市",
  "香港",
  "台北",
  "shanghai",
  "beijing",
  "guangzhou",
  "shenzhen",
  "chengdu",
  "wuhan",
  "xiamen",
  "kunming",
  "hangzhou",
  "chongqing",
  "changsha",
  "xian",
  "xi'an",
  "nanjing",
  "suzhou",
  "ningbo",
  "tianjin",
  "fuzhou",
  "qingdao",
  "zhengzhou",
  "shenyang",
  "dalian",
  "hong kong",
  "taipei",
]);
const PUBLIC_NOISE_ENTITY_TYPES = new Set(["product", "menu", "menu_item", "drink", "beverage", "wine", "beer", "cocktail"]);
const PUBLIC_NOISE_TEXT_PATTERNS = [
  "酒单",
  "新酒",
  "葡萄酒",
  "白葡萄酒",
  "红葡萄酒",
  "红酒",
  "干白",
  "干红",
  "起泡酒",
  "香槟",
  "啤酒",
  "鸡尾酒",
  "威士忌",
  "whisky",
  "whiskey",
  "wine menu",
  "wine list",
  "wine",
  "beer",
  "cocktail",
  "餐厅",
  "菜单",
  "美食",
  "咖啡",
  "奶茶",
  "甜品",
  "火锅",
  "烧烤",
  "茶饮",
  "下午茶",
  "brunch",
  "restaurant",
  "cafe",
  "café",
  "coffee",
  "招聘",
  "兼职",
  "岗位",
  "简历",
  "调酒师招聘",
  "店长",
  "hiring",
  "job opening",
  "加入我们",
  "课程表",
  "瑜伽",
  "健身",
  "冥想",
  "疗愈",
  "声疗",
  "塔罗",
  "占星",
  "占卜",
  "读书会",
  "艺术展",
  "艺术展映",
  "影像展",
  "画展",
  "画廊",
  "厕所展览",
  "电影",
  "放映",
  "观影",
  "戏剧",
  "话剧",
  "脱口秀",
  "促销精选",
  "优惠券",
  "折扣",
  "团购",
  "香水",
  "美妆",
  "护肤",
  "化妆品",
  "口红",
  "民宿",
  "酒店推荐",
  "周边酒店",
];
const GRAPH_KIND_ALIASES = new Map([
  ["article", "articles"],
  ["articles", "articles"],
  ["source", "articles"],
  ["sources", "articles"],
  ["entity", "entities"],
  ["entities", "entities"],
  ["person", "entities"],
  ["people", "entities"],
  ["venue", "entities"],
  ["venues", "entities"],
  ["club", "entities"],
  ["clubs", "entities"],
  ["label", "entities"],
  ["labels", "entities"],
  ["event", "events"],
  ["events", "events"],
]);

function text(value) {
  return String(value ?? "").trim();
}

function envFlag(value) {
  return ["1", "true", "yes", "on"].includes(String(value ?? "").trim().toLowerCase());
}

function sqliteTableExists(db, tableName) {
  return Boolean(db.prepare("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1").get(tableName));
}

function sqliteCount(db, tableName) {
  if (!sqliteTableExists(db, tableName)) return 0;
  return Number(db.prepare(`SELECT COUNT(*) AS count FROM ${tableName}`).get()?.count || 0);
}

function normalizeLimit(value, fallback = 20, max = 200) {
  const parsed = Number.parseInt(String(value ?? fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, 1), max);
}

function normalizeOffset(value) {
  const parsed = Number.parseInt(String(value ?? "0"), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function maybeJson(value, fallback) {
  const raw = text(value);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function textPreview(value, maxLength = 700) {
  const normalized = text(value).replace(/\s+/g, " ");
  if (!normalized) return "";
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

function safePublicAssetUrl(value) {
  const raw = text(value);
  if (!raw || raw.length > 500 || /[\u0000-\u001f\s]/.test(raw)) return "";
  if (!raw.startsWith("/atlas-assets/")) return "";
  try {
    const decoded = decodeURIComponent(raw);
    if (decoded.includes("..") || decoded.includes("\\") || decoded.includes("//")) return "";
  } catch {
    return "";
  }
  return raw;
}

function safeExternalUrl(value) {
  const raw = text(value);
  if (!raw || raw.length > 800 || /[\u0000-\u001f\s]/.test(raw)) return "";
  try {
    const parsed = new URL(raw);
    if (!["http:", "https:"].includes(parsed.protocol)) return "";
    return parsed.toString();
  } catch {
    return "";
  }
}

function linkDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return "";
  }
}

function normalizeAssetLink(value, fallbackLabel = "profile") {
  const rawUrl = typeof value === "string" ? value : value?.url || value?.href || value?.profileUrl || value?.profile_url;
  const url = safeExternalUrl(rawUrl);
  if (!url) return null;
  const domain = linkDomain(url);
  const label = text(typeof value === "object" ? value.label || value.title || value.domain || value.kind || value.type : fallbackLabel) || domain || fallbackLabel;
  return {
    label: textPreview(label, 64),
    url,
    domain,
    kind: textPreview(typeof value === "object" ? value.kind || value.type || "" : "", 32),
  };
}

function normalizeAssetEntry(entry = {}) {
  const avatarUrl = safePublicAssetUrl(entry.avatarUrl || entry.avatar_url || entry.imageUrl || entry.image_url || entry.photoUrl || entry.photo_url);
  const linkCandidates = [];
  for (const key of ["profileUrl", "profile_url", "homepage", "website", "instagram", "soundcloud", "bandcamp", "residentAdvisor", "raUrl", "ra_url"]) {
    if (entry[key]) linkCandidates.push({ label: key, url: entry[key], kind: key });
  }
  if (Array.isArray(entry.externalLinks)) linkCandidates.push(...entry.externalLinks);
  if (Array.isArray(entry.outlinks)) linkCandidates.push(...entry.outlinks);
  if (Array.isArray(entry.links)) linkCandidates.push(...entry.links);
  const seen = new Set();
  const externalLinks = [];
  for (const candidate of linkCandidates) {
    const link = normalizeAssetLink(candidate);
    if (!link || seen.has(link.url)) continue;
    seen.add(link.url);
    externalLinks.push(link);
    if (externalLinks.length >= 8) break;
  }
  return {
    avatarUrl,
    externalLinks,
    source: textPreview(entry.source || entry.assetSource || entry.asset_source || "", 64),
    updatedAt: textPreview(entry.updatedAt || entry.updated_at || "", 40),
  };
}

function normalizeGraphAssetManifest(raw) {
  const map = new Map();
  const entries = [];
  const pushEntry = (entry, idHint = "") => {
    if (!entry || typeof entry !== "object") return;
    entries.push({ ...entry, idHint });
  };
  if (Array.isArray(raw)) {
    raw.forEach((entry) => pushEntry(entry));
  } else if (raw && typeof raw === "object") {
    if (Array.isArray(raw.items)) raw.items.forEach((entry) => pushEntry(entry));
    if (Array.isArray(raw.entities)) raw.entities.forEach((entry) => pushEntry(entry));
    if (raw.entities && !Array.isArray(raw.entities) && typeof raw.entities === "object") {
      Object.entries(raw.entities).forEach(([key, entry]) => pushEntry(entry, key));
    }
    if (raw.nodes && typeof raw.nodes === "object") {
      Object.entries(raw.nodes).forEach(([key, entry]) => pushEntry(entry, key));
    }
  }
  for (const entry of entries) {
    const asset = normalizeAssetEntry(entry);
    if (!asset.avatarUrl && asset.externalLinks.length === 0) continue;
    const ids = [
      entry.nodeId,
      entry.node_id,
      entry.id,
      entry.eid,
      entry.entityId,
      entry.entity_id,
      entry.artistId,
      entry.artist_id,
      entry.primaryId,
      entry.primary_id,
      entry.idHint,
    ].map(text).filter(Boolean);
    for (const id of ids) {
      map.set(id, asset);
      if (!id.includes(":")) map.set(`entities:${id}`, asset);
    }
  }
  return map;
}

function ftsQuery(value) {
  const raw = text(value).replace(/"/g, '""');
  return raw ? `"${raw}"` : "";
}

function normalizeSearchText(value) {
  return text(value).toLowerCase().replace(/\s+/g, " ");
}

function profileNameKey(value) {
  return normalizeSearchText(value).replace(/[^a-z0-9\u4e00-\u9fff]+/g, "");
}

function profileAliasTokens(value) {
  return normalizeSearchText(value)
    .split(/[^a-z0-9\u4e00-\u9fff]+/g)
    .map((part) => profileNameKey(part))
    .filter(Boolean);
}

function profileAliasMatches(query, candidate) {
  const queryKey = profileNameKey(query);
  const candidateKey = profileNameKey(candidate);
  if (!queryKey || !candidateKey) return false;
  if (candidateKey === queryKey) return true;
  if (profileAliasTokens(candidate).includes(queryKey)) return true;
  if (candidateKey.startsWith(queryKey)) {
    const next = candidateKey.slice(queryKey.length, queryKey.length + 1);
    if (next && /[\u4e00-\u9fff]/u.test(next)) return true;
  }
  if (candidateKey.endsWith(queryKey)) {
    const prefix = candidateKey.slice(0, -queryKey.length);
    if (prefix && /^[\u4e00-\u9fff]+$/u.test(prefix)) return true;
  }
  return false;
}

const SERVING_ALIAS_GENERIC_KEYS = ["club", "clubs", "俱乐部"];
const SERVING_ALIAS_CITY_KEYS = Array.from(PUBLIC_CITY_AS_PLACE_LABELS)
  .map((item) => profileNameKey(item))
  .filter(Boolean)
  .sort((a, b) => b.length - a.length);
const SERVING_ALIAS_ENTITY_TYPES = ["dj", "venue", "organizer", "radio"];

function stripServingAliasBoundary(key, tokens) {
  for (const token of tokens) {
    if (!token || key === token || key.length <= token.length) continue;
    if (key.startsWith(token)) return key.slice(token.length);
    if (key.endsWith(token)) return key.slice(0, -token.length);
  }
  return "";
}

function servingCanonicalAliasKeys(value) {
  const base = profileNameKey(value);
  if (!base) return [];
  const seen = new Set();
  const queue = [base];
  const output = [];
  const add = (key) => {
    const item = text(key);
    if (!item || seen.has(item)) return;
    seen.add(item);
    output.push(item);
    queue.push(item);
  };
  add(base);
  for (let index = 0; index < queue.length && index < 32; index += 1) {
    const key = queue[index];
    add(stripServingAliasBoundary(key, SERVING_ALIAS_CITY_KEYS));
    add(stripServingAliasBoundary(key, SERVING_ALIAS_GENERIC_KEYS));
  }
  return output;
}

function servingSubjectMatchesAliasKeys(row, queryKeys) {
  if (!row || !queryKeys?.length) return false;
  const keys = new Set(queryKeys);
  const rowKeys = [
    profileNameKey(row.display_name),
    profileNameKey(row.normalized_name),
    ...profileAliasTokens(row.aliases_text),
    ...servingCanonicalAliasKeys(row.display_name),
  ].filter(Boolean);
  return rowKeys.some((key) => keys.has(key));
}

function servingAliasRank(row, queryKeys, preferredKeys = []) {
  const displayKey = profileNameKey(row?.display_name);
  const normalizedKey = profileNameKey(row?.normalized_name);
  const aliasKeys = profileAliasTokens(row?.aliases_text);
  const rowKeys = new Set([displayKey, normalizedKey, ...aliasKeys, ...servingCanonicalAliasKeys(row?.display_name)].filter(Boolean));
  if (preferredKeys.some((key) => displayKey === key || normalizedKey === key || aliasKeys.includes(key))) return 0;
  if (queryKeys.length && (displayKey === queryKeys[0] || normalizedKey === queryKeys[0] || aliasKeys.includes(queryKeys[0]))) return 1;
  if (preferredKeys.some((key) => rowKeys.has(key))) return 2;
  if (queryKeys.some((key) => rowKeys.has(key))) return 3;
  return 4;
}

function dedupeServingRows(rows) {
  const seen = new Set();
  const output = [];
  for (const row of rows || []) {
    const id = text(row?.subject_id);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    output.push(row);
  }
  return output;
}

function isPublicCityAsPlaceLabel(value) {
  const raw = normalizeSearchText(value);
  return Boolean(raw && PUBLIC_CITY_AS_PLACE_LABELS.has(raw));
}

function isShortCjkSearchLabel(value) {
  return /^[\u4e00-\u9fff]{1,2}$/u.test(profileNameKey(value));
}

function canExpandProfileAliases(seedRows) {
  return seedRows.some((row) => PROFILE_ALIAS_ENTITY_TYPES.has(text(row.type).toLowerCase()));
}

function rowTitle(row) {
  return text(row.title || row.name || row.article_uid || row.source_article_uid || row.eid || row.evid || row.article_id);
}

function shouldScopeLocalId(value) {
  return /^local:/i.test(text(value));
}

function encodeScopedPublicId(sourceArticleUid, localId) {
  const source = text(sourceArticleUid);
  const id = text(localId);
  if (!source || !id || !shouldScopeLocalId(id)) return id;
  return `src:${Buffer.from(JSON.stringify([source, id]), "utf8").toString("base64url")}`;
}

function decodeScopedPublicId(value) {
  const raw = text(value);
  if (!raw.startsWith("src:")) return null;
  try {
    const decoded = JSON.parse(Buffer.from(raw.slice(4), "base64url").toString("utf8"));
    if (!Array.isArray(decoded) || decoded.length < 2) return null;
    const sourceArticleUid = text(decoded[0]);
    const localId = text(decoded[1]);
    return sourceArticleUid && localId ? { sourceArticleUid, localId } : null;
  } catch {
    return null;
  }
}

function rowSearchHaystack(row, kind) {
  const fields = [
    rowTitle(row),
    row.type,
    row.city,
    row.place,
    row.source_article_uid,
    row.source_account,
    row.time_text,
    row.vector_text_preview,
    row.bio,
    row.evidence_quote,
  ];
  if (kind === "events") fields.push(...maybeJson(row.participants_json, []), ...maybeJson(row.organizers_json, []));
  if (kind === "entities") fields.push(...maybeJson(row.aliases_json, []));
  return normalizeSearchText(fields.join(" "));
}

function searchRank(row, kind, queryText) {
  const query = normalizeSearchText(queryText);
  if (!query) return 100;
  const title = normalizeSearchText(rowTitle(row));
  const localId = normalizeSearchText(kind === "entities" ? row.eid : kind === "events" ? row.evid : row.article_uid || row.article_id);
  const aliases = kind === "entities" ? maybeJson(row.aliases_json, []).map(normalizeSearchText) : [];
  const participants = kind === "events" ? maybeJson(row.participants_json, []).map(normalizeSearchText) : [];
  if (title === query || aliases.includes(query) || localId === query) return 0;
  if (title.startsWith(query)) return 1;
  if (title.includes(query) || aliases.some((alias) => alias.includes(query))) return 2;
  if (participants.includes(query)) return 3;
  if (participants.some((name) => name.includes(query))) return 4;
  return rowSearchHaystack(row, kind).includes(query) ? 10 : 50;
}

function sortedSearchRows(rows, kind, queryText) {
  return [...rows].sort((a, b) => {
    const rankDelta = searchRank(a, kind, queryText) - searchRank(b, kind, queryText);
    if (rankDelta) return rankDelta;
    const confidenceDelta = Number(b.confidence || 0) - Number(a.confidence || 0);
    if (confidenceDelta) return confidenceDelta;
    return Number(a.row_pk || 0) - Number(b.row_pk || 0);
  });
}

function isPublicAtlasNoise(row, kind) {
  if (!row) return false;
  const rowKind = text(kind);
  const rowType = text(row.type).toLowerCase();
  const title = rowTitle(row).toLowerCase();
  const sourceTitle = text(row.source_title).toLowerCase();
  const preview = text(row.vector_text_preview).toLowerCase();
  const bio = text(row.bio).toLowerCase();
  const evidence = text(row.evidence_quote).toLowerCase();
  const timeText = text(row.time_text).toLowerCase();
  const place = text(row.place).toLowerCase();
  const aliases = text(row.aliases_json).toLowerCase();
  const participants = text(row.participants_json).toLowerCase();
  const organizers = text(row.organizers_json).toLowerCase();
  const sourceAccount = text(row.source_account).toLowerCase();
  const haystack = [title, sourceTitle, preview, bio, evidence, timeText, place, aliases, participants, organizers, sourceAccount].join(" ");
  if (rowKind === "entities" && PUBLIC_NOISE_ENTITY_TYPES.has(rowType)) return true;
  if (rowKind === "articles" && PUBLIC_NOISE_TEXT_PATTERNS.some((pattern) => haystack.includes(pattern))) return true;
  if ((rowKind === "entities" || rowKind === "events") && PUBLIC_NOISE_TEXT_PATTERNS.some((pattern) => haystack.includes(pattern))) return true;
  return false;
}

function publicRows(rows, kind, limit = rows.length) {
  return rows.filter((row) => !isPublicAtlasNoise(row, kind)).slice(0, limit);
}

function primaryDetailId(row, kind) {
  if (kind === "entities" || kind === "events") {
    const field = kind === "entities" ? "eid" : "evid";
    const localId = text(row[field]);
    const scopedId = encodeScopedPublicId(row.source_article_uid, localId);
    if (scopedId) return scopedId;
  }
  for (const field of ID_FIELDS[kind] || []) {
    const value = text(row[field]);
    if (value) return value;
  }
  return "";
}

function compactArticle(row) {
  return {
    article_id: row.article_id || "",
    article_uid: row.article_uid || "",
    title: row.title || "",
    source_account: row.source_account || "",
    publish_time_status: row.publish_time_status || "",
    public_snippet: textPreview(row.public_snippet || row.vector_text_preview || row.title || "", 180),
    entity_count: row.entity_count || 0,
    event_count: row.event_count || 0,
    quality_grade: row.quality_grade || "",
  };
}

function compactEntity(row) {
  return {
    eid: row.eid || "",
    name: row.name || "",
    type: row.type || "",
    city: row.city || "",
    source_article_uid: row.source_article_uid || "",
    confidence: row.confidence ?? null,
  };
}

function compactEvent(row) {
  return {
    evid: row.evid || "",
    name: row.name || "",
    place: row.place || "",
    city: row.city || "",
    time_iso: row.time_iso || "",
    time_text: row.time_text || "",
    participants: maybeJson(row.participants_json, []).slice(0, 20),
    source_article_uid: row.source_article_uid || "",
    confidence: row.confidence ?? null,
  };
}

function compactRow(row, kind) {
  if (!row) return null;
  if (kind === "articles") return compactArticle(row);
  if (kind === "entities") return compactEntity(row);
  return compactEvent(row);
}

function chunkValues(values, size = 900) {
  const chunks = [];
  for (let i = 0; i < values.length; i += size) {
    chunks.push(values.slice(i, i + size));
  }
  return chunks;
}

function uniqueTexts(values, limit = 100_000) {
  const seen = new Set();
  const output = [];
  for (const value of values) {
    const item = text(value);
    if (!item || seen.has(item)) continue;
    seen.add(item);
    output.push(item);
    if (output.length >= limit) break;
  }
  return output;
}

function countBy(map, key, increment = 1, sample = "") {
  const normalizedKey = text(key);
  if (!normalizedKey) return;
  const current = map.get(normalizedKey) || { label: normalizedKey, count: 0, sample: "" };
  current.count += increment;
  if (sample && !current.sample) current.sample = sample;
  map.set(normalizedKey, current);
}

function topCounts(map, limit = 20) {
  return Array.from(map.values())
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, limit);
}

function publicEvidence(row, kind) {
  return {
    kind,
    title: row.title || row.name || "",
    sourceArticleUid: row.source_article_uid || row.article_uid || "",
    sourceAccount: row.source_account || "",
    publishTimeStatus: row.publish_time_status || "",
    qualityGrade: row.quality_grade || "",
    type: row.type || "",
    city: row.city || "",
    place: row.place || "",
    timeIso: row.time_iso || "",
    timeText: row.time_text || "",
    aliases: maybeJson(row.aliases_json, []).slice(0, 20),
    participants: maybeJson(row.participants_json, []).slice(0, 30),
    organizers: maybeJson(row.organizers_json, []).slice(0, 20),
    vectorTextPreview: textPreview(row.vector_text_preview),
  };
}

function normalizeGraphKind(value) {
  const raw = text(value).toLowerCase();
  const kind = GRAPH_KIND_ALIASES.get(raw) || raw;
  return KIND_TABLE[kind] ? kind : "";
}

function parseGraphNodeId(value) {
  const raw = text(value);
  const match = raw.match(/^(articles|entities|events):(.+)$/);
  if (!match) return null;
  return { kind: match[1], id: match[2] };
}

function graphNodeId(kind, row) {
  const primaryId = primaryDetailId(row, kind);
  return primaryId ? `${kind}:${primaryId}` : "";
}

function graphSubtype(row, kind) {
  if (kind === "articles") return "article";
  if (kind === "events") return "event";
  return text(row.type) || "entity";
}

function graphWeight(row, kind) {
  if (kind === "articles") return Math.max(2, Math.min(14, Number(row.entity_count || 0) + Number(row.event_count || 0)));
  if (kind === "events") return Math.max(2, Math.min(10, Math.round(Number(row.confidence || 0.4) * 10)));
  return Math.max(2, Math.min(10, Math.round(Number(row.confidence || 0.4) * 10)));
}

function graphNode(row, kind, attrs = {}) {
  if (isPublicAtlasNoise(row, kind)) return null;
  const primaryId = primaryDetailId(row, kind);
  if (!primaryId) return null;
  const sourceArticleUid = text(row.source_article_uid || row.article_uid);
  const asset = attrs.asset || {};
  const externalLinks = Array.isArray(asset.externalLinks) ? asset.externalLinks : [];
  return {
    id: `${kind}:${primaryId}`,
    kind,
    primaryId,
    label: rowTitle(row) || primaryId,
    subtype: graphSubtype(row, kind),
    city: text(row.city || row.city_label),
    place: text(row.place),
    sourceArticleUid,
    sourceAccount: text(row.source_account),
    detailHref: `/atlas/${kind}/${encodeURIComponent(primaryId)}`,
    weight: graphWeight(row, kind),
    summary: textPreview(row.vector_text_preview || row.bio || row.evidence_quote || row.title || row.name, 220),
    seed: Boolean(attrs.seed),
    role: graphNodeRole({ kind, seed: Boolean(attrs.seed) }, attrs),
    confidence: Number.isFinite(Number(row.confidence)) ? Number(row.confidence) : null,
    publicState: text(row.public_state || attrs.publicState) || "public_rollup",
    metrics: {
      weight: graphWeight(row, kind),
      degreeHint: 0,
      eventCount: Number(row.event_count || 0),
      relationCount: Number(row.relation_count || 0),
      sourceCount: Number(row.source_count || row.entity_count || 0),
      rankScore: Number(row.rank_score || 0),
    },
    visual: {
      avatarUrl: asset.avatarUrl || "",
      hasAvatar: Boolean(asset.avatarUrl),
      color: graphNodeColor(kind, graphSubtype(row, kind)),
      size: graphVisualSize(graphWeight(row, kind)),
    },
    externalLinks,
    hasExternalLinks: externalLinks.length > 0,
  };
}

function graphSafety() {
  return {
    modelCallExecuted: false,
    llmCallExecuted: false,
    qdrantWriteExecuted: false,
    qdrantAliasChangeExecuted: false,
    neo4jWriteExecuted: false,
    mem0WriteExecuted: false,
    sqliteWriteExecuted: false,
    bulkExportEnabled: false,
  };
}

const GRAPH_NODE_COLORS = {
  article: "#76808a",
  event: "#c85f3c",
  dj: "#18a8b8",
  person: "#18a8b8",
  venue: "#c28a2d",
  club: "#c28a2d",
  place: "#c28a2d",
  location: "#c28a2d",
  organization: "#2f8f5b",
  organizer: "#2f8f5b",
  label: "#2f8f5b",
  brand: "#2f8f5b",
  group: "#2f8f5b",
  project: "#2f8f5b",
  entity: "#376f8f",
};

function graphNodeColor(kind, subtype) {
  const rawSubtype = text(subtype).toLowerCase();
  if (GRAPH_NODE_COLORS[rawSubtype]) return GRAPH_NODE_COLORS[rawSubtype];
  if (kind === "articles") return GRAPH_NODE_COLORS.article;
  if (kind === "events") return GRAPH_NODE_COLORS.event;
  return GRAPH_NODE_COLORS.entity;
}

function normalizeGraphLod(value, fallback = "focus") {
  const raw = text(value).toLowerCase();
  if (["overview", "focus", "detail"].includes(raw)) return raw;
  return fallback;
}

function graphClusterId(node) {
  const subtype = text(node.subtype).toLowerCase();
  if (subtype === "dj" || subtype === "person" || subtype === "artist") return "cluster:dj";
  if (subtype === "event" || node.kind === "events") return "cluster:event";
  if (["venue", "club", "place", "location"].includes(subtype)) return "cluster:venue";
  if (["organization", "organizer", "label", "brand", "group", "project"].includes(subtype)) return "cluster:org";
  if (node.kind === "articles") return "cluster:evidence";
  return "cluster:entity";
}

function graphNodeRole(node, attrs = {}) {
  const role = text(node.role || attrs.role);
  if (role) return role;
  if (node.seed || attrs.seed) return "seed";
  if (node.kind === "events") return "event";
  if (node.kind === "articles") return "evidence";
  return "related";
}

function graphVisualSize(weight) {
  return Math.max(5, Math.min(26, 5 + Number(weight || 2)));
}

function graphNodeTimeline(node, metrics) {
  if (Array.isArray(node.timeline) && node.timeline.length) return node.timeline.slice(0, 4);
  const items = [];
  const time = text(node.starts_at || node.time_iso || node.timeText || node.time_text || node.generatedAt || "Atlas");
  const title = text(node.event_title || node.title || node.label || node.name || node.id || "Atlas 记录");
  const detail = text(node.summary || node.place || node.city || node.sourceAccount || node.source_article_uid || node.sourceArticleUid);
  if (title || detail) {
    items.push({
      time: time || "Atlas",
      title: title || "Atlas 记录",
      detail: detail || `活动 ${metrics.eventCount || 0}，关系 ${metrics.relationCount || 0}。`,
    });
  }
  return items;
}

function enrichGraphNodeDto(node, attrs = {}) {
  const weight = Number(node.weight || attrs.weight || 2);
  const confidence = Number.isFinite(Number(node.confidence ?? attrs.confidence))
    ? Number(node.confidence ?? attrs.confidence)
    : null;
  const subtype = text(node.subtype || attrs.subtype || "entity");
  const role = graphNodeRole(node, attrs);
  const label = text(node.label || node.name || node.title || node.id);
  const explicitScore = Number(node.score ?? node.metrics?.rankScore ?? node.rankScore ?? 0);
  const metrics = {
    weight,
    degreeHint: Number(attrs.degreeHint ?? node.metrics?.degreeHint ?? node.degreeHint ?? 0),
    eventCount: Number(attrs.eventCount ?? node.metrics?.eventCount ?? node.eventCount ?? 0),
    relationCount: Number(attrs.relationCount ?? node.metrics?.relationCount ?? node.relationCount ?? 0),
    sourceCount: Number(attrs.sourceCount ?? node.metrics?.sourceCount ?? node.sourceCount ?? 0),
    rankScore: Number(attrs.rankScore ?? node.metrics?.rankScore ?? node.rankScore ?? 0),
    ...node.metrics,
  };
  return {
    ...node,
    name: text(node.name) || label,
    type: text(node.type) || subtype,
    score: Number.isFinite(explicitScore) && explicitScore > 0 ? explicitScore : weight,
    events: Number(node.events ?? node.metrics?.eventCount ?? metrics.eventCount ?? 0),
    links: Number(node.links ?? node.metrics?.relationCount ?? metrics.relationCount ?? metrics.degreeHint ?? 0),
    timeline: graphNodeTimeline({ ...node, label }, metrics),
    role,
    clusterId: text(node.clusterId || attrs.clusterId) || graphClusterId({ ...node, subtype }),
    metrics,
    confidence,
    publicState: text(node.publicState || attrs.publicState || node.public_state) || "public_rollup",
    visual: {
      ...(node.visual || {}),
      color: text(node.visual?.color || attrs.color) || graphNodeColor(node.kind, subtype),
      size: Number(node.visual?.size || attrs.size || graphVisualSize(weight)),
      zBias: Number(node.visual?.zBias ?? attrs.zBias ?? (role === "seed" ? 30 : 0)),
      hasAvatar: Boolean(node.visual?.hasAvatar || attrs.hasAvatar),
    },
  };
}

function sampleEvidenceIds(value) {
  const raw = Array.isArray(value) ? value : maybeJson(value, []);
  const ids = [];
  for (const item of raw) {
    const id = text(typeof item === "string" ? item : item?.evidence_ref_id || item?.source_ref_id || item?.id);
    if (id && !ids.includes(id)) ids.push(id);
    if (ids.length >= 8) break;
  }
  return ids;
}

function finiteNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const PROFILE_MERGE_AGGREGATION_LIMITS = Object.freeze({
  total: 96,
  dj: 48,
  venue: 32,
  organizer: 32,
  radio: 16,
  event: 12,
  entity: 12,
  other: 12,
});

function servingRowRankScore(row) {
  return finiteNumber(row?.rank_score ?? row?.rankScore, 0);
}

function servingProfileAggregationRows(rows, seed, limits = PROFILE_MERGE_AGGREGATION_LIMITS) {
  const allRows = dedupeServingRows([seed, ...(rows || [])].filter(Boolean));
  const totalLimit = Math.max(1, finiteNumber(limits.total, 96));
  const selected = [];
  const selectedIds = new Set();
  const add = (row) => {
    const id = text(row?.subject_id);
    if (!id || selectedIds.has(id) || selected.length >= totalLimit) return false;
    selectedIds.add(id);
    selected.push(row);
    return true;
  };
  const seedId = text(seed?.subject_id);
  const rankedRows = allRows
    .slice()
    .sort((a, b) => {
      const aSeed = text(a?.subject_id) === seedId ? 1 : 0;
      const bSeed = text(b?.subject_id) === seedId ? 1 : 0;
      return bSeed - aSeed
        || servingRowRankScore(b) - servingRowRankScore(a)
        || text(a?.display_name).localeCompare(text(b?.display_name));
    });
  add(seed);
  const typeOrder = ["dj", "venue", "organizer", "radio", "event", "entity"];
  for (const typeName of typeOrder) {
    const typeLimit = Math.max(0, finiteNumber(limits[typeName], limits.other));
    if (!typeLimit) continue;
    let used = selected.filter((row) => text(row?.subject_type) === typeName).length;
    for (const row of rankedRows) {
      if (used >= typeLimit || selected.length >= totalLimit) break;
      if (text(row?.subject_type) !== typeName) continue;
      if (add(row)) used += 1;
    }
  }
  for (const row of rankedRows) {
    if (selected.length >= totalLimit) break;
    add(row);
  }
  return selected;
}

function graphRelationshipScore(edge) {
  const explicit = edge.relationshipScore
    ?? edge.relationship_score
    ?? edge.relationScore
    ?? edge.relation_score
    ?? edge.score;
  if (explicit !== undefined && explicit !== null && text(explicit) !== "") return finiteNumber(explicit, 0);
  if (["dj_collaboration", "organized_by", "frequent_venue"].includes(text(edge.kind || edge.type))) {
    return finiteNumber(edge.weight, 0);
  }
  return 0;
}

function graphEdgeWeight(edge) {
  return finiteNumber(
    edge.relationshipScore
      ?? edge.relationship_score
      ?? edge.relationScore
      ?? edge.relation_score
      ?? edge.score
      ?? edge.weight,
    1,
  );
}

function publicGraphEdgeLabel(kind, label) {
  const rawKind = text(kind);
  const rawLabel = text(label);
  if (rawKind === "dj_collaboration" && (!rawLabel || rawLabel.includes("同台"))) return "DJ 关系";
  return rawLabel || "关联";
}

function enrichGraphEdgeDto(edge) {
  const samples = sampleEvidenceIds(edge.sampleEvidenceIds || edge.sample_evidence_json || edge.evidence_json);
  const evidenceCount = Number(edge.evidenceCount ?? edge.evidence_count ?? samples.length ?? 0);
  const relationshipScore = graphRelationshipScore(edge);
  const weight = graphEdgeWeight(edge);
  const kind = text(edge.kind || edge.type || edge.relation || "related");
  return {
    ...edge,
    kind,
    type: text(edge.type) || kind,
    relation: text(edge.relation) || kind,
    label: publicGraphEdgeLabel(kind, edge.label),
    weight,
    width: Number(edge.width || Math.max(0.6, Math.min(7, Math.sqrt(weight || 1) / 2))),
    relationshipScore,
    relationScore: relationshipScore,
    evidenceCount: Number.isFinite(evidenceCount) ? evidenceCount : samples.length,
    sampleEvidenceIds: samples,
    publicState: text(edge.publicState || edge.public_state) || "public_rollup",
    metrics: {
      ...edge.metrics,
      weight,
      relationshipScore,
      relationScore: relationshipScore,
      sameEventCount: Number(edge.sameEventCount ?? edge.same_event_count ?? 0),
      sourceDiversity: Number(edge.sourceDiversity ?? edge.source_diversity ?? 0),
    },
  };
}

function graphFieldMapping() {
  return [
    { table: "canonical_subject", role: "entity node", fields: ["subject_id", "subject_type", "display_name", "taxon_path", "public_state"] },
    { table: "dj_profile", role: "DJ node metrics", fields: ["dj_id", "event_count", "venue_count", "collaborator_count", "confidence"] },
    { table: "performance_event", role: "event node", fields: ["event_id", "event_title", "starts_at", "venue_id", "source_ref_id"] },
    { table: "dj_relation_rollup", role: "DJ-DJ edge", fields: ["src_dj_id", "dst_dj_id", "same_event_count", "relation_score", "public_state"] },
    { table: "evidence_ref", role: "public evidence", fields: ["source_ref_id", "source_account", "source_title", "public_snippet"] },
  ];
}

function graphMetaForResponse(response, options = {}) {
  const nodes = response.nodes || [];
  const edges = response.edges || [];
  const sourceNodeCount = Number(options.sourceNodeCount ?? response.limits?.sourceNodes ?? nodes.length);
  const sourceEdgeCount = Number(options.sourceEdgeCount ?? response.limits?.sourceEdges ?? edges.length);
  const nodeLimit = Number(response.limits?.nodeLimit || options.requestedLimit || nodes.length);
  const edgeLimit = Number(response.limits?.edgeLimit || GRAPH_EDGE_LIMIT);
  return {
    schemaVersion: "stage7_atlas_graph_viewport.v2",
    lens: text(options.lens || response.lens) || "atlas_public_graph",
    lod: normalizeGraphLod(options.lod || response.lod || (sourceNodeCount > nodeLimit ? "overview" : "focus")),
    rendererHints: {
      primary: "3d-force-graph",
      overview: "cosmos-gl",
      fallback: "sigma-graphology-canvas",
    },
    counts: {
      nodes: nodes.length,
      edges: edges.length,
      sourceNodes: sourceNodeCount,
      sourceEdges: sourceEdgeCount,
    },
    truncation: {
      nodesTruncated: sourceNodeCount > nodes.length || nodes.length >= nodeLimit,
      edgesTruncated: sourceEdgeCount > edges.length || edges.length >= edgeLimit,
      nodeLimit,
      edgeLimit,
    },
    safety: {
      rawDbExposed: Boolean(response.retrieval?.dbPath),
      rawExportEnabled: false,
      sqliteWriteExecuted: false,
      graphWriteExecuted: false,
      modelCallExecuted: false,
      llmCallExecuted: false,
      publicOnly: true,
    },
    fieldMapping: graphFieldMapping(),
  };
}

function buildGraphLdrSourcePack(response) {
  const nodes = (response.nodes || []).slice(0, 12);
  const edges = (response.edges || []).slice(0, 12);
  const seedNode = nodes.find((node) => node.role === "seed" || node.seed) || nodes[0] || null;
  const targetLabel = text(response.seed?.label || seedNode?.label || response.query || "Atlas graph");
  const prompt =
    `请基于 Atlas public-safe read model 解释 "${targetLabel}" 的图谱关系。` +
    "只使用 source pack 中的节点、边、公开证据字段，区分候选解释和已接受事实，禁止推断生产写入或外部身份确认。";
  return {
    schemaVersion: "stage7_atlas_ldr_source_pack.v1",
    mode: "source_pack_only",
    target: {
      label: targetLabel,
      query: response.query || null,
      seed: response.seed || (seedNode ? { nodeId: seedNode.id, kind: seedNode.kind, primaryId: seedNode.primaryId, label: seedNode.label } : null),
      lens: response.meta?.lens || "atlas_public_graph",
    },
    nodes: nodes.map((node) => ({
      id: node.id,
      label: node.label,
      kind: node.kind,
      role: node.role,
      clusterId: node.clusterId,
      metrics: node.metrics,
      publicState: node.publicState,
      summary: node.summary || "",
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      kind: edge.kind,
      label: edge.label,
      weight: edge.weight,
      evidenceCount: edge.evidenceCount,
      sampleEvidenceIds: edge.sampleEvidenceIds,
      publicState: edge.publicState,
    })),
    fieldMapping: graphFieldMapping(),
    prompt,
    safety: {
      modelCallExecuted: false,
      networkCallExecuted: false,
      sqliteWriteExecuted: false,
      graphWriteExecuted: false,
      qdrantWriteExecuted: false,
      neo4jWriteExecuted: false,
      mem0WriteExecuted: false,
    },
  };
}

function finalizeGraphViewportResponse(response, options = {}) {
  response.nodes = (response.nodes || []).map((node) => enrichGraphNodeDto(node));
  response.edges = (response.edges || []).map((edge) => enrichGraphEdgeDto(edge));
  const degrees = new Map();
  for (const edge of response.edges) {
    const source = text(typeof edge.source === "object" ? edge.source?.id : edge.source);
    const target = text(typeof edge.target === "object" ? edge.target?.id : edge.target);
    if (source) degrees.set(source, (degrees.get(source) || 0) + 1);
    if (target) degrees.set(target, (degrees.get(target) || 0) + 1);
  }
  response.nodes = response.nodes.map((node) => {
    const degree = Number(degrees.get(node.id) || 0);
    if (!degree) return node;
    const relationCount = Math.max(Number(node.metrics?.relationCount || 0), degree);
    return {
      ...node,
      links: Math.max(Number(node.links || 0), degree),
      metrics: {
        ...node.metrics,
        relationCount,
        degreeHint: Math.max(Number(node.metrics?.degreeHint || 0), degree),
      },
    };
  });
  response.meta = graphMetaForResponse(response, options);
  response.ldrSourcePack = buildGraphLdrSourcePack(response);
  return response;
}

function servingGraphKindForType(value) {
  return text(value).toLowerCase() === "event" ? "events" : "entities";
}

function servingNodeId(rawId, type) {
  const id = text(rawId);
  if (!id) return "";
  return `${servingGraphKindForType(type || id.split(":")[0])}:${id}`;
}

function servingNodeType(value) {
  const raw = text(value).toLowerCase();
  if (raw === "organizer") return "organization";
  return raw || "entity";
}

function servingGraphNode(row, attrs = {}) {
  if (!row) return null;
  const rawId = text(row.subject_id || row.event_id || row.id);
  const rawType = text(row.subject_type || row.type || (rawId.startsWith("event:") ? "event" : "dj"));
  const id = servingNodeId(rawId, rawType);
  if (!id) return null;
  const subtype = servingNodeType(rawType);
  return {
    id,
    kind: servingGraphKindForType(rawType),
    primaryId: rawId,
    label: text(row.display_name || row.event_title || row.label || rawId),
    subtype,
    city: text(row.city_text || row.city),
    place: text(row.venue_name || row.place),
    sourceArticleUid: "",
    sourceAccount: "",
    detailHref: subtype === "event" ? `/atlas/events/${encodeURIComponent(rawId)}` : `/atlas/entities/${encodeURIComponent(rawId)}`,
    weight: Math.max(2, Math.min(18, Math.round(Number(row.rank_score || row.event_count || row.weight || 3) / 100) || 3)),
    summary: textPreview(row.search_text || row.taxon_path || row.time_text || "", 220),
    seed: Boolean(attrs.seed),
    role: graphNodeRole({ kind: servingGraphKindForType(rawType), seed: Boolean(attrs.seed), role: attrs.role || row.role }, attrs),
    confidence: Number.isFinite(Number(row.confidence)) ? Number(row.confidence) : null,
    publicState: text(row.public_state || attrs.publicState) || "public_rollup",
    metrics: {
      degreeHint: Number(row.degree_hint || 0),
      eventCount: Number(row.event_count || row.dj_event_count || 0),
      relationCount: Number(row.relation_count || 0),
      sourceCount: Number(row.source_count || row.source_article_count || 0),
      rankScore: Number(row.rank_score || row.weight || 0),
    },
    visual: { avatarUrl: "", hasAvatar: false, color: graphNodeColor(servingGraphKindForType(rawType), subtype), size: graphVisualSize(Math.max(2, Math.min(18, Math.round(Number(row.rank_score || row.event_count || row.weight || 3) / 100) || 3))) },
    externalLinks: [],
    hasExternalLinks: false,
  };
}

function servingGraphWindowPayload(windowRow, meta = {}) {
  const rawNodes = maybeJson(windowRow?.nodes_json, []);
  const rawEdges = maybeJson(windowRow?.edges_json, []);
  const nodes = rawNodes
    .map((node) => servingGraphNode({
      id: node.id,
      type: node.type,
      label: node.label,
      city: node.city,
      starts_at: node.starts_at,
      weight: node.weight,
    }, {
      seed: node.role === "seed" || node.id === windowRow?.seed_subject_id,
      role: node.role || "",
      publicState: node.public_state || node.publicState || "public_rollup",
    }))
    .filter(Boolean);
  const edges = rawEdges
    .map((edge) => {
      const source = servingNodeId(edge.source, edge.source?.split(":")[0]);
      const target = servingNodeId(edge.target, edge.target?.split(":")[0]);
      if (!source || !target || source === target) return null;
      return {
        id: text(edge.id) || `${text(edge.type || "related")}:${source}->${target}`,
        source,
        target,
        kind: text(edge.type || edge.kind || "related"),
        label: publicGraphEdgeLabel(text(edge.type || edge.kind || "related"), edge.label || edge.type || "关联"),
        weight: Number(edge.weight || 1),
        relationshipScore: graphRelationshipScore(edge),
        directed: false,
        evidenceCount: Number(edge.evidence_count || edge.evidenceCount || 0),
        sampleEvidenceIds: sampleEvidenceIds(edge.sample_evidence_json || edge.sampleEvidenceIds || []),
        publicState: text(edge.public_state || edge.publicState) || "public_rollup",
      };
    })
    .filter(Boolean);
  const response = {
    schemaVersion: "stage7_atlas_api.graph_response.v1",
    generatedAt: new Date().toISOString(),
    mode: meta.mode || "seed",
    query: meta.query || null,
    kind: meta.kind || null,
    seed: meta.seed || null,
    depth: Number(windowRow?.depth || meta.depth || 2),
    steps: meta.steps || null,
    fanout: meta.fanout || null,
    notFound: false,
    nodes,
    edges,
    limits: {
      requested: meta.requestedLimit || nodes.length,
      nodeLimit: meta.requestedLimit || nodes.length,
      edgeLimit: GRAPH_EDGE_LIMIT,
      returnedNodes: nodes.length,
      returnedEdges: edges.length,
    },
    retrieval: {
      mode: "atlas_serving_graph_window_cache",
      exactEntitySeeded: Boolean(meta.exactEntitySeeded),
      liveVectorSearchEnabled: false,
      dbPath: "",
      dbIdentity: meta.dbIdentity || null,
    },
    safety: graphSafety(),
  };
  return finalizeGraphViewportResponse(response, {
    lens: windowRow?.lens || meta.lens || "dj_core",
    lod: meta.lod || "focus",
    sourceNodeCount: Number(windowRow?.node_count || nodes.length),
    sourceEdgeCount: Number(windowRow?.edge_count || edges.length),
  });
}

function createGraphAccumulator({ nodeLimit, edgeLimit = GRAPH_EDGE_LIMIT, enrichNode } = {}) {
  const nodes = new Map();
  const edges = new Map();
  return {
    addNode(row, kind, attrs = {}) {
      const node = graphNode(row, kind, enrichNode ? { ...attrs, ...enrichNode(row, kind, attrs) } : attrs);
      if (!node) return null;
      const existing = nodes.get(node.id);
      if (existing) {
        existing.seed = existing.seed || node.seed;
        existing.weight = Math.max(existing.weight, node.weight);
        if (!existing.visual?.avatarUrl && node.visual?.avatarUrl) existing.visual = node.visual;
        if (!existing.externalLinks?.length && node.externalLinks?.length) {
          existing.externalLinks = node.externalLinks;
          existing.hasExternalLinks = true;
        }
        return existing;
      }
      if (nodes.size >= nodeLimit) return null;
      nodes.set(node.id, node);
      return node;
    },
    addEdge(source, target, kind, label, weight = 1) {
      if (!source?.id || !target?.id || source.id === target.id || edges.size >= edgeLimit) return null;
      const id = `${kind}:${source.id}->${target.id}`;
      if (edges.has(id)) return edges.get(id);
      const edge = {
        id,
        source: source.id,
        target: target.id,
        kind,
        label,
        weight,
        directed: false,
        evidenceCount: 0,
        sampleEvidenceIds: [],
        publicState: "public_rollup",
      };
      edges.set(id, edge);
      return edge;
    },
    output() {
      return {
        nodes: Array.from(nodes.values()),
        edges: Array.from(edges.values()),
        returnedNodes: nodes.size,
        returnedEdges: edges.size,
      };
    },
  };
}

function mapIdentityRow(row) {
  return {
    id: row.item_id || "",
    queue: row.queue || "",
    bucket: row.bucket || "",
    status: row.status || "",
    subjectName: row.subject_name || "",
    subjectType: row.subject_type || "",
    url: row.url || "",
    domain: row.domain || "",
    sourceAccount: row.source_account || "",
    sourceArticleUid: row.source_article_uid || "",
    sourceTitle: row.source_title || "",
    supportCount: row.support_count || 0,
    identitySignalScore: row.identity_signal_score ?? null,
    reviewReason: row.review_reason || "",
    nextActions: maybeJson(row.next_actions_json, []).slice(0, 6),
    signals: maybeJson(row.signals_json, {}),
    acceptedForGraph: Boolean(row.accepted_for_graph),
    identityProof: Boolean(row.identity_proof),
    graphWriteAllowed: Boolean(row.graph_write_allowed),
    currentState: row.current_action
      ? {
          action: row.current_action,
          decision: row.current_decision || "",
          reviewer: row.reviewer || "",
          note: row.note || "",
          updatedAt: row.updated_at || "",
          actionCount: row.action_count || 0,
        }
      : null,
  };
}

function mapGeocodeReviewRow(row) {
  return {
    reviewId: row.review_id || "",
    placeId: row.place_id || "",
    label: row.label || "",
    normalizedPlace: row.normalized_place || "",
    bucket: row.review_bucket || "",
    candidateCity: row.candidate_city || "",
    candidateLat: row.candidate_lat ?? null,
    candidateLon: row.candidate_lon ?? null,
    candidateSource: row.candidate_source || "",
    confidence: row.confidence ?? null,
    reason: row.reason || "",
    eventCount: row.event_count || 0,
    entityCount: row.entity_count || 0,
    articleCount: row.article_count || 0,
    sampleArticleUid: row.sample_article_uid || "",
    updatedAt: row.updated_at || "",
    payload: maybeJson(row.payload_json, {}),
    currentState: row.current_action
      ? {
          action: row.current_action,
          decision: row.current_decision || "",
          reviewer: row.reviewer || "",
          note: row.note || "",
          updatedAt: row.geocode_state_updated_at || "",
          actionCount: row.action_count || 0,
          lastActionId: row.last_action_id || "",
        }
      : null,
  };
}

function createFacet(rows) {
  return rows.map((row) => ({ label: row.label || "", count: row.count || 0 }));
}

function mobilePayloadPolicy() {
  return {
    target: "wechat_miniprogram",
    graphMode: "bounded_focus",
    initialRender: "profile_bottom_sheet",
    maxInitialNodes: 48,
    maxSectionItems: 10,
    fullGraphExport: false,
    evidenceDefaultCollapsed: true,
  };
}

function mobileSection(id, title, layout, items, options = {}) {
  return {
    id,
    title,
    layout,
    items: Array.isArray(items) ? items : [],
    emptyText: options.emptyText || "",
    badge: options.badge || "",
    summary: options.summary || null,
    reportOnly: Boolean(options.reportOnly),
  };
}

function atlasFamilySafety(baseSafety = {}) {
  return {
    ...graphSafety(),
    ...(baseSafety || {}),
    rawDbPathHidden: true,
    rawLocalPathExposed: false,
    rawUrlHiddenUnlessPublicAllowed: true,
    rawSourceUrlExposed: false,
    boundedPayload: true,
    fullGraphExport: false,
  };
}

function sourceRefIdFromArticle(row = {}) {
  return text(row.source_ref_id || row.sourceRefId || row.article_uid || row.article_id || row.id);
}

function sourceRefLooksPublicEvidence(value) {
  const raw = text(value);
  return Boolean(raw && (raw.includes("/") || raw.startsWith("src:") || raw.startsWith("source:") || raw.startsWith("evidence:")));
}

function familyEvidenceStub(sourceRefId) {
  const id = text(sourceRefId);
  if (!id) return null;
  return {
    sourceRefId: id,
    state: "public_fact",
    tap: {
      action: "open_source_evidence",
      sourceRefId: id,
      apiPath: `/api/v1/atlas/evidence/${encodeURIComponent(id)}`,
    },
  };
}

function familySourceItem(row = {}) {
  const sourceRefId = sourceRefIdFromArticle(row);
  return {
    sourceRefId,
    title: textPreview(row.title || row.source_title || row.sourceTitle || "", 120),
    sourceAccount: textPreview(row.source_account || row.sourceAccount || "", 80),
    postDate: textPreview(row.publish_time_status || row.post_date || row.postDate || row.date || "", 40),
    publicSnippet: textPreview(row.public_snippet || row.snippet || "", 180),
    state: "public_fact",
    tap: {
      action: "open_source_evidence",
      sourceRefId,
      apiPath: sourceRefId ? `/api/v1/atlas/evidence/${encodeURIComponent(sourceRefId)}` : "",
    },
  };
}

function familyHistoryItem(row = {}) {
  const eventId = text(row.evid || row.event_id || row.id);
  const sourceRefId = sourceRefIdFromArticle(row);
  const familyProfileApi = eventId ? `/api/v1/atlas/family/profile?id=${encodeURIComponent(eventId)}` : "";
  return {
    id: eventId,
    title: textPreview(row.name || row.event_title || row.title || "", 120),
    subtitle: uniqueTexts([row.time_text || row.starts_at || row.time_iso, row.place || row.venue_name, row.city], 4).join(" · "),
    time: text(row.time_text || row.starts_at || row.time_iso || ""),
    venue: textPreview(row.place || row.venue_name || "", 80),
    city: textPreview(row.city || "", 40),
    confidence: row.confidence ?? null,
    state: "public_fact",
    evidence: [familyEvidenceStub(sourceRefId)].filter(Boolean),
    tap: {
      action: "open_event_family",
      id: eventId,
      query: text(row.name || row.event_title || row.title || ""),
      apiPath: familyProfileApi,
      familyProfileApi,
      detailApiPath: eventId ? `/api/v1/stage7/events/${encodeURIComponent(eventId)}` : "",
    },
  };
}

function familyRelationshipEvidence(row = {}) {
  const refs = [
    ...sampleEvidenceIds(row.sampleEvidenceIds || row.sample_evidence_json || []),
    ...(sourceRefLooksPublicEvidence(row.sample) ? [row.sample] : []),
    ...(sourceRefLooksPublicEvidence(row.sourceRefId || row.source_ref_id) ? [row.sourceRefId || row.source_ref_id] : []),
  ];
  return uniqueTexts(refs, 6).map(familyEvidenceStub).filter(Boolean);
}

function familyRelationshipItem(row = {}) {
  const relationshipScore = finiteNumber(row.relationshipScore ?? row.relationScore ?? row.relationship_score ?? row.score ?? row.count, 0);
  const sameEventCount = finiteNumber(row.sameEventCount ?? row.same_event_count ?? row.activityCount ?? row.activity_count ?? row.count, 0);
  const id = text(row.eid || row.dj_id || row.id || row.label || row.name);
  const label = textPreview(row.label || row.name || row.display_name || "", 100);
  const profileApiPath = id.includes(":")
    ? `/api/v1/atlas/family/profile?id=${encodeURIComponent(id)}`
    : (label ? `/api/v1/atlas/family/profile?q=${encodeURIComponent(label)}` : "");
  return {
    id,
    label,
    type: text(row.type || row.kind || "entity"),
    relationshipScore,
    explanation: relationshipScore ? `关系分 ${relationshipScore}` : "公开关系证据",
    metrics: {
      sameEventCount,
      sameVenueCount: finiteNumber(row.sameVenueCount ?? row.same_venue_count, 0),
      sameLabelCount: finiteNumber(row.sameLabelCount ?? row.same_label_count, 0),
      sourceDiversity: finiteNumber(row.sourceDiversity ?? row.source_diversity, 0),
    },
    evidence: familyRelationshipEvidence(row),
    state: "public_fact",
    tap: {
      action: "open_entity_profile",
      query: label,
      apiPath: profileApiPath,
    },
  };
}

function familyRankedItem(row = {}, options = {}) {
  const label = text(row.label || row.name || row.venue_name || row.org_name || "");
  const id = text(row.venue_id || row.org_id || row.id || label);
  const profileApiPath = id.includes(":")
    ? `/api/v1/atlas/family/profile?id=${encodeURIComponent(id)}`
    : (label ? `/api/v1/atlas/family/profile?q=${encodeURIComponent(label)}` : "");
  return {
    id,
    label: textPreview(label, 100),
    city: textPreview(row.city || "", 40),
    relationshipScore: finiteNumber(row.relationshipScore ?? row.relationship_score ?? row.score ?? row.count, 0),
    evidenceCount: finiteNumber(row.evidenceCount ?? row.evidence_count ?? row.count, 0),
    activityCount: finiteNumber(row.activityCount ?? row.activity_count ?? row.event_count, 0),
    state: options.state || "public_fact",
    evidence: familyRelationshipEvidence(row),
    tap: {
      action: "open_entity_profile",
      query: label,
      apiPath: profileApiPath,
    },
  };
}

function atlasFamilyCenterKind(type) {
  const raw = text(type).toLowerCase();
  if (["dj", "artist", "person", "performer"].includes(raw)) return "dj";
  if (["venue", "club", "space"].includes(raw)) return "venue";
  if (raw === "event") return "event";
  if (["organizer", "label", "radio", "crew", "organization"].includes(raw)) return "organizer";
  return "entity";
}

function atlasFamilyExploreCopy(centerKind) {
  if (centerKind === "venue") {
    return {
      title: "以俱乐部为中心",
      guidance: "先看关系分高的 DJ，再看经常发生的活动和音响系统证据。",
      relatedDjsTitle: "关系分高的 DJ",
      clubsTitle: "关联场地",
      eventsTitle: "常办 / 历史活动",
      organizationsTitle: "关联厂牌 / 主办",
    };
  }
  if (centerKind === "event") {
    return {
      title: "以活动为中心",
      guidance: "先看参演 DJ，再跳到场地、来源证据和相关实体。",
      relatedDjsTitle: "参演 DJ",
      clubsTitle: "发生场地",
      eventsTitle: "活动详情",
      organizationsTitle: "主办 / 厂牌",
    };
  }
  if (centerKind === "organizer") {
    return {
      title: "以厂牌 / 主办为中心",
      guidance: "先看关系分高的 DJ，再看关联活动和常出现地点。",
      relatedDjsTitle: "关系分高的 DJ",
      clubsTitle: "常出现地点",
      eventsTitle: "关联活动",
      organizationsTitle: "相关厂牌 / 主办",
    };
  }
  return {
    title: "以 DJ 为中心",
    guidance: "先看关系分高的 DJ，再向外看常去俱乐部、历史活动和主办厂牌。",
    relatedDjsTitle: "关系分高的 DJ",
    clubsTitle: "常去俱乐部",
    eventsTitle: "历史活动",
    organizationsTitle: "主办 / 厂牌",
  };
}

function atlasFamilyExploreRing(id, title, hint, itemType, items) {
  return {
    id,
    title,
    hint,
    itemType,
    items: (Array.isArray(items) ? items : []).slice(0, 8),
  };
}

function atlasFamilyExploreRings(centerKind, sections) {
  const copy = atlasFamilyExploreCopy(centerKind);
  const rings = [];
  const relatedDjs = atlasFamilyExploreRing(
    "relatedDjs",
    copy.relatedDjsTitle,
    centerKind === "event" ? "点 DJ 继续看他的历史活动和高分关系。" : "点任意 DJ 切换中心继续漫游。",
    "dj",
    sections.relatedDjs,
  );
  const clubs = atlasFamilyExploreRing(
    "clubs",
    copy.clubsTitle,
    centerKind === "event" ? "点场地查看高关系分 DJ、常办活动和音响系统。" : "点俱乐部查看核心 DJ、活动和音响系统。",
    "venue",
    sections.clubs,
  );
  const events = atlasFamilyExploreRing(
    "events",
    copy.eventsTitle,
    "点活动切换为活动中心，查看参演 DJ 和来源证据。",
    "event",
    sections.events,
  );
  const organizations = atlasFamilyExploreRing(
    "organizations",
    copy.organizationsTitle,
    "点厂牌或主办继续查看关联 DJ 与活动。",
    "organization",
    sections.organizations,
  );
  const sources = atlasFamilyExploreRing("sources", "信息来源", "所有公开事实都从这里打开证据抽屉。", "source", sections.sources);
  if (centerKind === "venue") {
    rings.push(relatedDjs, events, atlasFamilyExploreRing("soundSystem", "音响系统", "报告态证据，不提升为公开事实。", "evidence", sections.soundSystem), sources);
  } else if (centerKind === "event") {
    rings.push(relatedDjs, clubs, sources);
  } else if (centerKind === "organizer") {
    rings.push(relatedDjs, events, clubs, sources);
  } else {
    rings.push(relatedDjs, clubs, events, organizations, sources);
  }
  return rings.filter((ring) => ring.items.length);
}

function publicEvidenceUrlPolicy(row = {}) {
  return {
    status: row.public_url_allowed ? "public_allowed_no_url" : "not_public",
    url: "",
  };
}

function topCountsFromProfile(rows, limit = 1) {
  return (Array.isArray(rows) ? rows : []).slice(0, limit).map((row) => row.label || "").filter(Boolean);
}

export class Stage7AtlasSqliteStore {
  constructor(options = {}) {
    const env = options.env || process.env;
    const useServingReadModel = String(env.ATLAS_USE_SERVING_READ_MODEL || "").trim() === "1";
    this.dbPath = options.stage7SqliteDbPath || env.STAGE7_ATLAS_SQLITE_DB || env.ATLAS_CORE_SQLITE_DB || env.ATLAS_SERVING_SQLITE_DB || (useServingReadModel ? DEFAULT_SERVING_SQLITE_DB : DEFAULT_SQLITE_DB);
    this.graphAssetsPath = options.graphEntityAssetsPath || env.ATLAS_GRAPH_ENTITY_ASSETS_PATH || env.ATLAS_GRAPH_ASSETS_PATH || "";
    this.soundSystemEvidencePath = options.soundSystemEvidencePath || env.ATLAS_SOUND_SYSTEM_EVIDENCE_PATH || env.ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH || "";
    this.entityMergeGroupsPath = options.entityMergeGroupsPath || env.ATLAS_ENTITY_MERGE_GROUPS_PATH || "";
    this.exposeInternalDbPath = String(env.ATLAS_EXPOSE_INTERNAL_DB_PATH || "").trim() === "1";
    this.readOnly = envFlag(env.ATLAS_SQLITE_READONLY || env.STAGE7_ATLAS_SQLITE_READONLY);
    this.dbHandle = null;
    this.dbModulePromise = null;
    this.initialized = false;
    this.servingReadModel = null;
    this.publicSourceNoiseCache = new Map();
    this.graphAssets = null;
    this.soundSystemEvidence = null;
    this.entityMergeGroups = null;
  }

  publicDbIdentity() {
    return {
      label: "atlas_public_read_model",
      mode: this.readOnly ? "sqlite_bounded_readonly_projection" : "sqlite_bounded_projection",
      source: "public_serving_read_model",
      internalPathExposed: this.exposeInternalDbPath,
      readOnly: this.readOnly,
      mutableLedgerEnabled: !this.readOnly,
    };
  }

  async loadDatabaseModule() {
    if (!this.dbModulePromise) {
      this.dbModulePromise = import("better-sqlite3").then((mod) => mod.default || mod);
    }
    return this.dbModulePromise;
  }

  async db() {
    if (!this.dbHandle) {
      const Database = await this.loadDatabaseModule();
      this.dbHandle = this.readOnly ? new Database(this.dbPath, { readonly: true, fileMustExist: true }) : new Database(this.dbPath);
      this.dbHandle.pragma("busy_timeout = 5000");
      this.dbHandle.pragma("cache_size = -64000");
      this.dbHandle.pragma("temp_store = MEMORY");
      this.dbHandle.pragma("mmap_size = 268435456");
      if (!this.readOnly) {
        this.dbHandle.pragma("journal_mode = WAL");
        this.dbHandle.pragma("synchronous = NORMAL");
      }
      if (this.readOnly) {
        this.dbHandle.pragma("query_only = ON");
      } else if (this.isServingReadModel(this.dbHandle)) {
        this.dbHandle.pragma("query_only = ON");
      } else {
        this.ensureMutableSchema();
      }
    }
    return this.dbHandle;
  }

  isServingReadModel(db) {
    if (this.servingReadModel !== null) return this.servingReadModel;
    this.servingReadModel = sqliteTableExists(db, "search_document")
      && sqliteTableExists(db, "performance_event")
      && sqliteTableExists(db, "dj_profile");
    return this.servingReadModel;
  }

  assertWritableLedger() {
    if (!this.readOnly) return;
    const error = new Error("Atlas SQLite store is running in read-only mode");
    error.statusCode = 403;
    error.code = "ATLAS_SQLITE_READONLY";
    throw error;
  }

  isPublicSourceArticleNoise(db, sourceArticleUid) {
    const uid = text(sourceArticleUid);
    if (!uid) return false;
    if (this.publicSourceNoiseCache.has(uid)) return this.publicSourceNoiseCache.get(uid);
    const article = this.findRow(db, "articles", uid);
    const value = Boolean(article && isPublicAtlasNoise(article, "articles"));
    this.publicSourceNoiseCache.set(uid, value);
    return value;
  }

  isPublicRowVisible(db, row, kind) {
    if (!row || isPublicAtlasNoise(row, kind)) return false;
    if (kind !== "articles" && this.isPublicSourceArticleNoise(db, row.source_article_uid)) return false;
    return true;
  }

  publicRows(db, rows, kind, limit = rows.length) {
    return rows.filter((row) => this.isPublicRowVisible(db, row, kind)).slice(0, limit);
  }

  getGraphAssets() {
    if (this.graphAssets) return this.graphAssets;
    if (!text(this.graphAssetsPath)) {
      this.graphAssets = new Map();
      return this.graphAssets;
    }
    try {
      const raw = JSON.parse(readFileSync(this.graphAssetsPath, "utf8"));
      this.graphAssets = normalizeGraphAssetManifest(raw);
    } catch {
      this.graphAssets = new Map();
    }
    return this.graphAssets;
  }

  getSoundSystemEvidenceIndex() {
    if (this.soundSystemEvidence) return this.soundSystemEvidence;
    const index = new Map();
    const add = (key, row) => {
      const normalizedKey = text(key);
      if (!normalizedKey) return;
      if (!index.has(normalizedKey)) index.set(normalizedKey, []);
      index.get(normalizedKey).push(row);
    };
    if (text(this.soundSystemEvidencePath)) {
      try {
        const lines = readFileSync(this.soundSystemEvidencePath, "utf8").split(/\r?\n/).filter(Boolean);
        for (const line of lines) {
          const raw = JSON.parse(line);
          const row = {
            venueId: text(raw.venueId || raw.venue_id),
            venueName: text(raw.venueName || raw.venue_name),
            city: text(raw.city),
            evidenceCount: finiteNumber(raw.evidenceCount ?? raw.evidence_count, 0),
            sourceCount: finiteNumber(raw.sourceCount ?? raw.source_count, 0),
            terms: uniqueTexts(raw.terms || [], 12),
            confidence: finiteNumber(raw.confidence, 0),
            evidence: Array.isArray(raw.evidence) ? raw.evidence.slice(0, 8).map((item) => ({
              sourceRefId: text(item.sourceRefId || item.source_ref_id),
              sourceAccount: text(item.sourceAccount || item.source_account),
              sourceTitle: text(item.sourceTitle || item.source_title),
              postDate: text(item.postDate || item.post_date),
              eventId: text(item.eventId || item.event_id),
              eventTitle: text(item.eventTitle || item.event_title),
              matchedTerms: uniqueTexts(item.matchedTerms || item.matched_terms || [], 12),
              publicSnippet: textPreview(item.publicSnippet || item.public_snippet, 220),
            })) : [],
            reportOnly: raw.reportOnly !== false,
          };
          add(row.venueId, row);
          add(profileNameKey(row.venueName), row);
        }
      } catch {
        // Optional sidecar: failure to load must not break graph APIs.
      }
    }
    this.soundSystemEvidence = index;
    return this.soundSystemEvidence;
  }

  soundSystemEvidenceForSubject(row, limit = 6) {
    const index = this.getSoundSystemEvidenceIndex();
    if (!index.size) return [];
    const keys = uniqueTexts([
      row?.subject_id,
      row?.eid,
      row?.venue_id,
      profileNameKey(row?.display_name || row?.name || row?.venue_name),
    ], 8);
    const out = [];
    const seen = new Set();
    for (const key of keys) {
      for (const item of index.get(key) || []) {
        const id = `${item.venueId}:${item.venueName}`;
        if (seen.has(id)) continue;
        seen.add(id);
        out.push(item);
        if (out.length >= limit) return out;
      }
    }
    return out;
  }

  soundSystemEvidenceForSubjects(rows, limit = 6) {
    const out = [];
    const seen = new Set();
    for (const row of rows || []) {
      for (const item of this.soundSystemEvidenceForSubject(row, limit)) {
        const id = `${item.venueId}:${item.venueName}`;
        if (seen.has(id)) continue;
        seen.add(id);
        out.push(item);
        if (out.length >= limit) return out;
      }
    }
    return out;
  }

  soundSystemSummary(evidenceRows) {
    const rows = Array.isArray(evidenceRows) ? evidenceRows : [];
    const terms = uniqueTexts(rows.flatMap((row) => row.terms || []), 16);
    return {
      available: rows.length > 0,
      venueCount: rows.length,
      evidenceCount: rows.reduce((sum, row) => sum + finiteNumber(row.evidenceCount, 0), 0),
      sourceCount: rows.reduce((sum, row) => sum + finiteNumber(row.sourceCount, 0), 0),
      terms,
      confidence: rows.reduce((max, row) => Math.max(max, finiteNumber(row.confidence, 0)), 0),
      reportOnly: true,
    };
  }

  getEntityMergeGroupIndex() {
    if (this.entityMergeGroups) return this.entityMergeGroups;
    const index = new Map();
    const add = (key, row) => {
      const normalizedKey = text(key);
      if (!normalizedKey) return;
      if (!index.has(normalizedKey)) index.set(normalizedKey, row);
    };
    if (text(this.entityMergeGroupsPath)) {
      try {
        const lines = readFileSync(this.entityMergeGroupsPath, "utf8").split(/\r?\n/).filter(Boolean);
        for (const line of lines) {
          const raw = JSON.parse(line);
          const members = Array.isArray(raw.members) ? raw.members.map((member) => ({
            subjectId: text(member.subject_id || member.subjectId),
            subjectType: text(member.subject_type || member.subjectType),
            displayName: text(member.display_name || member.displayName),
            city: text(member.city_text || member.city),
            taxonPath: text(member.taxon_path || member.taxonPath),
            rankScore: finiteNumber(member.rank_score ?? member.rankScore, 0),
          })).filter((member) => member.subjectId || member.displayName) : [];
          const row = {
            groupId: text(raw.group_id || raw.groupId),
            canonicalSubjectId: text(raw.canonical_subject_id || raw.canonicalSubjectId),
            canonicalName: text(raw.canonical_name || raw.canonicalName),
            memberCount: finiteNumber(raw.member_count ?? raw.memberCount, members.length),
            members,
            sourceClusterIds: uniqueTexts(raw.source_cluster_ids || raw.sourceClusterIds || [], 24),
            sourceDecisionCount: finiteNumber(raw.source_decision_count ?? raw.sourceDecisionCount, 0),
            confidenceMin: finiteNumber(raw.confidence_min ?? raw.confidenceMin, 0),
            confidenceAvg: finiteNumber(raw.confidence_avg ?? raw.confidenceAvg, 0),
            riskFlags: uniqueTexts(raw.risk_flags || raw.riskFlags || [], 16),
            reportOnly: raw.report_only !== false && raw.reportOnly !== false,
          };
          add(row.groupId, row);
          add(row.canonicalSubjectId, row);
          add(profileNameKey(row.canonicalName), row);
          for (const member of members) {
            add(member.subjectId, row);
            add(profileNameKey(member.displayName), row);
          }
        }
      } catch {
        // Optional report-only sidecar: failure to load must not break graph APIs.
      }
    }
    this.entityMergeGroups = index;
    return this.entityMergeGroups;
  }

  entityMergeGroupForProfile(profile) {
    const index = this.getEntityMergeGroupIndex();
    if (!index.size || !profile?.found) return null;
    const canonical = profile.canonical || {};
    const keys = uniqueTexts([
      canonical.primaryId,
      profile.id,
      profile.query,
      profileNameKey(canonical.name),
      ...(Array.isArray(canonical.names) ? canonical.names.map((name) => profileNameKey(name)) : []),
    ], 40);
    for (const key of keys) {
      const row = index.get(key);
      if (row) return row;
    }
    return null;
  }

  compactEntityMergeGroup(group, limit = 18) {
    if (!group) {
      return {
        available: false,
        reportOnly: true,
        aliases: [],
      };
    }
    const aliases = (group.members || [])
      .slice()
      .sort((a, b) => finiteNumber(b.rankScore, 0) - finiteNumber(a.rankScore, 0))
      .slice(0, limit)
      .map((member) => ({
        subjectId: member.subjectId,
        name: member.displayName,
        type: member.subjectType,
        city: member.city,
        rankScore: member.rankScore,
        tap: {
          action: "open_entity_profile",
          apiPath: `/api/v1/stage7/graph/mobile-profile?id=${encodeURIComponent(member.subjectId)}`,
          id: member.subjectId,
          query: member.displayName,
        },
      }));
    return {
      available: true,
      reportOnly: group.reportOnly !== false,
      groupId: group.groupId,
      canonicalSubjectId: group.canonicalSubjectId,
      canonicalName: group.canonicalName,
      memberCount: group.memberCount,
      aliases,
      sourceDecisionCount: group.sourceDecisionCount,
      confidenceMin: group.confidenceMin,
      confidenceAvg: group.confidenceAvg,
      riskFlags: group.riskFlags,
      truncated: group.memberCount > aliases.length,
    };
  }

  canonicalSubjectIdForSubject(subjectId) {
    const group = this.getEntityMergeGroupIndex().get(text(subjectId));
    return text(group?.canonicalSubjectId) || text(subjectId);
  }

  canonicalServingSubjectForRow(db, row) {
    if (!row) return row;
    const group = this.getEntityMergeGroupIndex().get(text(row.subject_id)) || this.getEntityMergeGroupIndex().get(profileNameKey(row.display_name));
    const canonicalId = text(group?.canonicalSubjectId);
    if (!canonicalId || canonicalId === text(row.subject_id)) return row;
    const canonical = this.servingSubjectByIdRaw(db, canonicalId);
    if (!canonical) return row;
    return {
      ...canonical,
      merge_overlay: {
        groupId: group.groupId,
        canonicalSubjectId: group.canonicalSubjectId,
        canonicalName: group.canonicalName,
        matchedSubjectId: row.subject_id || "",
        matchedName: row.display_name || "",
        memberCount: group.memberCount,
        reportOnly: group.reportOnly !== false,
      },
    };
  }

  canonicalizeServingRows(db, rows) {
    if (!this.getEntityMergeGroupIndex().size) return dedupeServingRows(rows);
    return dedupeServingRows((rows || []).map((row) => this.canonicalServingSubjectForRow(db, row)));
  }

  servingProfileMergeScope(db, seed, { selectedId = "", query = "" } = {}) {
    const index = this.getEntityMergeGroupIndex();
    const keys = uniqueTexts([
      selectedId,
      seed?.subject_id,
      seed?.merge_overlay?.matchedSubjectId,
      seed?.merge_overlay?.groupId,
      profileNameKey(seed?.display_name),
      profileNameKey(query),
    ], 24);
    let group = null;
    for (const key of keys) {
      const matched = index.get(key);
      if (matched) {
        group = matched;
        break;
      }
    }
    const memberRows = [];
    if (group?.members?.length) {
      for (const member of group.members) {
        memberRows.push({
          subject_id: member.subjectId,
          subject_type: member.subjectType,
          display_name: member.displayName,
          city_text: member.city,
          taxon_path: member.taxonPath,
          rank_score: member.rankScore,
          aliases_text: "",
        });
      }
    }
    const rows = dedupeServingRows([seed, ...memberRows].filter(Boolean));
    const aggregationRows = servingProfileAggregationRows(rows, seed);
    const names = uniqueTexts([
      group?.canonicalName,
      seed?.display_name,
      ...rows.map((row) => row.display_name),
      ...rows.flatMap((row) => text(row.aliases_text).split(/\s+/)),
    ], 24);
    const allDjIds = uniqueTexts(rows.filter((row) => text(row.subject_type) === "dj").map((row) => row.subject_id), 1_000);
    const allVenueIds = uniqueTexts(rows.filter((row) => text(row.subject_type) === "venue").map((row) => row.subject_id), 1_000);
    const allOrgIds = uniqueTexts(rows.filter((row) => ["organizer", "radio"].includes(text(row.subject_type))).map((row) => row.subject_id), 1_000);
    return {
      group,
      rows,
      aggregationRows,
      aggregationLimit: PROFILE_MERGE_AGGREGATION_LIMITS.total,
      names,
      allDjIds,
      allVenueIds,
      allOrgIds,
      djIds: uniqueTexts(aggregationRows.filter((row) => text(row.subject_type) === "dj").map((row) => row.subject_id), PROFILE_MERGE_AGGREGATION_LIMITS.dj),
      venueIds: uniqueTexts(aggregationRows.filter((row) => text(row.subject_type) === "venue").map((row) => row.subject_id), PROFILE_MERGE_AGGREGATION_LIMITS.venue),
      orgIds: uniqueTexts(aggregationRows.filter((row) => ["organizer", "radio"].includes(text(row.subject_type))).map((row) => row.subject_id), PROFILE_MERGE_AGGREGATION_LIMITS.organizer + PROFILE_MERGE_AGGREGATION_LIMITS.radio),
    };
  }

  assetForRow(row, kind) {
    if (!row) return null;
    const assets = this.getGraphAssets();
    if (!assets.size) return null;
    const primaryId = primaryDetailId(row, kind);
    const keys = [`${kind}:${primaryId}`, primaryId];
    if (kind === "entities" && row.eid) keys.push(`entities:${row.eid}`, row.eid);
    for (const key of keys) {
      const asset = assets.get(key);
      if (asset) return asset;
    }
    return null;
  }

  createGraphAccumulator(options = {}) {
    return createGraphAccumulator({
      ...options,
      enrichNode: (row, kind) => ({ asset: this.assetForRow(row, kind) }),
    });
  }

  ensureMutableSchema() {
    if (this.initialized || !this.dbHandle) return;
    this.dbHandle.exec(`
      CREATE TABLE IF NOT EXISTS adjudication_actions (
        action_id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL,
        subject_name TEXT NOT NULL DEFAULT '',
        subject_type TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT '',
        reviewer TEXT NOT NULL DEFAULT 'local',
        note TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        source_article_uid TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}'
      );
      CREATE TABLE IF NOT EXISTS adjudication_item_state (
        item_id TEXT PRIMARY KEY,
        subject_name TEXT NOT NULL DEFAULT '',
        subject_type TEXT NOT NULL DEFAULT '',
        current_action TEXT NOT NULL,
        current_decision TEXT NOT NULL DEFAULT '',
        reviewer TEXT NOT NULL DEFAULT 'local',
        note TEXT NOT NULL DEFAULT '',
        source_url TEXT NOT NULL DEFAULT '',
        source_article_uid TEXT NOT NULL DEFAULT '',
        action_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        last_action_id TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS map_geocode_places (
        place_id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        normalized_place TEXT NOT NULL,
        city TEXT NOT NULL DEFAULT '',
        lat REAL,
        lon REAL,
        geocode_status TEXT NOT NULL,
        geocode_source TEXT NOT NULL,
        precision TEXT NOT NULL,
        event_count INTEGER NOT NULL DEFAULT 0,
        entity_count INTEGER NOT NULL DEFAULT 0,
        article_count INTEGER NOT NULL DEFAULT 0,
        sample_article_uid TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS map_geocode_review_items (
        review_id TEXT PRIMARY KEY,
        place_id TEXT NOT NULL,
        label TEXT NOT NULL,
        normalized_place TEXT NOT NULL,
        review_bucket TEXT NOT NULL,
        candidate_city TEXT NOT NULL DEFAULT '',
        candidate_lat REAL,
        candidate_lon REAL,
        candidate_source TEXT NOT NULL DEFAULT '',
        confidence REAL,
        reason TEXT NOT NULL DEFAULT '',
        event_count INTEGER NOT NULL DEFAULT 0,
        entity_count INTEGER NOT NULL DEFAULT 0,
        article_count INTEGER NOT NULL DEFAULT 0,
        sample_article_uid TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}'
      );
      CREATE TABLE IF NOT EXISTS geocode_review_actions (
        action_id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL,
        place_id TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '',
        review_bucket TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT '',
        reviewer TEXT NOT NULL DEFAULT 'local',
        note TEXT NOT NULL DEFAULT '',
        sample_article_uid TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}'
      );
      CREATE TABLE IF NOT EXISTS geocode_review_item_state (
        review_id TEXT PRIMARY KEY,
        place_id TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '',
        review_bucket TEXT NOT NULL DEFAULT '',
        current_action TEXT NOT NULL,
        current_decision TEXT NOT NULL DEFAULT '',
        reviewer TEXT NOT NULL DEFAULT 'local',
        note TEXT NOT NULL DEFAULT '',
        sample_article_uid TEXT NOT NULL DEFAULT '',
        action_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        last_action_id TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_adjudication_actions_item ON adjudication_actions(item_id, created_at);
      CREATE INDEX IF NOT EXISTS idx_adjudication_state_action ON adjudication_item_state(current_action);
      CREATE INDEX IF NOT EXISTS idx_map_geocode_status ON map_geocode_places(geocode_status);
      CREATE INDEX IF NOT EXISTS idx_map_geocode_city ON map_geocode_places(city);
      CREATE INDEX IF NOT EXISTS idx_map_geocode_review_bucket ON map_geocode_review_items(review_bucket);
      CREATE INDEX IF NOT EXISTS idx_map_geocode_review_score ON map_geocode_review_items(event_count, entity_count);
      CREATE INDEX IF NOT EXISTS idx_geocode_review_actions_review ON geocode_review_actions(review_id, created_at);
      CREATE INDEX IF NOT EXISTS idx_geocode_review_state_action ON geocode_review_item_state(current_action);
      CREATE INDEX IF NOT EXISTS idx_articles_article_uid ON articles(article_uid);
      CREATE INDEX IF NOT EXISTS idx_articles_article_id ON articles(article_id);
      CREATE INDEX IF NOT EXISTS idx_articles_source_account ON articles(source_account);
      CREATE INDEX IF NOT EXISTS idx_entities_eid ON entities(eid);
      CREATE INDEX IF NOT EXISTS idx_entities_source_article_uid ON entities(source_article_uid);
      CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
      CREATE INDEX IF NOT EXISTS idx_entities_city ON entities(city);
      CREATE INDEX IF NOT EXISTS idx_events_evid ON events(evid);
      CREATE INDEX IF NOT EXISTS idx_events_source_article_uid ON events(source_article_uid);
      CREATE INDEX IF NOT EXISTS idx_events_place ON events(place);
      CREATE INDEX IF NOT EXISTS idx_events_city ON events(city);
      CREATE INDEX IF NOT EXISTS idx_events_time_iso ON events(time_iso);
    `);
    this.initialized = true;
  }

  async getManifest() {
    const db = await this.db();
    if (this.isServingReadModel(db)) {
      const metadata = sqliteTableExists(db, "build_metadata")
        ? Object.fromEntries(db.prepare("SELECT key, value FROM build_metadata").all().map((row) => [row.key, row.value]))
        : {};
      return {
        schemaVersion: "stage7_atlas_api.manifest.v1",
        releaseReady: metadata.deployable_public !== "0",
        decision: "atlas_serving_read_model_ready",
        channel: "serving_read_model",
        generatedAt: metadata.generated_at || null,
        counts: {
          articles: sqliteCount(db, "evidence_ref"),
          entities: sqliteCount(db, "dj_profile"),
          events: sqliteCount(db, "performance_event"),
          performance_events: sqliteCount(db, "performance_event"),
          dj_profiles: sqliteCount(db, "dj_profile"),
          dj_event_edges: sqliteCount(db, "dj_event"),
          dj_relation_edges_directed: sqliteCount(db, "dj_relation_rollup"),
          search_documents: sqliteCount(db, "search_document"),
          graph_windows: sqliteCount(db, "graph_window_cache"),
          evidence_refs: sqliteCount(db, "evidence_ref"),
          activity_event_detail: sqliteCount(db, "activity_event_detail"),
          activity_evidence_ref: sqliteCount(db, "activity_evidence_ref"),
        },
        publishTimePolicy: {},
        files: {},
        localDb: {
          path: this.exposeInternalDbPath ? this.dbPath : "",
          mode: "serving_read_model_sqlite",
          identity: this.publicDbIdentity(),
        },
        safety: {
          rawSourceUrlColumnsCopied: metadata.raw_source_url_columns_copied === "1",
          archiveHtmlPathColumnsCopied: metadata.archive_html_path_columns_copied === "1",
          publicUrlAllowedDefault: 0,
        },
      };
    }
    const counts = {
      articles: db.prepare("SELECT COUNT(*) AS count FROM articles").get().count,
      entities: db.prepare("SELECT COUNT(*) AS count FROM entities").get().count,
      events: db.prepare("SELECT COUNT(*) AS count FROM events").get().count,
    };
    const sourceCounts = maybeJson(db.prepare("SELECT value FROM metadata WHERE key = 'source_counts'").get()?.value, {});
    return {
      schemaVersion: "stage7_atlas_api.manifest.v1",
      releaseReady: true,
      decision: "atlas_local_sqlite_db_ready",
      channel: "local_sqlite",
      generatedAt: db.prepare("SELECT value FROM metadata WHERE key = 'generated_at'").get()?.value || null,
      counts: { ...sourceCounts, ...counts },
      publishTimePolicy: {},
      files: {},
      localDb: {
        path: this.exposeInternalDbPath ? this.dbPath : "",
        mode: "sqlite",
        identity: this.publicDbIdentity(),
      },
    };
  }

  async getLocalDbStatus() {
    const db = await this.db();
    const manifest = await this.getManifest();
    const map = db
      .prepare(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN lat IS NOT NULL AND lon IS NOT NULL THEN 1 ELSE 0 END) AS geocoded FROM map_geocode_places",
      )
      .get();
    const adjudication = db
      .prepare(
        "SELECT (SELECT COUNT(*) FROM adjudication_actions) AS actions, (SELECT COUNT(*) FROM adjudication_item_state) AS state_rows",
      )
      .get();
    const geocodeReview = db
      .prepare(
        `
        SELECT
          (SELECT COUNT(*) FROM map_geocode_review_items) AS review_rows,
          (SELECT COUNT(*) FROM geocode_review_actions) AS actions,
          (SELECT COUNT(*) FROM geocode_review_item_state) AS state_rows
      `,
      )
      .get();
    const geocodeReviewBuckets = createFacet(
      db
        .prepare(
          "SELECT review_bucket AS label, COUNT(*) AS count FROM map_geocode_review_items GROUP BY review_bucket ORDER BY count DESC",
        )
        .all(),
    );
    return {
      schemaVersion: "stage7_atlas_api.local_sqlite_status.v1",
      generatedAt: new Date().toISOString(),
      dbPath: this.exposeInternalDbPath ? this.dbPath : "",
      dbIdentity: this.publicDbIdentity(),
      manifest,
      map: {
        placeRows: map.total || 0,
        geocodedRows: map.geocoded || 0,
        unresolvedRows: (map.total || 0) - (map.geocoded || 0),
      },
      adjudication,
      geocodeReview: {
        reviewRows: geocodeReview.review_rows || 0,
        actions: geocodeReview.actions || 0,
        stateRows: geocodeReview.state_rows || 0,
        buckets: geocodeReviewBuckets,
      },
      safety: {
        sqliteWriteEnabled: true,
        networkCallExecuted: false,
        llmCallExecuted: false,
        qdrantWriteExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
      },
    };
  }

  async getOverview({ sampleLimit } = {}) {
    const db = await this.db();
    const rowLimit = normalizeLimit(sampleLimit, 80, 160);
    const manifest = await this.getManifest();
    if (this.isServingReadModel(db)) {
      const people = this.servingSearchDocuments(db, { limit: rowLimit, subjectTypes: ["dj"] }).map((row) => this.compactServingSubject(row));
      const venues = this.servingSearchDocuments(db, { limit: rowLimit, subjectTypes: ["venue"] }).map((row) => this.compactServingSubject(row));
      const labels = this.servingSearchDocuments(db, { limit: rowLimit, subjectTypes: ["organizer", "radio"] }).map((row) => this.compactServingSubject(row));
      const events = db
        .prepare(
          `
          SELECT *
          FROM performance_event
          ORDER BY
            CASE WHEN starts_at IS NULL OR starts_at = '' THEN 1 ELSE 0 END,
            starts_at DESC,
            participant_count DESC,
            event_title
          LIMIT ?
        `,
        )
        .all(rowLimit)
        .map((event) =>
          this.enrichServingEventItem(db, {
            evid: event.event_id || "",
            name: event.event_title || "",
            place: event.venue_name || "",
            city: event.city || "",
            time_iso: event.starts_at || "",
            time_text: event.time_text || "",
            participants: [],
            source_article_uid: "",
            confidence: event.confidence ?? null,
          }, event.event_id),
        );
      const mapPlaces = db
        .prepare(
          "SELECT venue_name AS label, COUNT(*) AS count FROM performance_event WHERE venue_name <> '' GROUP BY venue_name ORDER BY count DESC LIMIT 12",
        )
        .all();
      return {
        schemaVersion: "stage7_atlas_api.overview.v1",
        generatedAt: new Date().toISOString(),
        release: {
          releaseReady: manifest.releaseReady,
          decision: manifest.decision,
          channel: manifest.channel,
          generatedAt: manifest.generatedAt,
        },
        counts: manifest.counts,
        publishTimePolicy: manifest.publishTimePolicy,
        facets: {
          cities: createFacet(
            db
              .prepare("SELECT city AS label, COUNT(*) AS count FROM performance_event WHERE city <> '' GROUP BY city ORDER BY count DESC LIMIT 12")
              .all(),
          ),
          mapPlaces: createFacet(mapPlaces),
          entityTypes: createFacet(
            db.prepare("SELECT subject_type AS label, COUNT(*) AS count FROM search_document GROUP BY subject_type ORDER BY count DESC LIMIT 12").all(),
          ),
          eventPlaces: createFacet(mapPlaces),
          sourceAccounts: createFacet(
            db
              .prepare("SELECT source_account AS label, COUNT(*) AS count FROM evidence_ref WHERE source_account <> '' GROUP BY source_account ORDER BY count DESC LIMIT 12")
              .all(),
          ),
        },
        browsingSurfaces: [
          { id: "map", label: "地图", count: mapPlaces.length, samples: createFacet(mapPlaces) },
          { id: "people", label: "人物", count: people.length, samples: people.slice(0, 12) },
          { id: "labels", label: "厂牌", count: labels.length, samples: labels.slice(0, 12) },
          { id: "venues", label: "场地", count: venues.length, samples: venues.slice(0, 12) },
          { id: "scenes", label: "场景", count: events.length, samples: events.slice(0, 12) },
        ],
        samples: {
          articles: [],
          entities: people.slice(0, 12),
          events: events.slice(0, 12),
        },
        recommendations: [],
        graphRagAnswers: [],
        vector: { ok: true, decision: "serving_read_model_sqlite_backed" },
        serviceIntegration: {
          liveVectorSearchEnabled: false,
          searchMode: "atlas_serving_search_document_fts5",
          overviewSampleLimit: rowLimit,
        },
        safety: {
          modelCallExecuted: false,
          llmCallExecuted: false,
          qdrantWriteExecuted: false,
          qdrantAliasChangeExecuted: false,
          neo4jWriteExecuted: false,
          mem0WriteExecuted: false,
        },
      };
    }
    const people = db.prepare("SELECT * FROM entities WHERE LOWER(type) IN ('person') LIMIT ?").all(rowLimit).map(compactEntity);
    const labels = db
      .prepare("SELECT * FROM entities WHERE LOWER(type) IN ('organization','label','brand','group','project') LIMIT ?")
      .all(rowLimit)
      .map(compactEntity);
    const venues = db
      .prepare("SELECT * FROM entities WHERE LOWER(type) IN ('place','venue','location','club') LIMIT ?")
      .all(rowLimit)
      .map(compactEntity);
    const events = db.prepare("SELECT * FROM events ORDER BY row_pk LIMIT ?").all(rowLimit).map(compactEvent);
    const mapPlaces = db
      .prepare(
        "SELECT label, event_count + entity_count AS count FROM map_geocode_places WHERE lat IS NOT NULL AND lon IS NOT NULL ORDER BY count DESC LIMIT 12",
      )
      .all();
    return {
      schemaVersion: "stage7_atlas_api.overview.v1",
      generatedAt: new Date().toISOString(),
      release: {
        releaseReady: manifest.releaseReady,
        decision: manifest.decision,
        channel: manifest.channel,
        generatedAt: manifest.generatedAt,
      },
      counts: manifest.counts,
      publishTimePolicy: manifest.publishTimePolicy,
      facets: {
        cities: createFacet(
          db
            .prepare(
              "SELECT city AS label, COUNT(*) AS count FROM map_geocode_places WHERE city <> '' GROUP BY city ORDER BY count DESC LIMIT 12",
            )
            .all(),
        ),
        mapPlaces: createFacet(mapPlaces),
        entityTypes: createFacet(
          db.prepare("SELECT type AS label, COUNT(*) AS count FROM entities GROUP BY type ORDER BY count DESC LIMIT 12").all(),
        ),
        eventPlaces: createFacet(
          db.prepare("SELECT place AS label, COUNT(*) AS count FROM events WHERE place <> '' GROUP BY place ORDER BY count DESC LIMIT 12").all(),
        ),
        sourceAccounts: createFacet(
          db
            .prepare("SELECT source_account AS label, COUNT(*) AS count FROM articles GROUP BY source_account ORDER BY count DESC LIMIT 12")
            .all(),
        ),
      },
      browsingSurfaces: [
        { id: "map", label: "地图", count: mapPlaces.length, samples: createFacet(mapPlaces) },
        { id: "people", label: "人物", count: people.length, samples: people.slice(0, 12) },
        { id: "labels", label: "厂牌", count: labels.length, samples: labels.slice(0, 12) },
        { id: "venues", label: "场地", count: venues.length, samples: venues.slice(0, 12) },
        { id: "scenes", label: "场景", count: events.length, samples: events.slice(0, 12) },
      ],
      samples: {
        articles: db.prepare("SELECT * FROM articles ORDER BY row_pk LIMIT 12").all().map(compactArticle),
        entities: db.prepare("SELECT * FROM entities ORDER BY row_pk LIMIT 12").all().map(compactEntity),
        events: events.slice(0, 12),
      },
      recommendations: (await this.getRecommendations({ limit: 8 })).recommendations,
      graphRagAnswers: (await this.getGraphRagAnswers({ limit: 4 })).answers,
      vector: { ok: true, decision: "local_sqlite_db_backed" },
      serviceIntegration: {
        liveVectorSearchEnabled: false,
        searchMode: "sqlite_fts5_trigram",
        overviewSampleLimit: rowLimit,
      },
      safety: {
        modelCallExecuted: false,
        llmCallExecuted: false,
        qdrantWriteExecuted: false,
        qdrantAliasChangeExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
      },
    };
  }

  async search({ q, limit, kind } = {}) {
    const db = await this.db();
    if (this.isServingReadModel(db)) return this.searchServingReadModel(db, { q, limit, kind });
    const query = ftsQuery(q);
    const queryText = text(q);
    const pageLimit = normalizeLimit(limit, 20, 100);
    const kinds = kind && KIND_TABLE[kind] ? [kind] : ["articles", "entities", "events"];
    const results = [];
    for (const selectedKind of kinds) {
      const perKindLimit = Math.ceil(pageLimit / kinds.length);
      if (!query) {
        const rows = this.publicRows(
          db,
          db.prepare(`SELECT * FROM ${KIND_TABLE[selectedKind]} ORDER BY row_pk LIMIT ?`).all(perKindLimit * 4),
          selectedKind,
          perKindLimit,
        );
        results.push(...rows.map((row) => ({ kind: selectedKind, score: null, title: rowTitle(row), item: compactRow(row, selectedKind) })));
        continue;
      }
      const rows = sortedSearchRows(
        this.publicRows(db, this.searchKindRows(db, selectedKind, query, Math.max(pageLimit, perKindLimit * 8)), selectedKind, Math.max(pageLimit, perKindLimit * 3)),
        selectedKind,
        queryText,
      ).slice(0, perKindLimit);
      results.push(...rows.map((row) => ({ kind: selectedKind, score: null, title: rowTitle(row), item: compactRow(row, selectedKind) })));
    }
    if (query) {
      results.sort((a, b) => {
        const rankDelta = searchRank(a.item || {}, a.kind, queryText) - searchRank(b.item || {}, b.kind, queryText);
        if (rankDelta) return rankDelta;
        return a.kind.localeCompare(b.kind);
      });
    }
    return {
      schemaVersion: "stage7_atlas_api.search_response.v1",
      query: text(q),
      resultCount: results.length,
      results: results.slice(0, pageLimit),
      retrieval: {
        mode: "sqlite_fts5_trigram",
        liveVectorSearchEnabled: false,
        dbPath: this.exposeInternalDbPath ? this.dbPath : "",
        dbIdentity: this.publicDbIdentity(),
      },
      safety: {
        modelCallExecuted: false,
        qdrantWriteExecuted: false,
        sqliteWriteExecuted: false,
      },
    };
  }

  searchServingReadModel(db, { q, limit, kind } = {}) {
    const query = text(q);
    const pageLimit = normalizeLimit(limit, 20, 100);
    const subjectTypes = this.servingSubjectTypesForKind(kind);
    const rows = this.canonicalizeServingRows(
      db,
      this.servingAliasExpandedSearchDocuments(db, { q: query, limit: pageLimit, subjectTypes }),
    ).slice(0, pageLimit);
    return {
      schemaVersion: "stage7_atlas_api.search_response.v1",
      query,
      resultCount: rows.length,
      results: rows.map((row) => ({
        kind: row.subject_type === "event" ? "events" : "entities",
        score: row.rank_score ?? null,
        title: row.display_name || row.subject_id,
        item: this.compactServingSubject(row),
      })),
      retrieval: {
        mode: this.getEntityMergeGroupIndex().size ? "atlas_serving_search_document_fts5_entity_merge_overlay" : "atlas_serving_search_document_fts5",
        liveVectorSearchEnabled: false,
        entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
        dbPath: this.exposeInternalDbPath ? this.dbPath : "",
        dbIdentity: this.publicDbIdentity(),
      },
      safety: {
        modelCallExecuted: false,
        qdrantWriteExecuted: false,
        sqliteWriteExecuted: false,
      },
    };
  }

  compactServingSubject(row) {
    if (row.subject_type === "event") {
      const event = this.findServingEventById(this.dbHandle, row.subject_id) || {};
      return this.enrichServingEventItem(this.dbHandle, {
        evid: row.subject_id || "",
        name: row.display_name || "",
        place: event.venue_name || "",
        city: row.city_text || event.city || "",
        time_iso: event.starts_at || "",
        time_text: event.time_text || "",
        participants: [],
        source_article_uid: "",
        confidence: null,
      }, row.subject_id);
    }
    return {
      eid: row.subject_id || "",
      name: row.display_name || "",
      type: row.subject_type || "",
      city: row.city_text || "",
      source_article_uid: "",
      confidence: null,
    };
  }

  searchKindRows(db, kind, query, limit) {
    const fts = KIND_FTS[kind];
    const table = KIND_TABLE[kind];
    try {
      return db
        .prepare(`SELECT t.* FROM ${fts} JOIN ${table} t ON t.row_pk = ${fts}.row_pk WHERE ${fts} MATCH ? LIMIT ?`)
        .all(query, limit);
    } catch {
      return [];
    }
  }

  servingSubjectTypesForKind(kind) {
    const raw = text(kind);
    if (raw === "events") return ["event"];
    if (raw === "entities") return ["dj", "venue", "organizer", "radio"];
    return [];
  }

  servingSearchDocuments(db, { q, limit, subjectTypes = [] } = {}) {
    const pageLimit = normalizeLimit(limit, 20, 200);
    const query = text(q);
    const typeFilter = Array.isArray(subjectTypes) && subjectTypes.length
      ? ` AND sd.subject_type IN (${subjectTypes.map(() => "?").join(",")})`
      : "";
    const params = [...(subjectTypes || [])];
    if (query) {
      const likeFallbackRows = () => {
        const like = `%${query}%`;
        return db.prepare(`
          SELECT sd.*
          FROM search_document sd
          WHERE (sd.display_name LIKE ? OR sd.aliases_text LIKE ? OR sd.search_text LIKE ?)${typeFilter}
          ORDER BY sd.rank_score DESC, sd.doc_rowid
          LIMIT ?
        `).all(like, like, like, ...params, pageLimit);
      };
      const cityFallbackRows = () => db.prepare(`
        SELECT sd.*
        FROM search_document sd
        WHERE sd.city_text = ?${typeFilter}
        ORDER BY sd.rank_score DESC, sd.doc_rowid
        LIMIT ?
      `).all(query, ...params, pageLimit);
      const ftsRows = (ftsTable) => db.prepare(`
        SELECT sd.*
        FROM ${ftsTable} f
        JOIN search_document sd ON sd.doc_rowid = f.rowid
        WHERE ${ftsTable} MATCH ?${typeFilter}
        ORDER BY bm25(${ftsTable}), sd.rank_score DESC, sd.doc_rowid
        LIMIT ?
      `).all(ftsQuery(query), ...params, pageLimit);
      const unicodeCompanionRows = () => {
        if (!sqliteTableExists(db, "search_document_fts_unicode61")) return [];
        try {
          return ftsRows("search_document_fts_unicode61");
        } catch {
          return [];
        }
      };
      try {
        const rows = ftsRows("search_document_fts");
        if (rows.length) return rows;
        const unicodeRows = unicodeCompanionRows();
        if (unicodeRows.length) return unicodeRows;
        if (isPublicCityAsPlaceLabel(query) || isShortCjkSearchLabel(query)) {
          const cityRows = cityFallbackRows();
          if (cityRows.length) return cityRows;
        }
        return rows;
      } catch {
        const unicodeRows = unicodeCompanionRows();
        return unicodeRows.length ? unicodeRows : likeFallbackRows();
      }
    }
    return db.prepare(`
      SELECT sd.*
      FROM search_document sd
      WHERE 1=1${typeFilter}
      ORDER BY sd.rank_score DESC, sd.doc_rowid
      LIMIT ?
    `).all(...params, pageLimit);
  }

  servingAliasExpandedSearchDocuments(db, { q, limit, subjectTypes = [] } = {}) {
    const pageLimit = normalizeLimit(limit, 20, 200);
    const query = text(q);
    const baseRows = this.servingSearchDocuments(db, { q: query, limit: pageLimit, subjectTypes });
    const queryKeys = servingCanonicalAliasKeys(query);
    if (!query || queryKeys.length < 2) return baseRows;
    const typeFilter = Array.isArray(subjectTypes) && subjectTypes.length
      ? ` AND subject_type IN (${subjectTypes.map(() => "?").join(",")})`
      : "";
    const typeParams = [...(subjectTypes || [])];
    const expandedRows = [];
    for (const key of queryKeys.slice(1, 8)) {
      const like = `%${key}%`;
      expandedRows.push(...db.prepare(`
        SELECT *
        FROM search_document
        WHERE (display_name LIKE ? OR normalized_name LIKE ? OR aliases_text LIKE ? OR search_text LIKE ?)${typeFilter}
        ORDER BY rank_score DESC, doc_rowid
        LIMIT ?
      `).all(like, like, like, like, ...typeParams, Math.min(pageLimit, 80)));
    }
    const preferredKeys = queryKeys.slice(1);
    return dedupeServingRows([...baseRows, ...expandedRows])
      .sort((a, b) => {
        const rankDelta = servingAliasRank(a, queryKeys, preferredKeys) - servingAliasRank(b, queryKeys, preferredKeys);
        if (rankDelta) return rankDelta;
        return Number(b.rank_score || 0) - Number(a.rank_score || 0);
      })
      .slice(0, pageLimit);
  }

  servingSubjectByIdRaw(db, id) {
    const subjectId = text(id);
    if (!subjectId) return null;
    return db.prepare("SELECT * FROM search_document WHERE subject_id = ? ORDER BY rank_score DESC, doc_rowid LIMIT 1").get(subjectId) || null;
  }

  servingSubjectById(db, id) {
    return this.canonicalServingSubjectForRow(db, this.servingSubjectByIdRaw(db, id));
  }

  findServingEventById(db, id) {
    const eventId = text(id);
    if (!eventId) return null;
    return db.prepare("SELECT * FROM performance_event WHERE event_id = ? LIMIT 1").get(eventId) || null;
  }

  findServingActivityByEventId(db, id) {
    const eventId = text(id);
    if (!eventId || !sqliteTableExists(db, "activity_event_detail")) return null;
    return db.prepare("SELECT * FROM activity_event_detail WHERE event_id = ? LIMIT 1").get(eventId) || null;
  }

  servingActivityEvidenceRefs(db, eventId, limit = 20) {
    if (!sqliteTableExists(db, "activity_evidence_ref")) return [];
    return db.prepare(`
      SELECT field_path, field_value, support_type, source_kind, source_hash, source_account_name,
             source_published_at, quote, quote_policy, ocr_span_status, confidence
      FROM activity_evidence_ref
      WHERE event_id = ?
      ORDER BY confidence DESC, field_path
      LIMIT ?
    `).all(eventId, normalizeLimit(limit, 20, 80));
  }

  compactServingActivity(activity) {
    if (!activity) return null;
    return {
      sourceEventId: activity.source_event_id || "",
      publishPackage: activity.publish_package || "",
      dateStart: activity.event_date_start || "",
      dateEnd: activity.event_date_end || "",
      timeText: activity.event_time_text || "",
      timeStart: activity.time_start || "",
      timeEnd: activity.time_end || "",
      address: activity.address || "",
      lineupArtists: maybeJson(activity.lineup_artists_json, []),
      musicStyles: maybeJson(activity.music_styles_json, []),
      genres: maybeJson(activity.genres_json, []),
      price: maybeJson(activity.price_json, []),
      ticketingText: activity.ticketing_text || "",
      sourceHash: activity.source_hash || "",
      sourceAccountName: activity.source_account_name || "",
      sourcePublishedAt: activity.source_published_at || "",
    };
  }

  enrichServingEventItem(db, item, eventId) {
    const activity = this.findServingActivityByEventId(db, eventId);
    if (!activity) return item;
    const compact = this.compactServingActivity(activity);
    return {
      ...item,
      address: compact.address,
      participants: compact.lineupArtists.slice(0, 20),
      music_styles: compact.musicStyles,
      genres: compact.genres,
      price: compact.price,
      ticketing_text: compact.ticketingText,
      source_hash: compact.sourceHash,
      activity: compact,
    };
  }

  async listKind(kind, { limit, cursor, q } = {}) {
    if (!KIND_TABLE[kind]) throw new Error(`Unsupported Stage7 atlas kind: ${kind}`);
    const db = await this.db();
    if (this.isServingReadModel(db)) {
      const pageLimit = normalizeLimit(limit);
      const offset = normalizeOffset(cursor);
      const subjectTypes = this.servingSubjectTypesForKind(kind);
      const rows = this.servingSearchDocuments(db, { q, limit: pageLimit + offset, subjectTypes }).slice(offset, offset + pageLimit);
      return {
        schemaVersion: "stage7_atlas_api.list_response.v1",
        kind,
        query: text(q) || null,
        page: {
          limit: pageLimit,
          cursor: String(offset),
          nextCursor: rows.length >= pageLimit ? String(offset + rows.length) : null,
          scanned: rows.length,
        },
        items: rows.map((row) => this.compactServingSubject(row)),
      };
    }
    const pageLimit = normalizeLimit(limit);
    const offset = normalizeOffset(cursor);
    const query = ftsQuery(q);
    const rows = query
      ? this.publicRows(db, this.searchKindRows(db, kind, query, (pageLimit + offset) * 4), kind, pageLimit + offset).slice(offset, offset + pageLimit)
      : this.publicRows(db, db.prepare(`SELECT * FROM ${KIND_TABLE[kind]} ORDER BY row_pk LIMIT ? OFFSET ?`).all(pageLimit * 4, offset), kind, pageLimit);
    return {
      schemaVersion: "stage7_atlas_api.list_response.v1",
      kind,
      query: text(q) || null,
      page: {
        limit: pageLimit,
        cursor: String(offset),
        nextCursor: rows.length >= pageLimit ? String(offset + rows.length) : null,
        scanned: rows.length,
      },
      items: rows.map((row) => compactRow(row, kind)),
    };
  }

  async getDetail(kind, id, { relatedLimit } = {}) {
    if (!KIND_TABLE[kind]) throw new Error(`Unsupported Stage7 atlas kind: ${kind}`);
    const db = await this.db();
    if (this.isServingReadModel(db)) return this.getServingDetail(db, kind, id, { relatedLimit });
    const row = this.findRow(db, kind, id);
    if (!this.isPublicRowVisible(db, row, kind)) return null;
    const asset = this.assetForRow(row, kind) || {};
    const pageLimit = normalizeLimit(relatedLimit, 12, 50);
    const sourceArticleUid = row.source_article_uid || row.article_uid || "";
    const sourceArticle = sourceArticleUid ? this.findRow(db, "articles", sourceArticleUid) : null;
    const entities = sourceArticleUid
      ? this.publicRows(db, db.prepare("SELECT * FROM entities WHERE source_article_uid = ? ORDER BY confidence DESC, row_pk LIMIT ?").all(sourceArticleUid, pageLimit * 4), "entities", pageLimit).map(compactEntity)
      : [];
    const events = sourceArticleUid
      ? this.publicRows(db, db.prepare("SELECT * FROM events WHERE source_article_uid = ? ORDER BY confidence DESC, row_pk LIMIT ?").all(sourceArticleUid, pageLimit * 4), "events", pageLimit).map(compactEvent)
      : [];
    return {
      schemaVersion: "stage7_atlas_api.detail_response.v1",
      kind,
      primaryId: primaryDetailId(row, kind),
      matchedBy: this.matchedBy(row, kind, id),
      item: compactRow(row, kind),
      evidence: publicEvidence(row, kind),
      visual: {
        avatarUrl: asset.avatarUrl || "",
        hasAvatar: Boolean(asset.avatarUrl),
      },
      externalLinks: Array.isArray(asset.externalLinks) ? asset.externalLinks : [],
      related: {
        sourceArticle: sourceArticle && !isPublicAtlasNoise(sourceArticle, "articles") ? compactArticle(sourceArticle) : null,
        entities,
        events,
      },
      lookup: {
        mode: "sqlite_index",
        scanned: 1,
      },
      safety: {
        modelCallExecuted: false,
        llmCallExecuted: false,
        qdrantWriteExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
        sqliteWriteExecuted: false,
      },
    };
  }

  getServingDetail(db, kind, id, { relatedLimit } = {}) {
    const pageLimit = normalizeLimit(relatedLimit, 12, 50);
    if (kind === "events") {
      const event = this.findServingEventById(db, id);
      if (!event) return null;
      const eventItem = this.enrichServingEventItem(db, {
        evid: event.event_id,
        name: event.event_title || "",
        place: event.venue_name || "",
        city: event.city || "",
        time_iso: event.starts_at || "",
        time_text: event.time_text || "",
        participants: [],
        source_article_uid: "",
        confidence: event.confidence ?? null,
      }, event.event_id);
      const activityEvidence = this.servingActivityEvidenceRefs(db, event.event_id, pageLimit);
      const djs = db.prepare(`
        SELECT p.dj_id, p.display_name, p.city_primary, de.confidence
        FROM dj_event de
        JOIN dj_profile p ON p.dj_id = de.dj_id
        WHERE de.event_id = ?
        ORDER BY de.confidence DESC, p.event_count DESC
        LIMIT ?
      `).all(event.event_id, pageLimit);
      return {
        schemaVersion: "stage7_atlas_api.detail_response.v1",
        kind,
        primaryId: event.event_id,
        matchedBy: "serving_event_id",
        item: {
          ...eventItem,
          participants: eventItem.participants?.length ? eventItem.participants : djs.map((row) => row.display_name).slice(0, 20),
        },
        evidence: {
          source_kind: eventItem.activity ? "atlas_activity_sidecar" : "serving_rollup",
          source_article_uid: "",
          confidence: event.confidence ?? null,
          quote: activityEvidence[0]?.quote || "",
        },
        related: {
          sourceArticle: null,
          entities: djs.map((row) => ({ eid: row.dj_id, name: row.display_name, type: "dj", city: row.city_primary || "", source_article_uid: "", confidence: row.confidence ?? null })),
          events: [],
        },
        activityEvidence,
        lookup: { mode: "atlas_serving_event_index", scanned: 1 },
        safety: graphSafety(),
      };
    }
    const subject = this.servingSubjectById(db, id);
    if (!subject) return null;
    return {
      schemaVersion: "stage7_atlas_api.detail_response.v1",
      kind,
      primaryId: subject.subject_id,
      matchedBy: "serving_subject_id",
      item: this.compactServingSubject(subject),
      evidence: {
        source_kind: "serving_rollup",
        source_article_uid: "",
        confidence: null,
        quote: "",
      },
      visual: { avatarUrl: "", hasAvatar: false },
      externalLinks: [],
      related: {
        sourceArticle: null,
        entities: [],
        events: [],
      },
      lookup: { mode: "atlas_serving_subject_index", scanned: 1 },
      safety: graphSafety(),
    };
  }

  async getGraphSeed({ q, limit, kind, lod } = {}) {
    const db = await this.db();
    if (this.isServingReadModel(db)) return this.getServingGraphSeed(db, { q, limit, kind, lod });
    const pageLimit = normalizeLimit(limit, 40, 60);
    const hasQuery = Boolean(text(q));
    const selectedKind = normalizeGraphKind(kind);
    const kinds = selectedKind ? [selectedKind] : hasQuery ? ["entities", "events", "articles"] : ["articles"];
    const acc = this.createGraphAccumulator({ nodeLimit: pageLimit });
    const perKindLimit = hasQuery ? Math.max(8, Math.min(36, Math.ceil(pageLimit / 5))) : 12;
    let exactEntitySeeded = false;

    if (hasQuery && (!selectedKind || selectedKind === "entities")) {
      const exactRows = this.exactGraphEntityRows(db, q, Math.min(perKindLimit, 24));
      for (const row of exactRows) {
        this.addGraphSourceForRow(db, acc, "entities", row, { seed: true, perKindLimit });
        exactEntitySeeded = true;
        if (acc.output().returnedNodes >= Math.min(pageLimit, 12)) break;
      }
      if (exactEntitySeeded && acc.output().returnedNodes >= Math.min(pageLimit, 12)) {
        return this.graphResponse(acc, {
          mode: "seed",
          query: text(q) || null,
          kind: selectedKind || null,
          requestedLimit: pageLimit,
          exactEntitySeeded,
          lod,
        });
      }
    }

    const rows = this.graphSeedRows(db, kinds, q, hasQuery ? pageLimit : Math.min(pageLimit, 12));

    for (const item of rows) {
      if (acc.output().returnedNodes >= pageLimit) break;
      this.addGraphSourceForRow(db, acc, item.kind, item.row, { seed: true, perKindLimit });
    }

    return this.graphResponse(acc, {
      mode: "seed",
      query: text(q) || null,
      kind: selectedKind || null,
      requestedLimit: pageLimit,
      exactEntitySeeded,
      lod,
    });
  }

  getServingGraphSeed(db, { q, limit, kind, lod } = {}) {
    const pageLimit = normalizeLimit(limit, 40, 60);
    const query = text(q);
    const subjectTypes = this.servingSubjectTypesForKind(normalizeGraphKind(kind) || kind);
    const candidates = this.canonicalizeServingRows(
      db,
      this.servingAliasExpandedSearchDocuments(db, { q: query, limit: Math.min(pageLimit, 80), subjectTypes }),
    ).slice(0, Math.min(pageLimit, 48));
    const exactQuery = profileNameKey(query);
    const aliasQueryKeys = servingCanonicalAliasKeys(query);
    const preferredAliasKeys = aliasQueryKeys.slice(1);
    const sorted = query
      ? [...candidates].sort((a, b) => {
          const aExact = servingAliasRank(a, aliasQueryKeys.length ? aliasQueryKeys : [exactQuery], preferredAliasKeys);
          const bExact = servingAliasRank(b, aliasQueryKeys.length ? aliasQueryKeys : [exactQuery], preferredAliasKeys);
          if (aExact !== bExact) return aExact - bExact;
          return Number(b.rank_score || 0) - Number(a.rank_score || 0);
        })
      : candidates;
    const exactSubject = query
      ? sorted.find((row) => servingSubjectMatchesAliasKeys(row, aliasQueryKeys.length ? aliasQueryKeys : [exactQuery]))
      : null;
    if (exactSubject) {
      const window = this.servingGraphWindowForSubject(db, exactSubject.subject_id);
      const aliasExpanded = aliasQueryKeys.length > 1 && profileNameKey(exactSubject.display_name) !== exactQuery;
      const meta = {
        mode: "seed",
        query,
        kind: kind || null,
        requestedLimit: pageLimit,
        exactEntitySeeded: true,
        aliasExpanded,
        entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
        lod,
      };
      return window
        ? this.servingGraphResponseFromWindow(window, meta)
        : this.buildServingSubjectGraph(db, exactSubject, { ...meta, limit: pageLimit });
    }
    for (const row of sorted) {
      const window = this.servingGraphWindowForSubject(db, row.subject_id);
      if (window) {
        return this.servingGraphResponseFromWindow(window, {
          mode: "seed",
          query,
          kind: kind || null,
          requestedLimit: pageLimit,
          exactEntitySeeded: query && servingSubjectMatchesAliasKeys(row, aliasQueryKeys.length ? aliasQueryKeys : [exactQuery]),
          entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
          lod,
        });
      }
    }
    return this.buildServingSubjectGraph(db, sorted[0], {
      mode: "seed",
      query,
      kind: kind || null,
      requestedLimit: pageLimit,
      limit: pageLimit,
      entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
      lod,
    });
  }

  servingGraphWindowForSubject(db, subjectId) {
    const id = text(subjectId);
    if (!id || !sqliteTableExists(db, "graph_window_cache")) return null;
    return db.prepare(`
      SELECT *
      FROM graph_window_cache
      WHERE seed_subject_id = ?
      ORDER BY depth DESC, node_count DESC
      LIMIT 1
    `).get(id) || null;
  }

  servingGraphResponseFromWindow(window, meta = {}) {
    const payload = servingGraphWindowPayload(window, { ...meta, dbIdentity: this.publicDbIdentity() });
    payload.retrieval.dbPath = this.exposeInternalDbPath ? this.dbPath : "";
    payload.retrieval.aliasExpanded = Boolean(meta.aliasExpanded);
    payload.retrieval.entityMergeOverlayEnabled = Boolean(meta.entityMergeOverlayEnabled);
    if (payload.meta?.safety) payload.meta.safety.rawDbExposed = Boolean(payload.retrieval.dbPath);
    return payload;
  }

  servingSubjectIdFromGraphRef({ nodeId, id } = {}) {
    const parsed = parseGraphNodeId(nodeId);
    return text(parsed?.id || id || nodeId);
  }

  buildServingSubjectGraph(db, subject, meta = {}) {
    const pageLimit = normalizeLimit(meta.limit || meta.requestedLimit, 120, 300);
    if (!subject) {
      const response = {
        schemaVersion: "stage7_atlas_api.graph_response.v1",
        generatedAt: new Date().toISOString(),
        mode: meta.mode || "seed",
        query: meta.query || null,
        kind: meta.kind || null,
        seed: null,
        depth: meta.depth || null,
        steps: null,
        fanout: null,
        notFound: true,
        nodes: [],
        edges: [],
        limits: { requested: pageLimit, nodeLimit: pageLimit, edgeLimit: GRAPH_EDGE_LIMIT, returnedNodes: 0, returnedEdges: 0 },
        retrieval: {
          mode: "atlas_serving_subject_graph",
          exactEntitySeeded: false,
          liveVectorSearchEnabled: false,
          entityMergeOverlayEnabled: Boolean(meta.entityMergeOverlayEnabled),
          dbPath: this.exposeInternalDbPath ? this.dbPath : "",
          dbIdentity: this.publicDbIdentity(),
        },
        safety: graphSafety(),
      };
      return finalizeGraphViewportResponse(response, {
        lens: meta.lens || "serving_subject_graph",
        lod: meta.lod || "focus",
        sourceNodeCount: 0,
        sourceEdgeCount: 0,
      });
    }

    const nodes = [];
    const edges = [];
    const seenNodes = new Set();
    const addNode = (node) => {
      if (!node || seenNodes.has(node.id) || nodes.length >= pageLimit) return null;
      seenNodes.add(node.id);
      nodes.push(node);
      return node;
    };
    const addEdge = (edge) => {
      if (!edge?.source || !edge?.target || edges.length >= GRAPH_EDGE_LIMIT) return;
      edges.push(edge);
    };
    const seedNode = addNode(servingGraphNode(subject, { seed: true }));
    if (!seedNode) return this.buildServingSubjectGraph(db, null, meta);

    if (subject.subject_type === "venue") {
      const rows = db.prepare(`
        SELECT v.dj_id, v.venue_id, v.venue_name, v.city, v.event_count, v.score, p.display_name, p.event_count AS dj_event_count
        FROM dj_venue_rollup v
        JOIN dj_profile p ON p.dj_id = v.dj_id
        WHERE v.venue_id = ?
        ORDER BY v.score DESC, v.event_count DESC
        LIMIT ?
      `).all(subject.subject_id, Math.min(pageLimit, 80));
      for (const row of rows) {
        const djNode = addNode(servingGraphNode({ subject_id: row.dj_id, subject_type: "dj", display_name: row.display_name, city_text: row.city, rank_score: row.dj_event_count }));
        if (djNode) addEdge({ id: `venue:${row.dj_id}:${row.venue_id}`, source: djNode.id, target: seedNode.id, kind: "frequent_venue", label: "常演场地", weight: Number(row.score || row.event_count || 1), relationshipScore: Number(row.score || 0), directed: false });
      }
      const eventRows = db.prepare("SELECT * FROM performance_event WHERE venue_id = ? ORDER BY starts_at DESC, confidence DESC LIMIT ?").all(subject.subject_id, Math.min(pageLimit, 60));
      for (const event of eventRows) {
        const eventNode = addNode(servingGraphNode({ event_id: event.event_id, type: "event", event_title: event.event_title, city: event.city, venue_name: event.venue_name, weight: event.confidence }));
        if (eventNode) addEdge({ id: `hosted:${event.event_id}:${subject.subject_id}`, source: eventNode.id, target: seedNode.id, kind: "hosted_at", label: "发生于", weight: 2, directed: false });
      }
    } else if (subject.subject_type === "organizer" || subject.subject_type === "radio") {
      const rows = db.prepare(`
        SELECT o.dj_id, o.org_id, o.org_name, o.org_type, o.evidence_count, o.score, o.sample_evidence_json,
               p.display_name, p.city_primary, p.event_count AS dj_event_count
        FROM dj_org_rollup o
        JOIN dj_profile p ON p.dj_id = o.dj_id
        WHERE o.org_id = ?
        ORDER BY o.score DESC, o.evidence_count DESC, p.event_count DESC
        LIMIT ?
      `).all(subject.subject_id, Math.min(pageLimit, 90));
      const djIds = [];
      for (const row of rows) {
        const djNode = addNode(servingGraphNode({ subject_id: row.dj_id, subject_type: "dj", display_name: row.display_name, city_text: row.city_primary, rank_score: row.dj_event_count }));
        if (djNode) {
          djIds.push(row.dj_id);
          addEdge({
            id: `org:${row.dj_id}:${row.org_id}`,
            source: djNode.id,
            target: seedNode.id,
            kind: "organized_by",
            label: "关联厂牌/主办",
            weight: Number(row.score || row.evidence_count || 1),
            relationshipScore: Number(row.score || 0),
            directed: false,
            evidenceCount: Number(row.evidence_count || 0),
            sampleEvidenceIds: sampleEvidenceIds(row.sample_evidence_json || []),
          });
        }
      }
      if (djIds.length) {
        const limitedDjIds = uniqueTexts(djIds, 80);
        const placeholders = limitedDjIds.map(() => "?").join(",");
        const eventRows = db.prepare(`
          SELECT de.dj_id, de.event_id, de.event_title, de.starts_at, de.time_text, de.venue_id, de.venue_name, de.city, de.confidence
          FROM dj_event de
          WHERE de.dj_id IN (${placeholders})
          ORDER BY COALESCE(de.starts_at, '') DESC, de.confidence DESC
          LIMIT ?
        `).all(...limitedDjIds, Math.min(pageLimit, 80));
        for (const event of eventRows) {
          const eventNode = addNode(servingGraphNode({ event_id: event.event_id, type: "event", event_title: event.event_title, city: event.city, venue_name: event.venue_name, weight: event.confidence }));
          if (eventNode) {
            addEdge({
              id: `played:${event.dj_id}:${event.event_id}`,
              source: servingNodeId(event.dj_id, "dj"),
              target: eventNode.id,
              kind: "performed_at",
              label: "参演",
              weight: 3,
              directed: false,
            });
          }
        }
      }
    } else if (subject.subject_type === "event") {
      const event = this.findServingEventById(db, subject.subject_id);
      if (event?.venue_id) {
        const venueNode = addNode(servingGraphNode({ subject_id: event.venue_id, subject_type: "venue", display_name: event.venue_name, city_text: event.city }));
        if (venueNode) addEdge({ id: `hosted:${event.event_id}:${event.venue_id}`, source: seedNode.id, target: venueNode.id, kind: "hosted_at", label: "发生于", weight: 2, directed: false });
      }
      const rows = db.prepare(`
        SELECT de.dj_id, de.confidence, p.display_name, p.city_primary, p.event_count
        FROM dj_event de
        JOIN dj_profile p ON p.dj_id = de.dj_id
        WHERE de.event_id = ?
        ORDER BY de.confidence DESC, p.event_count DESC
        LIMIT ?
      `).all(subject.subject_id, Math.min(pageLimit, 80));
      for (const row of rows) {
        const djNode = addNode(servingGraphNode({ subject_id: row.dj_id, subject_type: "dj", display_name: row.display_name, city_text: row.city_primary, rank_score: row.event_count }));
        if (djNode) addEdge({ id: `played:${row.dj_id}:${subject.subject_id}`, source: djNode.id, target: seedNode.id, kind: "performed_at", label: "参演", weight: 3, directed: false });
      }
    }

    const response = {
      schemaVersion: "stage7_atlas_api.graph_response.v1",
      generatedAt: new Date().toISOString(),
      mode: meta.mode || "seed",
      query: meta.query || null,
      kind: meta.kind || null,
      seed: { nodeId: seedNode.id, kind: seedNode.kind, primaryId: seedNode.primaryId, label: seedNode.label },
      depth: meta.depth || 1,
      steps: null,
      fanout: null,
      notFound: false,
      nodes,
      edges,
      limits: { requested: pageLimit, nodeLimit: pageLimit, edgeLimit: GRAPH_EDGE_LIMIT, returnedNodes: nodes.length, returnedEdges: edges.length },
      retrieval: {
        mode: "atlas_serving_subject_graph",
        exactEntitySeeded: Boolean(meta.exactEntitySeeded),
        aliasExpanded: Boolean(meta.aliasExpanded),
        liveVectorSearchEnabled: false,
        entityMergeOverlayEnabled: Boolean(meta.entityMergeOverlayEnabled),
        dbPath: this.exposeInternalDbPath ? this.dbPath : "",
        dbIdentity: this.publicDbIdentity(),
      },
      safety: graphSafety(),
    };
    return finalizeGraphViewportResponse(response, {
      lens: meta.lens || "serving_subject_graph",
      lod: meta.lod || "focus",
      sourceNodeCount: nodes.length,
      sourceEdgeCount: edges.length,
    });
  }

  getServingGraphSubgraph(db, { nodeId, kind, id, depth, limit, lod } = {}) {
    const pageLimit = normalizeLimit(limit, 120, 300);
    const subjectId = this.servingSubjectIdFromGraphRef({ nodeId, id });
    const subject = this.servingSubjectById(db, subjectId)
      || (subjectId.startsWith("event:") ? { subject_id: subjectId, subject_type: "event", display_name: this.findServingEventById(db, subjectId)?.event_title || subjectId } : null);
    const window = subject ? this.servingGraphWindowForSubject(db, subject.subject_id) : null;
    if (window) {
      return this.servingGraphResponseFromWindow(window, {
        mode: "subgraph",
        requestedLimit: pageLimit,
        depth: normalizeLimit(depth, 1, 3),
        entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
        lod,
        seed: {
          nodeId: servingNodeId(subject.subject_id, subject.subject_type),
          kind: servingGraphKindForType(subject.subject_type),
          primaryId: subject.subject_id,
          label: subject.display_name || subject.subject_id,
        },
      });
    }
    return this.buildServingSubjectGraph(db, subject, {
      mode: "subgraph",
      requestedLimit: pageLimit,
      limit: pageLimit,
      depth: normalizeLimit(depth, 1, 3),
      entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
      lod,
    });
  }

  async getGraphEntityProfile({ q, id, limit, sourceLimit, eventLimit, collaboratorLimit, venueLimit, articleLimit, preferEntities } = {}) {
    const db = await this.db();
    if (this.isServingReadModel(db)) return this.getServingGraphEntityProfile(db, { q, id, limit, sourceLimit, eventLimit, collaboratorLimit, venueLimit, articleLimit, preferEntities });
    const pageLimit = normalizeLimit(limit, 40, 120);
    const sourceWindowLimit = normalizeLimit(sourceLimit, 2_000, 20_000);
    const eventPageLimit = normalizeLimit(eventLimit, 36, 120);
    const collaboratorPageLimit = normalizeLimit(collaboratorLimit, 36, 120);
    const venuePageLimit = normalizeLimit(venueLimit, 24, 80);
    const articlePageLimit = normalizeLimit(articleLimit, 24, 80);
    const seedRows = this.profileSeedEntityRows(db, { q, id, limit: Math.min(pageLimit, 48) });

    if (!seedRows.length) {
      return {
        schemaVersion: "stage7_atlas_api.graph_entity_profile.v1",
        query: text(q) || null,
        id: text(id) || null,
        found: false,
        safety: graphSafety(),
      };
    }

    const seedNames = uniqueTexts(seedRows.map((row) => row.name), 12);
    const profileTerms = this.buildProfileTerms(db, { q, seedRows });
    const names = profileTerms.names.length ? profileTerms.names : seedNames;
    const exact = this.loadProfileEntityRows(db, profileTerms, sourceWindowLimit);
    const visibleEntityRows = this.publicRows(db, exact.rows, "entities", exact.rows.length);
    const sourceArticleUids = exact.sourceArticleUids.length
      ? exact.sourceArticleUids
      : uniqueTexts(visibleEntityRows.map((row) => row.source_article_uid), sourceWindowLimit);
    const relationSourceArticleUids = exact.eventSourceArticleUids?.length
      ? exact.eventSourceArticleUids
      : (exact.allSourceArticleUids?.length ? exact.allSourceArticleUids : sourceArticleUids);
    const sourceWindowTruncated = exact.totalSourceArticles > sourceArticleUids.length;
    const articles = this.loadRowsByArticleUid(db, sourceArticleUids, sourceWindowLimit);
    const relatedEntityRowLimit = Math.min(Math.max(sourceWindowLimit * 16, relationSourceArticleUids.length * 12), 160_000);
    const relatedEventRowLimit = Math.min(Math.max(sourceWindowLimit * 8, relationSourceArticleUids.length * 8), 160_000);
    const relatedEntities = this.loadRowsBySourceArticleUid(db, "entities", relationSourceArticleUids, relatedEntityRowLimit);
    const relatedEventRows = profileTerms.expandedByAliases
      ? this.loadProfileEventRows(db, profileTerms, exact.accountSourceArticleUids || [], relatedEventRowLimit)
      : this.loadRowsBySourceArticleUid(db, "events", relationSourceArticleUids, relatedEventRowLimit);
    const relatedEvents = this.publicRows(
      db,
      relatedEventRows,
      "events",
      relatedEventRowLimit,
    );
    const seedKeys = new Set(names.map(profileNameKey));
    const typeCounts = new Map();
    const sourceAccountCounts = new Map();
    const cityCounts = new Map();
    const venueCounts = new Map();
    const collaboratorCounts = new Map();
    const organizationCounts = new Map();
    const articleByUid = new Map(articles.map((row) => [row.article_uid, row]));

    for (const row of visibleEntityRows) {
      countBy(typeCounts, row.type || "entity");
      countBy(cityCounts, row.city);
    }

    for (const article of articles) {
      if (isPublicAtlasNoise(article, "articles")) continue;
      countBy(sourceAccountCounts, article.source_account, 1, article.article_uid);
    }

    for (const event of relatedEvents) {
      if (!isPublicCityAsPlaceLabel(event.place)) countBy(venueCounts, event.place);
      countBy(cityCounts, event.city);
      for (const participant of maybeJson(event.participants_json, [])) {
        if (!seedKeys.has(profileNameKey(participant))) countBy(collaboratorCounts, participant, 1, event.source_article_uid);
      }
      for (const organizer of maybeJson(event.organizers_json, [])) {
        if (!seedKeys.has(profileNameKey(organizer))) countBy(organizationCounts, organizer, 1, event.source_article_uid);
      }
    }

    for (const row of this.publicRows(db, relatedEntities, "entities", relatedEntities.length)) {
      const key = profileNameKey(row.name);
      if (!key || seedKeys.has(key)) continue;
      const type = text(row.type).toLowerCase();
      if (type === "person" || type === "dj" || type === "artist") {
        countBy(collaboratorCounts, row.name, 1, row.source_article_uid);
      } else if (["organization", "label", "brand", "group", "project", "venue", "club"].includes(type)) {
        countBy(organizationCounts, row.name, 1, row.source_article_uid);
      }
    }

    const eventSample = relatedEvents
      .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0) || Number(b.row_pk || 0) - Number(a.row_pk || 0))
      .slice(0, eventPageLimit)
      .map(compactEvent);
    const articleSample = articles
      .filter((row) => !isPublicAtlasNoise(row, "articles"))
      .sort((a, b) => Number(b.entity_count || 0) + Number(b.event_count || 0) - (Number(a.entity_count || 0) + Number(a.event_count || 0)))
      .slice(0, articlePageLimit)
      .map(compactArticle);
    const identityRows = this.loadIdentityProfileRows(db, names, Math.min(12, pageLimit));
    const assetLinks = [];
    for (const row of seedRows) {
      const asset = this.assetForRow(row, "entities");
      if (asset?.externalLinks?.length) assetLinks.push(...asset.externalLinks);
    }

    const primarySeed = visibleEntityRows[0] || seedRows[0];
    const soundSystemEvidence = this.soundSystemEvidenceForSubject({
      eid: primaryDetailId(primarySeed, "entities"),
      name: primarySeed.name,
      display_name: primarySeed.name,
    });
    return {
      schemaVersion: "stage7_atlas_api.graph_entity_profile.v1",
      query: text(q) || null,
      id: text(id) || null,
      found: true,
      canonical: {
        name: primarySeed.name || seedNames[0] || names[0] || "",
        primaryType: text(primarySeed.type) || topCounts(typeCounts, 1)[0]?.label || "entity",
        names: names.slice(0, 24),
        primaryId: primaryDetailId(primarySeed, "entities"),
        nodeId: graphNodeId("entities", primarySeed),
      },
      summary: {
        exactEntityRows: exact.totalRows,
        loadedEntityRows: visibleEntityRows.length,
        sourceArticleCount: exact.totalSourceArticles,
        loadedSourceArticles: sourceArticleUids.length,
        eventCount: exact.totalEvents || relatedEvents.length,
        loadedEventRows: relatedEvents.length,
        collaboratorCount: collaboratorCounts.size,
        organizationCount: organizationCounts.size,
        canonicalNameCount: names.length,
        sourceWindowTruncated,
        relationWindowTruncated: Boolean(exact.totalEvents && relatedEvents.length < exact.totalEvents),
      },
      taxonomy: {
        types: topCounts(typeCounts, 12),
        cities: topCounts(cityCounts, 12),
      },
      sources: {
        accounts: topCounts(sourceAccountCounts, pageLimit),
        articles: articleSample,
      },
      history: {
        events: eventSample,
        venues: topCounts(venueCounts, venuePageLimit),
      },
      relationships: {
        collaborators: topCounts(collaboratorCounts, collaboratorPageLimit),
        organizations: topCounts(organizationCounts, collaboratorPageLimit),
      },
      publicProfiles: {
        externalLinks: uniqueTexts(assetLinks.map((item) => item.url), 12).map((url) => assetLinks.find((item) => item.url === url)).filter(Boolean),
        identityCandidates: identityRows.map((row) => ({
          itemId: row.item_id || "",
          subjectName: row.subject_name || "",
          subjectType: row.subject_type || "",
          url: row.url || "",
          domain: row.domain || "",
          status: row.status || "",
          bucket: row.bucket || "",
          supportCount: row.support_count || 0,
          acceptedForGraph: Boolean(row.accepted_for_graph),
          identityProof: Boolean(row.identity_proof),
        })),
      },
      attributes: {
        soundSystemSummary: this.soundSystemSummary(soundSystemEvidence),
        soundSystemEvidence,
      },
      retrieval: {
        mode: profileTerms.expandedByAliases ? "sqlite_canonical_alias_profile_rollup" : "sqlite_full_entity_profile_rollup",
        exactNameIndexed: true,
        canonicalAliasExpanded: Boolean(profileTerms.expandedByAliases),
        canonicalAliasCounts: {
          names: profileTerms.names.length,
          sourceAccounts: profileTerms.sourceAccounts.length,
          places: profileTerms.places.length,
        },
        sourceArticleWindowLimit: sourceWindowLimit,
        dbIdentity: this.publicDbIdentity(),
      },
      safety: graphSafety(),
    };
  }

  getServingGraphEntityProfile(db, { q, id, limit, sourceLimit, eventLimit, collaboratorLimit, venueLimit, articleLimit, preferEntities } = {}) {
    const pageLimit = normalizeLimit(limit, 40, 120);
    const eventPageLimit = normalizeLimit(eventLimit, 36, 120);
    const collaboratorPageLimit = normalizeLimit(collaboratorLimit, 36, 120);
    const venuePageLimit = normalizeLimit(venueLimit, 24, 80);
    const articlePageLimit = normalizeLimit(articleLimit, 24, 80);
    const selectedId = text(id);
    const defaultSeed = () => this.canonicalizeServingRows(db, this.servingSearchDocuments(db, { q, limit: 12 }))[0];
    const entitySeed = () => this.canonicalizeServingRows(
      db,
      this.servingSearchDocuments(db, { q, limit: 12, subjectTypes: this.servingSubjectTypesForKind("entities") }),
    )[0];
    const eventSeed = () => {
      if (!selectedId.startsWith("event:")) return null;
      const event = this.findServingEventById(db, selectedId);
      if (!event) return null;
      return {
        subject_id: event.event_id,
        subject_type: "event",
        display_name: event.event_title || event.event_id,
        city_text: event.city || "",
        taxon_path: "活动/演出",
        rank_score: event.confidence || 0,
        aliases_text: "",
      };
    };
    const seed = selectedId
      ? this.servingSubjectById(db, selectedId) || eventSeed()
      : (preferEntities ? entitySeed() || defaultSeed() : defaultSeed());

    if (!seed) {
      return {
        schemaVersion: "stage7_atlas_api.graph_entity_profile.v1",
        query: text(q) || null,
        id: selectedId || null,
        found: false,
        safety: graphSafety(),
      };
    }

    const type = text(seed.subject_type);
    const scope = this.servingProfileMergeScope(db, seed, { selectedId, query: q });
    const fullScopeRows = scope.rows.length ? scope.rows : [seed];
    const scopeRows = scope.aggregationRows?.length ? scope.aggregationRows : fullScopeRows;
    const scopeNames = scope.names.length ? scope.names : uniqueTexts([seed.display_name, ...(text(seed.aliases_text).split(/\s+/))], 24);
    const scopeDjIdSet = new Set(scope.allDjIds?.length ? scope.allDjIds : scope.djIds);
    const sourceAccountCounts = new Map();
    const cityCounts = new Map();
    const typeCounts = new Map();
    for (const row of fullScopeRows) {
      countBy(typeCounts, row.subject_type || type || "entity");
      countBy(cityCounts, row.city_text);
    }
    let articles = [];
    const eventById = new Map();
    const collaboratorById = new Map();
    const venueById = new Map();
    const orgById = new Map();
    const sourceRefs = [];
    const addSourceRef = (value) => {
      const item = text(value);
      if (item && !sourceRefs.includes(item)) sourceRefs.push(item);
    };
    const addEvents = (rows) => {
      for (const row of rows || []) {
        const eventId = text(row.evid || row.event_id);
        if (!eventId || eventById.has(eventId)) continue;
        eventById.set(eventId, row);
        addSourceRef(row.source_ref_id);
      }
    };
    const upsertRanked = (map, key, row) => {
      const id = text(key);
      if (!id) return;
      const existing = map.get(id);
      if (!existing) {
        map.set(id, row);
        return;
      }
      existing.relationship_score = Math.max(finiteNumber(existing.relationship_score ?? existing.score, 0), finiteNumber(row.relationship_score ?? row.score, 0));
      existing.score = Math.max(finiteNumber(existing.score, 0), finiteNumber(row.score, 0));
      existing.same_event_count = finiteNumber(existing.same_event_count, 0) + finiteNumber(row.same_event_count, 0);
      existing.activity_count = finiteNumber(existing.activity_count ?? existing.event_count, 0) + finiteNumber(row.activity_count ?? row.event_count, 0);
      existing.evidence_count = finiteNumber(existing.evidence_count, 0) + finiteNumber(row.evidence_count, 0);
      if (!existing.sample && row.sample) existing.sample = row.sample;
    };
    const upsertCollaborator = (row) => {
      const peerId = text(row.eid || row.dj_id);
      if (scopeDjIdSet.has(peerId)) return;
      upsertRanked(collaboratorById, peerId || row.name || row.display_name, { ...row, eid: peerId || row.eid, type: row.type || "dj" });
    };
    const upsertVenue = (row) => upsertRanked(venueById, row.venue_id || row.label || row.venue_name, row);
    const upsertOrg = (row) => upsertRanked(orgById, row.org_id || row.label || row.org_name, row);
    const aggregateProfile = scope.djIds.length
      ? db.prepare(`
        SELECT COALESCE(SUM(source_article_count),0) AS source_article_count,
               COALESCE(SUM(event_count),0) AS event_count,
               COALESCE(SUM(venue_count),0) AS venue_count,
               COALESCE(SUM(collaborator_count),0) AS collaborator_count,
               COALESCE(SUM(organization_count),0) AS organization_count,
               MAX(confidence) AS confidence,
               MAX(city_primary) AS city_primary
        FROM dj_profile
        WHERE dj_id IN (${scope.djIds.map(() => "?").join(",")})
      `).get(...scope.djIds) || {}
      : {};
    let summary = {
      exactEntityRows: 1,
        loadedEntityRows: scopeRows.length,
        candidateEntityRows: fullScopeRows.length,
        sourceArticleCount: 0,
      loadedSourceArticles: 0,
      eventCount: 0,
      loadedEventRows: 0,
      collaboratorCount: 0,
      organizationCount: 0,
      canonicalNameCount: 1,
      sourceWindowTruncated: false,
      relationWindowTruncated: false,
    };

    if (scope.djIds.length) {
      const placeholders = scope.djIds.map(() => "?").join(",");
      addEvents(db.prepare(`
        SELECT event_id AS evid, event_title AS name, venue_name AS place, city, starts_at AS time_iso, time_text, confidence, source_ref_id
        FROM dj_event
        WHERE dj_id IN (${placeholders})
        ORDER BY COALESCE(starts_at, '') DESC, confidence DESC
        LIMIT ?
      `).all(...scope.djIds, Math.max(eventPageLimit, scope.djIds.length * eventPageLimit)));
      db.prepare(`
        SELECT r.dst_dj_id AS eid, p.display_name AS name, 'dj' AS type, p.city_primary AS city,
               MAX(r.relation_score) AS relationship_score,
               SUM(r.same_event_count) AS same_event_count,
               MAX(r.relation_label_zh) AS relation_label_zh
        FROM dj_relation_rollup r
        JOIN dj_profile p ON p.dj_id = r.dst_dj_id
        WHERE r.src_dj_id IN (${placeholders})
          AND r.dst_dj_id NOT IN (${placeholders})
        GROUP BY r.dst_dj_id
        ORDER BY relationship_score DESC, same_event_count DESC
        LIMIT ?
      `).all(...scope.djIds, ...scope.djIds, collaboratorPageLimit).forEach(upsertCollaborator);
      db.prepare(`
        SELECT venue_id, venue_name AS label, SUM(event_count) AS activity_count, city,
               MIN(first_seen_at) AS first_seen_at, MAX(last_seen_at) AS last_seen_at,
               MAX(score) AS relationship_score
        FROM dj_venue_rollup
        WHERE dj_id IN (${placeholders})
        GROUP BY venue_id, venue_name, city
        ORDER BY relationship_score DESC, activity_count DESC
        LIMIT ?
      `).all(...scope.djIds, venuePageLimit).forEach(upsertVenue);
      db.prepare(`
        SELECT org_id, org_name AS label, SUM(evidence_count) AS evidence_count, org_type, MAX(score) AS relationship_score
        FROM dj_org_rollup
        WHERE dj_id IN (${placeholders})
        GROUP BY org_id, org_name, org_type
        ORDER BY relationship_score DESC, evidence_count DESC
        LIMIT ?
      `).all(...scope.djIds, collaboratorPageLimit).forEach(upsertOrg);
      countBy(cityCounts, aggregateProfile.city_primary || seed.city_text);
    }

    if (scope.venueIds.length) {
      const placeholders = scope.venueIds.map(() => "?").join(",");
      db.prepare(`
        SELECT v.dj_id, p.display_name AS name, p.city_primary AS city,
               SUM(v.event_count) AS activity_count,
               MAX(v.score) AS relationship_score
        FROM dj_venue_rollup v
        JOIN dj_profile p ON p.dj_id = v.dj_id
        WHERE v.venue_id IN (${placeholders})
        GROUP BY v.dj_id, p.display_name, p.city_primary
        ORDER BY relationship_score DESC, activity_count DESC
        LIMIT ?
      `).all(...scope.venueIds, collaboratorPageLimit).forEach(upsertCollaborator);
      addEvents(db.prepare(`
        SELECT event_id AS evid, event_title AS name, venue_name AS place, city, starts_at AS time_iso, time_text, confidence, source_ref_id
        FROM performance_event
        WHERE venue_id IN (${placeholders})
        ORDER BY COALESCE(starts_at, '') DESC, confidence DESC
        LIMIT ?
      `).all(...scope.venueIds, eventPageLimit));
      for (const row of scopeRows.filter((item) => text(item.subject_type) === "venue")) {
        upsertVenue({
          venue_id: row.subject_id,
          label: row.display_name,
          activity_count: 0,
          city: row.city_text || "",
          relationship_score: row.rank_score,
        });
      }
    }

    if (type === "event") {
      const event = this.findServingEventById(db, seed.subject_id);
      if (event) {
        addEvents([event]);
        addSourceRef(event.source_ref_id);
        if (event.venue_id || event.venue_name) {
          upsertVenue({
            venue_id: event.venue_id || event.venue_name,
            label: event.venue_name || event.venue_id,
            activity_count: 1,
            city: event.city || "",
            relationship_score: finiteNumber(event.confidence, 0) * 10,
            source_ref_id: event.source_ref_id || "",
          });
        }
        const eventDjRows = db.prepare(`
          SELECT de.dj_id, de.confidence, de.source_ref_id, p.display_name AS name, p.city_primary AS city, p.event_count
          FROM dj_event de
          JOIN dj_profile p ON p.dj_id = de.dj_id
          WHERE de.event_id = ?
          ORDER BY de.confidence DESC, p.event_count DESC
          LIMIT ?
        `).all(seed.subject_id, collaboratorPageLimit);
        for (const row of eventDjRows) {
          upsertCollaborator({
            eid: row.dj_id,
            name: row.name || row.dj_id,
            type: "dj",
            city: row.city || "",
            relationship_score: Math.round(finiteNumber(row.confidence, 0) * 100) / 10,
            same_event_count: 1,
            relation_label_zh: "参演",
            source_ref_id: row.source_ref_id || event.source_ref_id || "",
          });
          addSourceRef(row.source_ref_id || event.source_ref_id);
        }
        countBy(cityCounts, event.city);
      }
    }

    if (scope.orgIds.length) {
      const placeholders = scope.orgIds.map(() => "?").join(",");
      const orgRows = db.prepare(`
        SELECT o.dj_id, p.display_name AS name, p.city_primary AS city,
               SUM(o.evidence_count) AS evidence_count,
               MAX(o.score) AS relationship_score,
               MAX(o.sample_evidence_json) AS sample_evidence_json
        FROM dj_org_rollup o
        JOIN dj_profile p ON p.dj_id = o.dj_id
        WHERE o.org_id IN (${placeholders})
        GROUP BY o.dj_id, p.display_name, p.city_primary
        ORDER BY relationship_score DESC, evidence_count DESC
        LIMIT ?
      `).all(...scope.orgIds, collaboratorPageLimit);
      orgRows.forEach((row) => {
        upsertCollaborator(row);
        for (const ref of sampleEvidenceIds(row.sample_evidence_json || [])) addSourceRef(ref);
      });
      const linkedDjIds = uniqueTexts(orgRows.map((row) => row.dj_id), 80);
      if (!eventById.size && linkedDjIds.length) {
        const djPlaceholders = linkedDjIds.map(() => "?").join(",");
        addEvents(db.prepare(`
          SELECT event_id AS evid, event_title AS name, venue_name AS place, city, starts_at AS time_iso, time_text, confidence, source_ref_id
          FROM dj_event
          WHERE dj_id IN (${djPlaceholders})
          ORDER BY COALESCE(starts_at, '') DESC, confidence DESC
          LIMIT ?
        `).all(...linkedDjIds, eventPageLimit));
      }
    }

    let events = Array.from(eventById.values())
      .sort((a, b) => text(b.time_iso || b.starts_at).localeCompare(text(a.time_iso || a.starts_at)) || finiteNumber(b.confidence, 0) - finiteNumber(a.confidence, 0))
      .slice(0, eventPageLimit);
    let collaborators = Array.from(collaboratorById.values())
      .sort((a, b) => finiteNumber(b.relationship_score ?? b.score, 0) - finiteNumber(a.relationship_score ?? a.score, 0))
      .slice(0, collaboratorPageLimit);
    let venues = Array.from(venueById.values())
      .sort((a, b) => finiteNumber(b.relationship_score ?? b.score, 0) - finiteNumber(a.relationship_score ?? a.score, 0))
      .slice(0, venuePageLimit);
    let orgs = Array.from(orgById.values())
      .sort((a, b) => finiteNumber(b.relationship_score ?? b.score, 0) - finiteNumber(a.relationship_score ?? a.score, 0))
      .slice(0, collaboratorPageLimit);

    const articleRefs = uniqueTexts(sourceRefs, Math.max(articlePageLimit, articlePageLimit * 3));
    if (articleRefs.length) {
      const placeholders = articleRefs.map(() => "?").join(",");
      articles = db.prepare(`
        SELECT source_ref_id, source_account, source_title, post_date, public_snippet
        FROM evidence_ref
        WHERE source_ref_id IN (${placeholders})
        ORDER BY post_date DESC
        LIMIT ?
      `).all(...articleRefs, articlePageLimit);
    }
    summary = {
      ...summary,
      sourceArticleCount: Math.max(finiteNumber(aggregateProfile.source_article_count, 0), articles.length),
      loadedSourceArticles: articles.length,
      eventCount: Math.max(finiteNumber(aggregateProfile.event_count, 0), events.length),
      loadedEventRows: events.length,
      collaboratorCount: Math.max(finiteNumber(aggregateProfile.collaborator_count, 0), collaborators.length),
      organizationCount: Math.max(finiteNumber(aggregateProfile.organization_count, 0), orgs.length),
      canonicalNameCount: scopeNames.length,
      relationWindowTruncated: Boolean(finiteNumber(aggregateProfile.event_count, 0) && events.length < finiteNumber(aggregateProfile.event_count, 0)),
    };

    for (const event of events) countBy(cityCounts, event.city);
    for (const article of articles) countBy(sourceAccountCounts, article.source_account, 1, article.source_ref_id);
    const soundSystemEvidence = this.soundSystemEvidenceForSubjects(scopeRows);

    return {
      schemaVersion: "stage7_atlas_api.graph_entity_profile.v1",
      query: text(q) || null,
      id: selectedId || null,
      found: true,
      canonical: {
        name: seed.display_name || seed.subject_id,
        primaryType: type || "entity",
        names: scopeNames,
        primaryId: seed.subject_id,
        nodeId: servingNodeId(seed.subject_id, type),
      },
      summary,
      taxonomy: {
        types: topCounts(typeCounts, 12),
        cities: topCounts(cityCounts, 12),
      },
      sources: {
        accounts: topCounts(sourceAccountCounts, pageLimit),
        articles: articles.map((row) => ({
          article_id: row.source_ref_id || "",
          article_uid: row.source_ref_id || "",
          title: row.source_title || "",
          source_account: row.source_account || "",
          publish_time_status: row.post_date || "",
          public_snippet: textPreview(row.public_snippet || "", 180),
          entity_count: 0,
          event_count: 0,
          quality_grade: "",
        })),
      },
      history: {
        events: events.map((row) => this.enrichServingEventItem(db, {
          evid: row.evid || row.event_id || "",
          name: row.name || row.event_title || "",
          place: row.place || row.venue_name || "",
          city: row.city || "",
          time_iso: row.time_iso || row.starts_at || "",
          time_text: row.time_text || "",
          participants: [],
          source_article_uid: "",
          confidence: row.confidence ?? null,
        }, row.evid || row.event_id || "")),
        venues,
      },
      relationships: {
        collaborators: collaborators.map((row) => ({
          eid: row.eid || row.dj_id || "",
          label: row.name || row.display_name || "",
          type: row.type || "dj",
          relationshipScore: finiteNumber(row.relationship_score ?? row.score, 0),
          relationScore: finiteNumber(row.relationship_score ?? row.score, 0),
          sameEventCount: finiteNumber(row.same_event_count, 0),
        sourceRefId: row.source_ref_id || "",
        sampleEvidenceIds: sampleEvidenceIds(row.sample_evidence_json || []),
        sample: publicGraphEdgeLabel("dj_collaboration", row.relation_label_zh || ""),
      })),
      organizations: orgs.map((row) => ({
        label: row.label || "",
        relationshipScore: finiteNumber(row.relationship_score ?? row.score, 0),
        relationScore: finiteNumber(row.relationship_score ?? row.score, 0),
        evidenceCount: finiteNumber(row.evidence_count, 0),
        sourceRefId: row.source_ref_id || "",
        sampleEvidenceIds: sampleEvidenceIds(row.sample_evidence_json || []),
        sample: "",
      })),
      },
      publicProfiles: {
        externalLinks: [],
        identityCandidates: [],
      },
      attributes: {
        soundSystemSummary: this.soundSystemSummary(soundSystemEvidence),
        soundSystemEvidence,
      },
      retrieval: {
        mode: this.getEntityMergeGroupIndex().size ? "atlas_serving_dj_first_rollup_entity_merge_overlay" : "atlas_serving_dj_first_rollup",
        exactNameIndexed: true,
        canonicalAliasExpanded: Boolean(scope.group || seed.merge_overlay),
        canonicalAliasCounts: {
          names: scopeNames.length,
          sourceAccounts: 0,
          places: scope.allVenueIds?.length || scope.venueIds.length,
          aggregationSubjects: scopeRows.length,
        },
        sourceArticleWindowLimit: normalizeLimit(sourceLimit, 2_000, 20_000),
        entityMergeOverlayEnabled: this.getEntityMergeGroupIndex().size > 0,
        entityMergePlan: scope.group ? {
          groupId: scope.group.groupId,
          canonicalSubjectId: scope.group.canonicalSubjectId,
          memberCount: scope.group.memberCount,
          aggregationMemberCount: scopeRows.length,
          aggregationMemberLimit: scope.aggregationLimit,
          aggregationTruncated: fullScopeRows.length > scopeRows.length,
          reportOnly: scope.group.reportOnly !== false,
        } : null,
        dbIdentity: this.publicDbIdentity(),
      },
      safety: graphSafety(),
    };
  }

  async getGraphMobileProfile({ q, id, limit, eventLimit, collaboratorLimit, venueLimit, articleLimit } = {}) {
    const profile = await this.getGraphEntityProfile({
      q,
      id,
      limit: limit || 24,
      sourceLimit: 500,
      eventLimit: eventLimit || 8,
      collaboratorLimit: collaboratorLimit || 10,
      venueLimit: venueLimit || 8,
      articleLimit: articleLimit || 5,
      preferEntities: true,
    });
    return this.compactGraphMobileProfile(profile);
  }

  compactGraphMobileProfile(profile) {
    const canonical = profile?.canonical || {};
    const primaryId = text(canonical.primaryId || profile?.id);
    const title = text(canonical.name || profile?.query || primaryId);
    const query = text(profile?.query || title);
    if (!profile?.found) {
      return {
        schemaVersion: "stage7_atlas_api.graph_mobile_profile.v1",
        query: query || null,
        id: primaryId || null,
        found: false,
        header: null,
        sections: [],
        quickActions: [],
        payloadPolicy: mobilePayloadPolicy(),
        safety: graphSafety(),
      };
    }

    const graphSeedPath = `/api/v1/stage7/graph/seed?q=${encodeURIComponent(title)}&limit=48&lod=focus`;
    const mobileProfilePath = primaryId
      ? `/api/v1/stage7/graph/mobile-profile?id=${encodeURIComponent(primaryId)}`
      : `/api/v1/stage7/graph/mobile-profile?q=${encodeURIComponent(title)}`;
    const entityMerge = this.compactEntityMergeGroup(this.entityMergeGroupForProfile(profile), 18);
    const soundSystem = {
      summary: profile.attributes?.soundSystemSummary || this.soundSystemSummary([]),
      evidence: (profile.attributes?.soundSystemEvidence || []).slice(0, 3).map((row) => ({
        venueId: row.venueId || "",
        venueName: row.venueName || "",
        city: row.city || "",
        terms: uniqueTexts(row.terms || [], 8),
        confidence: finiteNumber(row.confidence, 0),
        evidenceCount: finiteNumber(row.evidenceCount, 0),
        sourceCount: finiteNumber(row.sourceCount, 0),
        evidence: (row.evidence || []).slice(0, 3).map((item) => ({
          sourceRefId: item.sourceRefId || "",
          sourceAccount: item.sourceAccount || "",
          sourceTitle: item.sourceTitle || "",
          postDate: item.postDate || "",
          eventId: item.eventId || "",
          eventTitle: item.eventTitle || "",
          matchedTerms: uniqueTexts(item.matchedTerms || [], 8),
          publicSnippet: textPreview(item.publicSnippet, 120),
          tap: {
            action: "open_source_evidence",
            sourceRefId: item.sourceRefId || "",
          },
        })),
        reportOnly: row.reportOnly !== false,
      })),
    };

    const aliasItems = entityMerge.available
      ? entityMerge.aliases
      : uniqueTexts(canonical.names || [title], 18).map((name) => ({
          name,
          query: name,
          tap: {
            action: "search_entity",
            query: name,
            apiPath: `/api/v1/stage7/graph/mobile-profile?q=${encodeURIComponent(name)}`,
          },
        }));

    const eventItems = (profile.history?.events || []).slice(0, 8).map((event) => ({
      id: event.evid || event.event_id || "",
      title: event.name || event.event_title || "",
      subtitle: uniqueTexts([event.time_text || event.time_iso, event.place, event.city], 3).join(" · "),
      time: event.time_text || event.time_iso || "",
      venue: event.place || "",
      city: event.city || "",
      confidence: event.confidence ?? null,
      tap: {
        action: "open_event",
        id: event.evid || event.event_id || "",
        apiPath: `/api/v1/stage7/events/${encodeURIComponent(event.evid || event.event_id || "")}`,
      },
    }));
    const collaboratorItems = (profile.relationships?.collaborators || []).slice(0, 10).map((row) => ({
      label: row.label || "",
      relationshipScore: finiteNumber(row.relationshipScore ?? row.relationScore ?? row.count, 0),
      sameEventCount: finiteNumber(row.sameEventCount ?? row.count, 0),
      sample: row.sample || "",
      tap: {
        action: "open_entity_profile",
        query: row.label || "",
        apiPath: `/api/v1/stage7/graph/mobile-profile?q=${encodeURIComponent(row.label || "")}`,
      },
    }));
    const organizationItems = (profile.relationships?.organizations || []).slice(0, 8).map((row) => ({
      label: row.label || "",
      relationshipScore: finiteNumber(row.relationshipScore ?? row.relationScore ?? row.count, 0),
      evidenceCount: finiteNumber(row.evidenceCount ?? row.count, 0),
      tap: {
        action: "open_entity_profile",
        query: row.label || "",
        apiPath: `/api/v1/stage7/graph/mobile-profile?q=${encodeURIComponent(row.label || "")}`,
      },
    }));
    const venueItems = (profile.history?.venues || []).slice(0, 8).map((row) => ({
      label: row.label || "",
      city: row.city || "",
      relationshipScore: finiteNumber(row.relationshipScore ?? row.score ?? row.count, 0),
      activityCount: finiteNumber(row.activity_count ?? row.activityCount ?? row.count, 0),
      tap: {
        action: "open_entity_profile",
        query: row.label || "",
        apiPath: `/api/v1/stage7/graph/mobile-profile?q=${encodeURIComponent(row.label || "")}`,
      },
    }));
    const sourceItems = (profile.sources?.articles || []).slice(0, 5).map((row) => ({
      sourceRefId: row.article_id || row.article_uid || row.source_ref_id || "",
      title: row.title || row.source_title || "",
      account: row.source_account || "",
      date: row.publish_time_status || row.post_date || "",
      snippet: textPreview(row.public_snippet || row.snippet || "", 120),
      tap: {
        action: "open_source_evidence",
        sourceRefId: row.article_id || row.article_uid || row.source_ref_id || "",
      },
    }));

    const sections = [
      mobileSection("aliases", "同一实体 / 别名", "chips", aliasItems, {
        badge: entityMerge.available ? `${entityMerge.memberCount} 个候选名` : `${aliasItems.length} 个名称`,
        reportOnly: entityMerge.reportOnly,
      }),
      mobileSection("history", "历史活动", "timeline", eventItems, { emptyText: "暂无可公开活动" }),
      mobileSection("relationships", "关系分", "ranked-list", collaboratorItems, { emptyText: "暂无公开关系" }),
      mobileSection("organizations", "主办 / 厂牌", "ranked-list", organizationItems, { emptyText: "暂无公开主办关系" }),
      mobileSection("venues", "常出现地点", "ranked-list", venueItems, { emptyText: "暂无公开地点" }),
      mobileSection("sound_system", "音响系统", "evidence-list", soundSystem.evidence, {
        emptyText: "暂无可公开音响证据",
        summary: soundSystem.summary,
        reportOnly: true,
      }),
      mobileSection("sources", "信息来源", "source-list", sourceItems, { emptyText: "暂无公开来源" }),
    ].filter((section) => section.items.length || section.id === "sound_system" || section.id === "aliases");

    return {
      schemaVersion: "stage7_atlas_api.graph_mobile_profile.v1",
      query: query || null,
      id: primaryId || null,
      found: true,
      header: {
        title,
        subtitle: uniqueTexts([canonical.primaryType, ...topCountsFromProfile(profile.taxonomy?.cities, 1), `${finiteNumber(profile.summary?.eventCount, 0)} 场活动`], 3).join(" · "),
        primaryType: canonical.primaryType || "entity",
        primaryId,
        nodeId: canonical.nodeId || "",
        stats: [
          { label: "活动", value: finiteNumber(profile.summary?.eventCount, 0) },
          { label: "关系", value: finiteNumber(profile.summary?.collaboratorCount, 0) },
          { label: "来源", value: finiteNumber(profile.summary?.sourceArticleCount, 0) },
        ],
      },
      quickActions: [
        { id: "open_graph", label: "关系漫游", action: "open_graph_seed", apiPath: graphSeedPath },
        { id: "search", label: "同名搜索", action: "search_entity", query: title, apiPath: mobileProfilePath },
        { id: "sources", label: "看来源", action: "scroll_section", sectionId: "sources" },
      ],
      entityMerge,
      sections,
      navigation: {
        graphSeedApi: graphSeedPath,
        profileApi: mobileProfilePath,
        expandApi: primaryId ? `/api/v1/stage7/graph/expand?id=${encodeURIComponent(primaryId)}&limit=48&lod=focus` : "",
      },
      payloadPolicy: mobilePayloadPolicy(),
      retrieval: {
        source: profile.retrieval?.mode || "",
        dbIdentity: profile.retrieval?.dbIdentity || this.publicDbIdentity(),
        entityMergeSidecarEnabled: this.getEntityMergeGroupIndex().size > 0,
        entityMergePlan: profile.retrieval?.entityMergePlan || null,
        soundSystemSidecarEnabled: this.getSoundSystemEvidenceIndex().size > 0,
      },
      safety: profile.safety || graphSafety(),
    };
  }

  async getAtlasFamilyProfile({ q, id, limit, eventLimit, collaboratorLimit, venueLimit, articleLimit } = {}) {
    const profile = await this.getGraphEntityProfile({
      q,
      id,
      limit: limit || 32,
      sourceLimit: 500,
      eventLimit: eventLimit || 8,
      collaboratorLimit: collaboratorLimit || 12,
      venueLimit: venueLimit || 8,
      articleLimit: articleLimit || 8,
      preferEntities: true,
    });
    return this.compactAtlasFamilyProfile(profile, { q, id });
  }

  compactAtlasFamilyProfile(profile, { q, id } = {}) {
    const canonical = profile?.canonical || {};
    const title = text(canonical.name || profile?.query || q || id || "");
    const primaryId = text(canonical.primaryId || profile?.id || id || "");
    const centerKind = atlasFamilyCenterKind(canonical.primaryType);
    const centerCopy = atlasFamilyExploreCopy(centerKind);
    if (!profile?.found) {
      return {
        schemaVersion: "atlas.family_profile.v1",
        query: text(q) || null,
        id: text(id) || null,
        found: false,
        canonical: null,
        trust: this.atlasFamilyTrust(profile),
        stats: { events: 0, relationships: 0, sources: 0, aliases: 0 },
        sections: this.emptyAtlasFamilySections(),
        navigation: {},
        safety: atlasFamilySafety(profile?.safety),
      };
    }

    const aliases = uniqueTexts(canonical.names || [title], 24).map((name) => ({
      name,
      state: profile.retrieval?.entityMergePlan ? "report_only" : "public_fact",
      tap: {
        action: "open_entity_profile",
        query: name,
        apiPath: `/api/v1/atlas/family/profile?q=${encodeURIComponent(name)}`,
      },
    }));
    const historyItems = (profile.history?.events || []).slice(0, 12).map(familyHistoryItem);
    const relationshipItems = (profile.relationships?.collaborators || []).slice(0, 16).map(familyRelationshipItem);
    const organizationItems = (profile.relationships?.organizations || []).slice(0, 12).map((row) => familyRankedItem(row));
    const venueItems = (profile.history?.venues || []).slice(0, 12).map((row) => familyRankedItem(row));
    const soundEvidence = (profile.attributes?.soundSystemEvidence || []).slice(0, 8).map((row) => ({
      venueId: text(row.venueId || row.venue_id || ""),
      venueName: textPreview(row.venueName || row.venue_name || "", 100),
      city: textPreview(row.city || "", 40),
      terms: uniqueTexts(row.terms || [], 10),
      confidence: finiteNumber(row.confidence, 0),
      evidenceCount: finiteNumber(row.evidenceCount ?? row.evidence_count, 0),
      state: row.reportOnly === false ? "review_ready" : "report_only",
      reportOnly: row.reportOnly !== false,
      evidence: (row.evidence || []).slice(0, 5).map((item) => ({
        sourceRefId: text(item.sourceRefId || item.source_ref_id || ""),
        sourceAccount: textPreview(item.sourceAccount || item.source_account || "", 80),
        sourceTitle: textPreview(item.sourceTitle || item.source_title || "", 120),
        postDate: textPreview(item.postDate || item.post_date || "", 40),
        publicSnippet: textPreview(item.publicSnippet || item.public_snippet || "", 160),
        tap: {
          action: "open_source_evidence",
          sourceRefId: text(item.sourceRefId || item.source_ref_id || ""),
        },
      })),
    }));
    const sourceItems = (profile.sources?.articles || []).slice(0, 12).map(familySourceItem);
    const exploreRings = atlasFamilyExploreRings(centerKind, {
      relatedDjs: relationshipItems,
      clubs: venueItems,
      events: historyItems,
      organizations: organizationItems,
      soundSystem: soundEvidence,
      sources: sourceItems,
    });

    return {
      schemaVersion: "atlas.family_profile.v1",
      query: text(profile.query || q) || null,
      id: text(id) || primaryId || null,
      found: true,
      center: {
        kind: centerKind,
        title: centerCopy.title,
        guidance: centerCopy.guidance,
        primaryAction: "radiate_from_center",
      },
      canonical: {
        name: title,
        type: text(canonical.primaryType || "entity"),
        primaryType: text(canonical.primaryType || "entity"),
        primaryId,
        nodeId: text(canonical.nodeId || ""),
        city: topCountsFromProfile(profile.taxonomy?.cities, 1)[0] || "",
        taxonomy: profile.taxonomy || { types: [], cities: [] },
        publicState: "public_fact",
      },
      trust: this.atlasFamilyTrust(profile),
      stats: {
        events: finiteNumber(profile.summary?.eventCount, historyItems.length),
        relationships: finiteNumber(profile.summary?.collaboratorCount, relationshipItems.length),
        sources: finiteNumber(profile.summary?.sourceArticleCount, sourceItems.length),
        aliases: aliases.length,
        organizations: finiteNumber(profile.summary?.organizationCount, organizationItems.length),
        venues: venueItems.length,
      },
      sections: {
        explore: {
          title: centerCopy.title,
          state: "public_fact",
          layout: "radial-orbit",
          guidance: centerCopy.guidance,
          center: {
            id: primaryId,
            label: title,
            type: text(canonical.primaryType || "entity"),
            kind: centerKind,
            city: topCountsFromProfile(profile.taxonomy?.cities, 1)[0] || "",
          },
          rings: exploreRings,
        },
        relatedDjs: {
          title: centerCopy.relatedDjsTitle,
          state: "public_fact",
          layout: "ranked-list",
          items: relationshipItems,
        },
        clubs: {
          title: centerCopy.clubsTitle,
          state: "public_fact",
          layout: "ranked-list",
          items: venueItems,
        },
        events: {
          title: centerCopy.eventsTitle,
          state: "public_fact",
          layout: "timeline",
          items: historyItems,
        },
        aliases: {
          title: "同一实体 / 别名",
          state: profile.retrieval?.entityMergePlan ? "report_only" : "public_fact",
          items: aliases,
        },
        history: {
          title: "历史活动",
          state: "public_fact",
          layout: "timeline",
          items: historyItems,
        },
        relationships: {
          title: "关系分",
          state: "public_fact",
          layout: "ranked-list",
          items: relationshipItems,
        },
        organizations: {
          title: "主办 / 厂牌",
          state: "public_fact",
          layout: "ranked-list",
          items: organizationItems,
        },
        venues: {
          title: "常出现地点",
          state: "public_fact",
          layout: "ranked-list",
          items: venueItems,
        },
        soundSystem: {
          title: "音响系统",
          state: soundEvidence.length ? "report_only" : "blocked",
          layout: "evidence-list",
          summary: profile.attributes?.soundSystemSummary || null,
          items: soundEvidence,
          reportOnly: true,
        },
        sources: {
          title: "信息来源",
          state: "public_fact",
          layout: "source-list",
          items: sourceItems,
        },
        candidates: {
          title: "候选层",
          state: "candidate",
          layout: "status-list",
          items: [
            { id: "social", label: "外链候选", state: "candidate", publicFact: false },
            { id: "avatar", label: "头像候选", state: "blocked", publicFact: false },
            { id: "merge", label: "同一实体候选", state: "report_only", publicFact: false, reportOnly: true },
            { id: "sound_system", label: "音响系统证据", state: soundEvidence.length ? "report_only" : "blocked", publicFact: false, reportOnly: true },
          ],
        },
      },
      navigation: {
        graphSeedApi: title ? `/api/v1/stage7/graph/seed?q=${encodeURIComponent(title)}&limit=48&lod=focus` : "",
        profileApi: title ? `/api/v1/atlas/family/profile?q=${encodeURIComponent(title)}` : "",
        relationshipsApi: primaryId ? `/api/v1/atlas/family/relationships?id=${encodeURIComponent(primaryId)}&limit=50` : "",
      },
      retrieval: {
        mode: profile.retrieval?.mode || "",
        entityMergePlan: profile.retrieval?.entityMergePlan || null,
        dbIdentity: profile.retrieval?.dbIdentity || this.publicDbIdentity(),
      },
      safety: atlasFamilySafety(profile.safety),
    };
  }

  atlasFamilyTrust(profile = {}) {
    const soundAvailable = Boolean(profile.attributes?.soundSystemSummary?.available || (profile.attributes?.soundSystemEvidence || []).length);
    return {
      facts: "public_fact",
      merge: "report_only",
      social: "candidate",
      avatar: "blocked",
      soundSystem: soundAvailable ? "report_only" : "blocked",
    };
  }

  emptyAtlasFamilySections() {
    return {
      explore: { title: "中心辐射", state: "blocked", layout: "radial-orbit", rings: [] },
      relatedDjs: { title: "关系分高的 DJ", state: "blocked", items: [] },
      clubs: { title: "常去俱乐部", state: "blocked", items: [] },
      events: { title: "历史活动", state: "blocked", items: [] },
      aliases: { title: "同一实体 / 别名", state: "blocked", items: [] },
      history: { title: "历史活动", state: "blocked", items: [] },
      relationships: { title: "关系分", state: "blocked", items: [] },
      organizations: { title: "主办 / 厂牌", state: "blocked", items: [] },
      venues: { title: "常出现地点", state: "blocked", items: [] },
      soundSystem: { title: "音响系统", state: "blocked", items: [], reportOnly: true },
      sources: { title: "信息来源", state: "blocked", items: [] },
      candidates: { title: "候选层", state: "candidate", items: [] },
    };
  }

  async getAtlasFamilyRelationships({ q, id, limit } = {}) {
    const pageLimit = normalizeLimit(limit, 20, 80);
    let profile = await this.getAtlasFamilyProfile({ q, id, collaboratorLimit: pageLimit, eventLimit: 6, articleLimit: 6 });
    if (!profile.found && id && !q) {
      const fallbackQuery = text(id).split(":").pop();
      if (fallbackQuery && fallbackQuery !== id) {
        profile = await this.getAtlasFamilyProfile({ q: fallbackQuery, collaboratorLimit: pageLimit, eventLimit: 6, articleLimit: 6 });
      }
    }
    const relationships = (profile.sections?.relationships?.items || []).slice(0, pageLimit);
    return {
      schemaVersion: "atlas.family_relationships.v1",
      query: text(q) || null,
      target: profile.found
        ? {
            id: profile.canonical?.primaryId || text(id) || "",
            label: profile.canonical?.name || text(q) || text(id) || "",
            type: profile.canonical?.primaryType || "entity",
            state: "public_fact",
          }
        : null,
      relationships,
      safety: atlasFamilySafety(profile.safety),
    };
  }

  async getAtlasEvidence(sourceRefId) {
    const id = text(sourceRefId);
    if (!id) return null;
    const db = await this.db();
    let row = null;
    let supportFields = [];
    if (sqliteTableExists(db, "evidence_ref")) {
      row = db.prepare(`
        SELECT source_ref_id, source_hash, source_account, source_title, post_date, public_snippet, source_kind, public_url_allowed
        FROM evidence_ref
        WHERE source_ref_id = ?
        LIMIT 1
      `).get(id);
    }
    if (sqliteTableExists(db, "activity_evidence_ref")) {
      supportFields = db.prepare(`
        SELECT field_path, field_value, support_type, quote, quote_policy, confidence
        FROM activity_evidence_ref
        WHERE source_ref_id = ? OR evidence_ref_id = ?
        ORDER BY confidence DESC, field_path
        LIMIT 20
      `).all(id, id).map((item) => ({
        fieldPath: text(item.field_path || ""),
        fieldValue: textPreview(item.field_value || "", 160),
        supportType: text(item.support_type || ""),
        quote: textPreview(item.quote || "", 180),
        quotePolicy: text(item.quote_policy || ""),
        confidence: item.confidence ?? null,
      }));
    }
    if (!row && sqliteTableExists(db, "articles")) {
      const article = db.prepare(`
        SELECT article_uid, article_id, title, source_account, publish_time, publish_time_status, vector_text_preview, quality_grade
        FROM articles
        WHERE article_uid = ? OR article_id = ?
        LIMIT 1
      `).get(id, id);
      if (article) {
        row = {
          source_ref_id: article.article_uid || article.article_id,
          source_hash: "",
          source_account: article.source_account || "",
          source_title: article.title || "",
          post_date: article.publish_time || article.publish_time_status || "",
          public_snippet: article.vector_text_preview || article.title || "",
          source_kind: "article",
          public_url_allowed: 0,
          quality_grade: article.quality_grade || "",
        };
      }
    }
    if (!row) return null;
    return {
      schemaVersion: "atlas.evidence.v1",
      sourceRefId: text(row.source_ref_id || id),
      sourceAccount: textPreview(row.source_account || "", 80),
      sourceTitle: textPreview(row.source_title || "", 160),
      postDate: textPreview(row.post_date || "", 40),
      publicSnippet: textPreview(row.public_snippet || "", 240),
      sourceKind: text(row.source_kind || ""),
      publicUrl: publicEvidenceUrlPolicy(row),
      supportFields,
      safety: atlasFamilySafety({
        sourceHashExposed: false,
      }),
    };
  }

  profileSeedEntityRows(db, { q, id, limit }) {
    const selectedId = text(id);
    if (selectedId) {
      const row = this.findRow(db, "entities", selectedId);
      return this.isPublicRowVisible(db, row, "entities") ? [row] : [];
    }
    const query = text(q);
    if (!query) return [];
    const exactRows = this.exactGraphEntityRows(db, query, limit);
    if (exactRows.length) return exactRows;
    return sortedSearchRows(this.publicRows(db, this.searchKindRows(db, "entities", ftsQuery(query), limit * 4), "entities", limit * 2), "entities", query).slice(0, limit);
  }

  buildProfileTerms(db, { q, seedRows }) {
    const query = text(q || seedRows[0]?.name || "");
    const names = [];
    const sourceAccounts = [];
    const places = [];
    for (const row of seedRows) {
      names.push(row.name);
      for (const alias of maybeJson(row.aliases_json, [])) names.push(alias);
    }
    const expandedByAliases = Boolean(query && canExpandProfileAliases(seedRows));
    if (expandedByAliases) {
      const like = `%${query}%`;
      const entityAliases = db
        .prepare(
          "SELECT name, type, COUNT(*) AS count FROM entities WHERE LOWER(name) LIKE LOWER(?) GROUP BY name, type ORDER BY count DESC LIMIT 400",
        )
        .all(like);
      for (const row of entityAliases) {
        if (!PROFILE_ALIAS_ENTITY_TYPES.has(text(row.type).toLowerCase())) continue;
        if (profileAliasMatches(query, row.name)) names.push(row.name);
      }
      const accountAliases = db
        .prepare(
          "SELECT source_account AS name, COUNT(*) AS count FROM articles WHERE LOWER(source_account) LIKE LOWER(?) GROUP BY source_account ORDER BY count DESC LIMIT 200",
        )
        .all(like);
      for (const row of accountAliases) {
        if (!profileAliasMatches(query, row.name)) continue;
        sourceAccounts.push(row.name);
        names.push(row.name);
      }
      const placeAliases = db
        .prepare(
          "SELECT place AS name, COUNT(*) AS count FROM events WHERE place <> '' AND LOWER(place) LIKE LOWER(?) GROUP BY place ORDER BY count DESC LIMIT 500",
        )
        .all(like);
      for (const row of placeAliases) {
        if (!profileAliasMatches(query, row.name)) continue;
        places.push(row.name);
        names.push(row.name);
      }
    }
    return {
      names: uniqueTexts(names, 120),
      sourceAccounts: uniqueTexts(sourceAccounts, 80),
      places: uniqueTexts(places, 160),
      expandedByAliases,
    };
  }

  loadProfileEntityRows(db, profileTerms, limit) {
    const selectedNames = uniqueTexts(profileTerms.names || [], 120);
    if (!selectedNames.length && !profileTerms.sourceAccounts?.length && !profileTerms.places?.length) {
      return { totalRows: 0, totalSourceArticles: 0, totalEvents: 0, rows: [], sourceArticleUids: [], allSourceArticleUids: [] };
    }
    let totalRows = 0;
    const rows = [];
    const sourceArticleUidSet = new Set();
    const entitySourceArticleUidSet = new Set();
    const accountSourceArticleUidSet = new Set();
    const placeSourceArticleUidSet = new Set();
    for (const chunk of chunkValues(selectedNames)) {
      const placeholders = chunk.map(() => "?").join(",");
      totalRows += Number(db.prepare(`SELECT COUNT(*) AS count FROM entities WHERE name IN (${placeholders})`).get(...chunk)?.count || 0);
      this.addProfileSourceArticleUids(db, sourceArticleUidSet, "entities", "source_article_uid", "name", chunk, entitySourceArticleUidSet);
      if (rows.length < limit) {
        const remaining = limit - rows.length;
        rows.push(...db.prepare(`SELECT * FROM entities WHERE name IN (${placeholders}) ORDER BY confidence DESC, row_pk LIMIT ?`).all(...chunk, remaining));
      }
    }
    for (const chunk of chunkValues(profileTerms.sourceAccounts || [])) {
      this.addProfileSourceArticleUids(db, sourceArticleUidSet, "articles", "article_uid", "source_account", chunk, accountSourceArticleUidSet);
    }
    for (const chunk of chunkValues(profileTerms.places || [])) {
      this.addProfileSourceArticleUids(db, sourceArticleUidSet, "events", "source_article_uid", "place", chunk, placeSourceArticleUidSet);
    }
    const allSourceArticleUids = Array.from(sourceArticleUidSet);
    const eventSourceArticleUids = uniqueTexts([...accountSourceArticleUidSet, ...placeSourceArticleUidSet]);
    const totalEvents = eventSourceArticleUids.length
      ? this.countProfileEventRows(db, profileTerms, Array.from(accountSourceArticleUidSet))
      : this.countRowsBySourceArticleUids(db, "events", allSourceArticleUids);
    return {
      totalRows,
      totalSourceArticles: allSourceArticleUids.length,
      totalEvents,
      rows,
      sourceArticleUids: allSourceArticleUids.slice(0, limit),
      allSourceArticleUids,
      entitySourceArticleUids: Array.from(entitySourceArticleUidSet),
      accountSourceArticleUids: Array.from(accountSourceArticleUidSet),
      placeSourceArticleUids: Array.from(placeSourceArticleUidSet),
      eventSourceArticleUids,
    };
  }

  addProfileSourceArticleUids(db, targetSet, table, sourceColumn, matchColumn, values, extraTargetSet = null) {
    if (!values.length) return;
    const placeholders = values.map(() => "?").join(",");
    const rows = db.prepare(`SELECT DISTINCT ${sourceColumn} AS source_uid FROM ${table} WHERE ${matchColumn} IN (${placeholders})`).all(...values);
    for (const row of rows) {
      const uid = text(row.source_uid);
      if (!uid) continue;
      targetSet.add(uid);
      if (extraTargetSet) extraTargetSet.add(uid);
    }
  }

  countRowsBySourceArticleUids(db, kind, sourceArticleUids) {
    const table = KIND_TABLE[kind];
    if (!table || !sourceArticleUids.length) return 0;
    let count = 0;
    for (const chunk of chunkValues(sourceArticleUids)) {
      const placeholders = chunk.map(() => "?").join(",");
      count += Number(db.prepare(`SELECT COUNT(*) AS count FROM ${table} WHERE source_article_uid IN (${placeholders})`).get(...chunk)?.count || 0);
    }
    return count;
  }

  countProfileEventRows(db, profileTerms, accountSourceArticleUids) {
    const rowPks = new Set();
    for (const chunk of chunkValues(accountSourceArticleUids || [])) {
      const placeholders = chunk.map(() => "?").join(",");
      const rows = db.prepare(`SELECT row_pk FROM events WHERE source_article_uid IN (${placeholders})`).all(...chunk);
      for (const row of rows) rowPks.add(row.row_pk);
    }
    for (const chunk of chunkValues(profileTerms.places || [])) {
      const placeholders = chunk.map(() => "?").join(",");
      const rows = db.prepare(`SELECT row_pk FROM events WHERE place IN (${placeholders})`).all(...chunk);
      for (const row of rows) rowPks.add(row.row_pk);
    }
    return rowPks.size;
  }

  loadProfileEventRows(db, profileTerms, accountSourceArticleUids, maxRows) {
    if (maxRows <= 0) return [];
    const rowsByPk = new Map();
    const addRows = (rows) => {
      for (const row of rows) {
        if (!rowsByPk.has(row.row_pk)) rowsByPk.set(row.row_pk, row);
      }
    };
    for (const chunk of chunkValues(accountSourceArticleUids || [])) {
      if (rowsByPk.size >= maxRows) break;
      const placeholders = chunk.map(() => "?").join(",");
      addRows(db.prepare(`SELECT * FROM events WHERE source_article_uid IN (${placeholders}) ORDER BY confidence DESC, row_pk LIMIT ?`).all(...chunk, maxRows));
    }
    for (const chunk of chunkValues(profileTerms.places || [])) {
      if (rowsByPk.size >= maxRows) break;
      const placeholders = chunk.map(() => "?").join(",");
      addRows(db.prepare(`SELECT * FROM events WHERE place IN (${placeholders}) ORDER BY confidence DESC, row_pk LIMIT ?`).all(...chunk, maxRows));
    }
    return Array.from(rowsByPk.values())
      .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0) || Number(b.row_pk || 0) - Number(a.row_pk || 0))
      .slice(0, maxRows);
  }

  loadRowsBySourceArticleUid(db, kind, sourceArticleUids, maxRows) {
    const table = KIND_TABLE[kind];
    if (!table || !sourceArticleUids.length || maxRows <= 0) return [];
    const rows = [];
    for (const chunk of chunkValues(sourceArticleUids)) {
      const remaining = maxRows - rows.length;
      if (remaining <= 0) break;
      const placeholders = chunk.map(() => "?").join(",");
      rows.push(...db.prepare(`SELECT * FROM ${table} WHERE source_article_uid IN (${placeholders}) ORDER BY confidence DESC, row_pk LIMIT ?`).all(...chunk, remaining));
    }
    return rows;
  }

  loadRowsByArticleUid(db, articleUids, maxRows) {
    if (!articleUids.length || maxRows <= 0) return [];
    const rows = [];
    for (const chunk of chunkValues(articleUids)) {
      const remaining = maxRows - rows.length;
      if (remaining <= 0) break;
      const placeholders = chunk.map(() => "?").join(",");
      rows.push(...db.prepare(`SELECT * FROM articles WHERE article_uid IN (${placeholders}) ORDER BY row_pk LIMIT ?`).all(...chunk, remaining));
    }
    return rows;
  }

  loadIdentityProfileRows(db, names, limit) {
    const selectedNames = uniqueTexts(names, 12);
    if (!selectedNames.length || limit <= 0) return [];
    if (!sqliteTableExists(db, "identity_review_items")) return [];
    const placeholders = selectedNames.map(() => "?").join(",");
    return db
      .prepare(`SELECT * FROM identity_review_items WHERE subject_name IN (${placeholders}) ORDER BY support_count DESC, identity_signal_score DESC, row_pk LIMIT ?`)
      .all(...selectedNames, limit);
  }

  async getGraphSubgraph({ nodeId, kind, id, depth, limit, lod } = {}) {
    const db = await this.db();
    if (this.isServingReadModel(db)) return this.getServingGraphSubgraph(db, { nodeId, kind, id, depth, limit, lod });
    const pageLimit = normalizeLimit(limit, 120, 300);
    const depthLimit = normalizeLimit(depth, 1, 3);
    const acc = this.createGraphAccumulator({ nodeLimit: pageLimit });
    const ref = this.resolveGraphRef(db, { nodeId, kind, id });
    const perKindLimit = Math.max(10, Math.min(48, Math.ceil(pageLimit / 4)));

    if (!ref?.row) {
      return this.graphResponse(acc, {
        mode: "subgraph",
        requestedLimit: pageLimit,
        depth: depthLimit,
        notFound: true,
        lod,
      });
    }

    const start = this.addGraphSourceForRow(db, acc, ref.kind, ref.row, { seed: true, perKindLimit }).node;
    let frontier = [ref];
    for (let level = 2; level <= depthLimit; level += 1) {
      const next = [];
      for (const item of frontier.slice(0, perKindLimit)) {
        next.push(...this.addSimilarGraphRows(db, acc, item.kind, item.row, Math.max(4, Math.ceil(perKindLimit / 2))));
      }
      if (next.length === 0) break;
      frontier = next;
    }

    return this.graphResponse(acc, {
      mode: "subgraph",
      seed: start ? { nodeId: start.id, kind: ref.kind, primaryId: ref.id, label: start.label } : null,
      requestedLimit: pageLimit,
      depth: depthLimit,
      lod,
    });
  }

  async getGraphRandomWalk({ nodeId, kind, id, steps, fanout, limit, lod } = {}) {
    const db = await this.db();
    if (this.isServingReadModel(db)) return this.getServingGraphSubgraph(db, { nodeId, kind, id, depth: steps || 2, limit, lod });
    const pageLimit = normalizeLimit(limit, 140, 300);
    const stepLimit = normalizeLimit(steps, 3, 6);
    const fanoutLimit = normalizeLimit(fanout, 8, 40);
    const acc = this.createGraphAccumulator({ nodeLimit: pageLimit });
    const ref = this.resolveGraphRef(db, { nodeId, kind, id }) || this.defaultGraphStart(db);
    const perKindLimit = Math.max(8, Math.min(36, Math.ceil(pageLimit / 5)));

    if (ref?.row) {
      this.addGraphSourceForRow(db, acc, ref.kind, ref.row, { seed: true, perKindLimit });
    }

    let frontier = ref?.row ? [ref] : [];
    for (let step = 0; step < stepLimit; step += 1) {
      const next = this.graphWalkRows(db, frontier[0], Math.max(2, Math.ceil(fanoutLimit / 2)));
      for (const item of next) {
        this.addGraphSourceForRow(db, acc, item.kind, item.row, { perKindLimit: Math.max(4, Math.ceil(perKindLimit / 2)) });
      }
      if (next.length === 0) break;
      frontier = next;
    }

    if (acc.output().returnedNodes < 4) {
      for (const item of this.graphSeedRows(db, ["entities", "events", "articles"], "", Math.min(pageLimit, 24))) {
        this.addGraphSourceForRow(db, acc, item.kind, item.row, { perKindLimit: Math.max(4, Math.ceil(perKindLimit / 2)) });
      }
    }

    return this.graphResponse(acc, {
      mode: "random_walk",
      seed: ref?.row ? { nodeId: graphNodeId(ref.kind, ref.row), kind: ref.kind, primaryId: primaryDetailId(ref.row, ref.kind) } : null,
      requestedLimit: pageLimit,
      steps: stepLimit,
      fanout: fanoutLimit,
      lod,
    });
  }

  graphSeedRows(db, kinds, q, pageLimit) {
    const query = ftsQuery(q);
    const queryText = text(q);
    const perKind = Math.max(4, Math.ceil(pageLimit / Math.max(1, kinds.length)));
    const rows = [];
    for (const kind of kinds) {
      const selectedRows = query
        ? sortedSearchRows(this.publicRows(db, this.searchKindRows(db, kind, query, perKind * 8), kind, perKind * 3), kind, queryText).slice(0, perKind)
        : this.defaultGraphRows(db, kind, perKind);
      rows.push(...selectedRows.map((row) => ({ kind, row })));
    }
    return query
      ? rows.sort((a, b) => searchRank(a.row, a.kind, queryText) - searchRank(b.row, b.kind, queryText)).slice(0, pageLimit)
      : rows.slice(0, pageLimit);
  }

  defaultGraphRows(db, kind, limit) {
    if (kind === "articles") {
      return this.publicRows(db, db.prepare("SELECT * FROM articles ORDER BY row_pk LIMIT ?").all(limit * 4), kind, limit);
    }
    if (kind === "events") {
      return this.publicRows(db, db.prepare("SELECT * FROM events ORDER BY row_pk LIMIT ?").all(limit * 4), kind, limit);
    }
    return this.publicRows(db, db.prepare("SELECT * FROM entities ORDER BY row_pk LIMIT ?").all(limit * 4), kind, limit);
  }

  exactGraphEntityRows(db, q, limit) {
    const query = text(q);
    if (!query) return [];
    const normalizedQuery = normalizeSearchText(query);
    const ftsRows = this.publicRows(
      db,
      this.searchKindRows(db, "entities", ftsQuery(query), Math.max(limit * 16, 96)),
      "entities",
      Math.max(limit * 4, 48),
    );
    return sortedSearchRows(ftsRows, "entities", query)
      .filter((row) => normalizeSearchText(rowTitle(row)) === normalizedQuery)
      .slice(0, limit);
  }

  resolveGraphRef(db, { nodeId, kind, id } = {}) {
    const parsed = parseGraphNodeId(nodeId);
    const selectedKind = parsed?.kind || normalizeGraphKind(kind);
    const selectedId = text(parsed?.id || id);
    if (!selectedKind || !selectedId) return null;
    const row = this.findRow(db, selectedKind, selectedId);
    return this.isPublicRowVisible(db, row, selectedKind) ? { kind: selectedKind, id: selectedId, row } : null;
  }

  defaultGraphStart(db) {
    const entity = this.publicRows(db, db.prepare("SELECT * FROM entities ORDER BY row_pk LIMIT 20").all(), "entities", 1)[0];
    if (entity) return { kind: "entities", id: primaryDetailId(entity, "entities"), row: entity };
    const event = this.publicRows(db, db.prepare("SELECT * FROM events ORDER BY row_pk LIMIT 20").all(), "events", 1)[0];
    if (event) return { kind: "events", id: primaryDetailId(event, "events"), row: event };
    const article = this.publicRows(db, db.prepare("SELECT * FROM articles ORDER BY row_pk LIMIT 20").all(), "articles", 1)[0];
    return article ? { kind: "articles", id: primaryDetailId(article, "articles"), row: article } : null;
  }

  addGraphSourceForRow(db, acc, kind, row, options = {}) {
    const node = acc.addNode(row, kind, options);
    const sourceArticleUid = text(row.source_article_uid || row.article_uid);
    const neighborhood = sourceArticleUid ? this.addGraphArticleNeighborhood(db, acc, sourceArticleUid, options) : { rows: [] };
    if (node && neighborhood.articleNode && kind !== "articles") {
      acc.addEdge(
        neighborhood.articleNode,
        node,
        kind === "entities" ? "mentions_entity" : "mentions_event",
        kind === "entities" ? "MENTIONED_IN" : "HAS_EVENT",
        2,
      );
    }
    return { node, ...neighborhood };
  }

  addGraphArticleNeighborhood(db, acc, sourceArticleUid, options = {}) {
    const perKindLimit = normalizeLimit(options.perKindLimit, 18, 80);
    const article = this.findRow(db, "articles", sourceArticleUid);
    if (article && isPublicAtlasNoise(article, "articles")) {
      return { articleNode: null, entityNodes: [], eventNodes: [], rows: [] };
    }
    const articleNode = article ? acc.addNode(article, "articles", options) : null;
    const entities = this.publicRows(
      db,
      db.prepare("SELECT * FROM entities WHERE source_article_uid = ? ORDER BY confidence DESC, row_pk LIMIT ?").all(sourceArticleUid, perKindLimit * 4),
      "entities",
      perKindLimit,
    );
    const events = this.publicRows(
      db,
      db.prepare("SELECT * FROM events WHERE source_article_uid = ? ORDER BY confidence DESC, row_pk LIMIT ?").all(sourceArticleUid, perKindLimit * 4),
      "events",
      perKindLimit,
    );
    const entityNodes = [];
    const eventNodes = [];
    const rows = [];

    for (const row of entities) {
      const node = acc.addNode(row, "entities");
      if (!node) continue;
      entityNodes.push(node);
      rows.push({ kind: "entities", row });
      if (articleNode) acc.addEdge(articleNode, node, "mentions_entity", "MENTIONED_IN", 2);
    }

    for (const row of events) {
      const node = acc.addNode(row, "events");
      if (!node) continue;
      eventNodes.push(node);
      rows.push({ kind: "events", row });
      if (articleNode) acc.addEdge(articleNode, node, "mentions_event", "HAS_EVENT", 2);
    }

    for (const entityNode of entityNodes.slice(0, 10)) {
      for (const eventNode of eventNodes.slice(0, 10)) {
        acc.addEdge(entityNode, eventNode, "same_article", "SAME_ARTICLE", 1);
      }
    }

    return { articleNode, entityNodes, eventNodes, rows };
  }

  addSimilarGraphRows(db, acc, kind, row, fanout) {
    const limit = normalizeLimit(fanout, 8, 40);
    const sourceArticleUid = text(row.source_article_uid || row.article_uid);
    let rows = [];
    if (kind === "entities" && text(row.name)) {
      rows = db
        .prepare("SELECT * FROM entities WHERE LOWER(name) = LOWER(?) AND source_article_uid <> ? ORDER BY confidence DESC, row_pk LIMIT ?")
        .all(text(row.name), sourceArticleUid, limit * 4);
    } else if (kind === "events") {
      rows = db
        .prepare(
          "SELECT * FROM events WHERE ((place <> '' AND LOWER(place) = LOWER(?)) OR (city <> '' AND LOWER(city) = LOWER(?))) AND source_article_uid <> ? ORDER BY confidence DESC, row_pk LIMIT ?",
        )
        .all(text(row.place), text(row.city), sourceArticleUid, limit * 4);
    } else if (kind === "articles" && text(row.source_account)) {
      rows = db
        .prepare("SELECT * FROM articles WHERE source_account <> '' AND LOWER(source_account) = LOWER(?) AND article_uid <> ? ORDER BY row_pk LIMIT ?")
        .all(text(row.source_account), text(row.article_uid), limit * 4);
    }

    const refs = [];
    for (const candidate of this.publicRows(db, rows, kind, limit)) {
      this.addGraphSourceForRow(db, acc, kind, candidate, { perKindLimit: Math.max(4, Math.ceil(limit / 2)) });
      refs.push({ kind, id: primaryDetailId(candidate, kind), row: candidate });
    }
    return refs;
  }

  graphWalkRows(db, ref, limit) {
    const pageLimit = normalizeLimit(limit, 4, 24);
    const baseRowPk = Number(ref?.row?.row_pk || 0);
    const rows = this.publicRows(db, db.prepare("SELECT * FROM articles WHERE row_pk > ? ORDER BY row_pk LIMIT ?").all(baseRowPk, pageLimit * 4), "articles", pageLimit);
    if (rows.length < pageLimit) {
      const seen = new Set(rows.map((row) => row.row_pk));
      const refill = this.publicRows(db, db.prepare("SELECT * FROM articles ORDER BY row_pk LIMIT ?").all((pageLimit - rows.length) * 4), "articles", pageLimit - rows.length);
      rows.push(...refill.filter((row) => !seen.has(row.row_pk)));
    }
    return rows.map((row) => ({ kind: "articles", id: primaryDetailId(row, "articles"), row }));
  }

  graphResponse(acc, meta = {}) {
    const output = acc.output();
    const response = {
      schemaVersion: "stage7_atlas_api.graph_response.v1",
      generatedAt: new Date().toISOString(),
      mode: meta.mode || "seed",
      query: meta.query || null,
      kind: meta.kind || null,
      seed: meta.seed || null,
      depth: meta.depth || null,
      steps: meta.steps || null,
      fanout: meta.fanout || null,
      notFound: Boolean(meta.notFound),
      nodes: output.nodes,
      edges: output.edges,
      limits: {
        requested: meta.requestedLimit || output.returnedNodes,
        nodeLimit: meta.requestedLimit || output.returnedNodes,
        edgeLimit: GRAPH_EDGE_LIMIT,
        returnedNodes: output.returnedNodes,
        returnedEdges: output.returnedEdges,
      },
      retrieval: {
        mode: "sqlite_readonly_graph_neighborhood",
        exactEntitySeeded: Boolean(meta.exactEntitySeeded),
        liveVectorSearchEnabled: false,
        dbPath: this.exposeInternalDbPath ? this.dbPath : "",
        dbIdentity: this.publicDbIdentity(),
      },
      safety: graphSafety(),
    };
    return finalizeGraphViewportResponse(response, {
      lens: meta.lens || "legacy_stage7_graph",
      lod: meta.lod || "focus",
      sourceNodeCount: output.returnedNodes,
      sourceEdgeCount: output.returnedEdges,
    });
  }

  findRow(db, kind, id) {
    const table = KIND_TABLE[kind];
    const target = text(id);
    const scoped = decodeScopedPublicId(target);
    if (scoped && (kind === "entities" || kind === "events")) {
      const field = kind === "entities" ? "eid" : "evid";
      const row = db
        .prepare(`SELECT * FROM ${table} WHERE source_article_uid = ? AND ${field} = ? LIMIT 1`)
        .get(scoped.sourceArticleUid, scoped.localId);
      if (row) return row;
    }
    for (const field of ID_FIELDS[kind] || []) {
      const matches = db.prepare(`SELECT * FROM ${table} WHERE ${field} = ? ORDER BY row_pk LIMIT 20`).all(target);
      const row = matches.find((candidate) => this.isPublicRowVisible(db, candidate, kind)) || matches[0];
      if (row) return row;
    }
    return null;
  }

  matchedBy(row, kind, id) {
    const target = text(id);
    const scoped = decodeScopedPublicId(target);
    if (scoped && (kind === "entities" || kind === "events")) {
      const field = kind === "entities" ? "eid" : "evid";
      if (text(row.source_article_uid) === scoped.sourceArticleUid && text(row[field]) === scoped.localId) return `source_article_uid+${field}`;
    }
    for (const field of ID_FIELDS[kind] || []) {
      if (text(row[field]) === target) return field;
    }
    return "";
  }

  async getIdentityReview({ limit, queue, bucket, domain } = {}) {
    const db = await this.db();
    const pageLimit = normalizeLimit(limit, 50, 200);
    if (!sqliteTableExists(db, "identity_review_items")) {
      return {
        schemaVersion: "stage7_atlas_api.identity_review_response.v1",
        generatedAt: new Date().toISOString(),
        decision: "identity_review_unavailable_for_serving_read_model",
        summary: {
          itemCount: 0,
          acceptedForGraph: 0,
          identityProofCount: 0,
          graphWriteAllowedCount: 0,
          needsReviewCount: 0,
        },
        sourceReports: [],
        facets: { queues: [], buckets: [], domains: [] },
        filters: { queue: text(queue) || null, bucket: text(bucket) || null, domain: text(domain) || null },
        page: { limit: pageLimit, total: 0, returned: 0 },
        items: [],
        safety: {
          modelCallExecuted: false,
          networkCallExecuted: false,
          graphWriteExecuted: false,
          sqliteWriteExecuted: false,
        },
      };
    }
    const where = [];
    const params = [];
    if (text(queue)) {
      where.push("i.queue = ?");
      params.push(text(queue));
    }
    if (text(bucket)) {
      where.push("i.bucket = ?");
      params.push(text(bucket));
    }
    if (text(domain)) {
      where.push("LOWER(i.domain) = LOWER(?)");
      params.push(text(domain));
    }
    const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const rows = db
      .prepare(
        `
        SELECT i.*, s.current_action, s.current_decision, s.reviewer, s.note, s.updated_at, s.action_count
        FROM identity_review_items i
        LEFT JOIN adjudication_item_state s ON s.item_id = i.item_id
        ${whereSql}
        ORDER BY i.row_pk
        LIMIT ?
      `,
      )
      .all(...params, pageLimit);
    const total = db.prepare(`SELECT COUNT(*) AS count FROM identity_review_items i ${whereSql}`).get(...params).count;
    const summary = {
      itemCount: db.prepare("SELECT COUNT(*) AS count FROM identity_review_items").get().count,
      acceptedForGraph: db.prepare("SELECT COUNT(*) AS count FROM identity_review_items WHERE accepted_for_graph = 1").get().count,
      identityProofCount: db.prepare("SELECT COUNT(*) AS count FROM identity_review_items WHERE identity_proof = 1").get().count,
      graphWriteAllowedCount: db.prepare("SELECT COUNT(*) AS count FROM identity_review_items WHERE graph_write_allowed = 1").get().count,
      needsReviewCount: db.prepare("SELECT COUNT(*) AS count FROM identity_review_items WHERE accepted_for_graph = 0").get().count,
    };
    return {
      schemaVersion: "stage7_atlas_api.identity_review_response.v1",
      generatedAt: new Date().toISOString(),
      decision: "identity_review_workbench_sqlite_persistent",
      summary,
      sourceReports: [],
      facets: {
        queues: createFacet(db.prepare("SELECT queue AS label, COUNT(*) AS count FROM identity_review_items GROUP BY queue ORDER BY count DESC").all()),
        buckets: createFacet(db.prepare("SELECT bucket AS label, COUNT(*) AS count FROM identity_review_items GROUP BY bucket ORDER BY count DESC").all()),
        domains: createFacet(db.prepare("SELECT domain AS label, COUNT(*) AS count FROM identity_review_items GROUP BY domain ORDER BY count DESC").all()),
      },
      filters: {
        queue: text(queue) || null,
        bucket: text(bucket) || null,
        domain: text(domain) || null,
      },
      page: {
        limit: pageLimit,
        total,
        returned: rows.length,
      },
      items: rows.map(mapIdentityRow),
      safety: {
        reportOnly: false,
        localPersistentLedger: true,
        networkCallExecuted: false,
        modelCallExecuted: false,
        graphWriteExecuted: false,
        qdrantWriteExecuted: false,
        sqliteWriteExecuted: false,
        mem0WriteExecuted: false,
        paidApiUsed: false,
        cookieOrTokenExported: false,
        dScanExecuted: false,
      },
    };
  }

  async recordAdjudicationAction(input = {}) {
    this.assertWritableLedger();
    const db = await this.db();
    const itemId = text(input.itemId || input.id);
    const action = text(input.action);
    if (!itemId) {
      const error = new Error("itemId is required");
      error.statusCode = 400;
      throw error;
    }
    if (!ALLOWED_ADJUDICATION_ACTIONS.has(action)) {
      const error = new Error("Unsupported adjudication action");
      error.statusCode = 400;
      throw error;
    }
    const item = db.prepare("SELECT * FROM identity_review_items WHERE item_id = ? LIMIT 1").get(itemId) || {};
    const now = new Date().toISOString();
    const actionId = `adj_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const payload = {
      ...input,
      itemId,
      action,
    };
    const row = {
      actionId,
      itemId,
      subjectName: text(input.subjectName || item.subject_name),
      subjectType: text(input.subjectType || item.subject_type),
      action,
      decision: text(input.decision),
      reviewer: text(input.reviewer) || "local",
      note: text(input.note),
      sourceUrl: text(input.sourceUrl || item.url),
      sourceArticleUid: text(input.sourceArticleUid || item.source_article_uid),
      createdAt: now,
      payloadJson: JSON.stringify(payload),
    };
    const tx = db.transaction(() => {
      db.prepare(
        `
        INSERT INTO adjudication_actions (
          action_id, item_id, subject_name, subject_type, action, decision,
          reviewer, note, source_url, source_article_uid, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      ).run(
        row.actionId,
        row.itemId,
        row.subjectName,
        row.subjectType,
        row.action,
        row.decision,
        row.reviewer,
        row.note,
        row.sourceUrl,
        row.sourceArticleUid,
        row.createdAt,
        row.payloadJson,
      );
      db.prepare(
        `
        INSERT INTO adjudication_item_state (
          item_id, subject_name, subject_type, current_action, current_decision,
          reviewer, note, source_url, source_article_uid, action_count,
          updated_at, last_action_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          subject_name=excluded.subject_name,
          subject_type=excluded.subject_type,
          current_action=excluded.current_action,
          current_decision=excluded.current_decision,
          reviewer=excluded.reviewer,
          note=excluded.note,
          source_url=excluded.source_url,
          source_article_uid=excluded.source_article_uid,
          action_count=adjudication_item_state.action_count + 1,
          updated_at=excluded.updated_at,
          last_action_id=excluded.last_action_id
      `,
      ).run(
        row.itemId,
        row.subjectName,
        row.subjectType,
        row.action,
        row.decision,
        row.reviewer,
        row.note,
        row.sourceUrl,
        row.sourceArticleUid,
        row.createdAt,
        row.actionId,
      );
    });
    tx();
    return {
      schemaVersion: "stage7_atlas_api.adjudication_action_result.v1",
      ok: true,
      action: row,
      safety: {
        sqliteWriteExecuted: true,
        sqliteDbPath: this.exposeInternalDbPath ? this.dbPath : "",
        graphWriteExecuted: false,
        qdrantWriteExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
        networkCallExecuted: false,
        llmCallExecuted: false,
      },
    };
  }

  async getAdjudicationLedger({ limit, itemId } = {}) {
    const db = await this.db();
    const pageLimit = normalizeLimit(limit, 50, 200);
    const where = text(itemId) ? "WHERE item_id = ?" : "";
    const params = text(itemId) ? [text(itemId)] : [];
    const actions = db
      .prepare(`SELECT * FROM adjudication_actions ${where} ORDER BY created_at DESC LIMIT ?`)
      .all(...params, pageLimit)
      .map((row) => ({
        actionId: row.action_id,
        itemId: row.item_id,
        subjectName: row.subject_name,
        subjectType: row.subject_type,
        action: row.action,
        decision: row.decision,
        reviewer: row.reviewer,
        note: row.note,
        sourceUrl: row.source_url,
        sourceArticleUid: row.source_article_uid,
        createdAt: row.created_at,
      }));
    return {
      schemaVersion: "stage7_atlas_api.adjudication_ledger.v1",
      page: { limit: pageLimit, returned: actions.length },
      actions,
      safety: { sqliteWriteExecuted: false, localPersistentLedger: true },
    };
  }

  async recordGeocodeReviewAction(input = {}) {
    this.assertWritableLedger();
    const db = await this.db();
    const reviewId = text(input.reviewId || input.itemId || input.id);
    const action = text(input.action);
    if (!reviewId) {
      const error = new Error("reviewId is required");
      error.statusCode = 400;
      throw error;
    }
    if (!ALLOWED_GEOCODE_REVIEW_ACTIONS.has(action)) {
      const error = new Error("Unsupported geocode review action");
      error.statusCode = 400;
      throw error;
    }
    const item = db.prepare("SELECT * FROM map_geocode_review_items WHERE review_id = ? LIMIT 1").get(reviewId);
    if (!item) {
      const error = new Error("Geocode review item was not found");
      error.statusCode = 404;
      throw error;
    }
    const now = new Date().toISOString();
    const actionId = `geo_adj_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const payload = {
      ...input,
      reviewId,
      action,
    };
    const row = {
      actionId,
      reviewId,
      placeId: item.place_id || "",
      label: item.label || "",
      reviewBucket: item.review_bucket || "",
      action,
      decision: text(input.decision) || action,
      reviewer: text(input.reviewer) || "local",
      note: text(input.note),
      sampleArticleUid: text(input.sampleArticleUid || item.sample_article_uid),
      createdAt: now,
      payloadJson: JSON.stringify(payload),
    };
    const tx = db.transaction(() => {
      db.prepare(
        `
        INSERT INTO geocode_review_actions (
          action_id, review_id, place_id, label, review_bucket, action,
          decision, reviewer, note, sample_article_uid, created_at, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      ).run(
        row.actionId,
        row.reviewId,
        row.placeId,
        row.label,
        row.reviewBucket,
        row.action,
        row.decision,
        row.reviewer,
        row.note,
        row.sampleArticleUid,
        row.createdAt,
        row.payloadJson,
      );
      db.prepare(
        `
        INSERT INTO geocode_review_item_state (
          review_id, place_id, label, review_bucket, current_action, current_decision,
          reviewer, note, sample_article_uid, action_count, updated_at, last_action_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(review_id) DO UPDATE SET
          place_id=excluded.place_id,
          label=excluded.label,
          review_bucket=excluded.review_bucket,
          current_action=excluded.current_action,
          current_decision=excluded.current_decision,
          reviewer=excluded.reviewer,
          note=excluded.note,
          sample_article_uid=excluded.sample_article_uid,
          action_count=geocode_review_item_state.action_count + 1,
          updated_at=excluded.updated_at,
          last_action_id=excluded.last_action_id
      `,
      ).run(
        row.reviewId,
        row.placeId,
        row.label,
        row.reviewBucket,
        row.action,
        row.decision,
        row.reviewer,
        row.note,
        row.sampleArticleUid,
        row.createdAt,
        row.actionId,
      );
    });
    tx();
    return {
      schemaVersion: "stage7_atlas_api.geocode_review_action_result.v1",
      ok: true,
      action: row,
      safety: {
        localReviewOnly: true,
        sqliteWriteExecuted: true,
        sqliteDbPath: this.exposeInternalDbPath ? this.dbPath : "",
        graphWriteExecuted: false,
        qdrantWriteExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
        networkCallExecuted: false,
        llmCallExecuted: false,
        mapFactPromoted: false,
      },
    };
  }

  async getMap({ limit, status, city, q } = {}) {
    const db = await this.db();
    const pageLimit = normalizeLimit(limit, 200, 1000);
    const where = [];
    const params = [];
    if (text(status)) {
      if (text(status) === "geocoded") {
        where.push("lat IS NOT NULL AND lon IS NOT NULL");
      } else {
        where.push("geocode_status = ?");
        params.push(text(status));
      }
    }
    if (text(city)) {
      where.push("city = ?");
      params.push(text(city));
    }
    if (text(q)) {
      where.push("normalized_place LIKE ?");
      params.push(`%${text(q).toLowerCase()}%`);
    }
    const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const rows = db
      .prepare(
        `
        SELECT * FROM map_geocode_places
        ${whereSql}
        ORDER BY (event_count + entity_count) DESC, label
        LIMIT ?
      `,
      )
      .all(...params, pageLimit);
    const summary = db
      .prepare(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN lat IS NOT NULL AND lon IS NOT NULL THEN 1 ELSE 0 END) AS geocoded FROM map_geocode_places",
      )
      .get();
    return {
      schemaVersion: "stage7_atlas_api.map_geocode_response.v1",
      generatedAt: new Date().toISOString(),
      summary: {
        total: summary.total || 0,
        geocoded: summary.geocoded || 0,
        unresolved: (summary.total || 0) - (summary.geocoded || 0),
      },
      filters: {
        status: text(status) || null,
        city: text(city) || null,
        q: text(q) || null,
      },
      places: rows.map((row) => ({
        placeId: row.place_id,
        label: row.label,
        city: row.city,
        lat: row.lat,
        lon: row.lon,
        geocodeStatus: row.geocode_status,
        geocodeSource: row.geocode_source,
        precision: row.precision,
        eventCount: row.event_count,
        entityCount: row.entity_count,
        articleCount: row.article_count,
        sampleArticleUid: row.sample_article_uid,
      })),
      safety: {
        networkCallExecuted: false,
        paidApiUsed: false,
        sqliteWriteExecuted: false,
      },
    };
  }

  async getGeocodeReview({ limit, bucket, q } = {}) {
    const db = await this.db();
    const pageLimit = normalizeLimit(limit, 50, 500);
    const where = [];
    const params = [];
    if (text(bucket)) {
      where.push("r.review_bucket = ?");
      params.push(text(bucket));
    }
    if (text(q)) {
      where.push("(r.normalized_place LIKE ? OR r.label LIKE ?)");
      const query = `%${text(q).toLowerCase()}%`;
      params.push(query, `%${text(q)}%`);
    }
    const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
    const rows = db
      .prepare(
        `
        SELECT
          r.*,
          s.current_action,
          s.current_decision,
          s.reviewer,
          s.note,
          s.updated_at AS geocode_state_updated_at,
          s.action_count,
          s.last_action_id
        FROM map_geocode_review_items r
        LEFT JOIN geocode_review_item_state s ON s.review_id = r.review_id
        ${whereSql}
        ORDER BY (r.event_count + r.entity_count) DESC, r.confidence DESC, r.label
        LIMIT ?
      `,
      )
      .all(...params, pageLimit);
    const total = db.prepare(`SELECT COUNT(*) AS count FROM map_geocode_review_items r ${whereSql}`).get(...params).count;
    return {
      schemaVersion: "stage7_atlas_api.geocode_review_response.v1",
      generatedAt: new Date().toISOString(),
      decision: "local_sqlite_geocode_review_queue",
      page: {
        limit: pageLimit,
        total,
        returned: rows.length,
      },
      filters: {
        bucket: text(bucket) || null,
        q: text(q) || null,
      },
      facets: {
        buckets: createFacet(
          db
            .prepare(
              "SELECT review_bucket AS label, COUNT(*) AS count FROM map_geocode_review_items GROUP BY review_bucket ORDER BY count DESC",
            )
            .all(),
        ),
      },
      items: rows.map(mapGeocodeReviewRow),
      safety: {
        networkCallExecuted: false,
        paidApiUsed: false,
        sqliteWriteExecuted: false,
        graphWriteExecuted: false,
        qdrantWriteExecuted: false,
      },
    };
  }

  async getRecommendations({ limit } = {}) {
    const db = await this.db();
    const pageLimit = normalizeLimit(limit, 20, 100);
    const rows = db.prepare("SELECT * FROM recommendations ORDER BY row_pk LIMIT ?").all(pageLimit);
    return {
      schemaVersion: "stage7_atlas_api.recommendations_response.v1",
      generatedAt: new Date().toISOString(),
      decision: "local_sqlite_recommendations",
      recommendationCount: rows.length,
      recommendations: rows.map((row) => ({
        id: row.item_id,
        type: row.type,
        title: row.title,
        score: row.score,
        evidence: maybeJson(row.evidence_json, []),
      })),
      safety: {
        modelCallExecuted: false,
        qdrantWriteExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
      },
    };
  }

  async getGraphRagAnswers({ limit } = {}) {
    const db = await this.db();
    const pageLimit = normalizeLimit(limit, 10, 50);
    const rows = db.prepare("SELECT * FROM graph_rag_answers ORDER BY row_pk LIMIT ?").all(pageLimit);
    return {
      schemaVersion: "stage7_atlas_api.graph_rag_answers_response.v1",
      generatedAt: new Date().toISOString(),
      answerCount: rows.length,
      llmCallExecuted: false,
      answers: rows.map((row) => ({
        id: row.item_id,
        query: row.query,
        answer: row.answer,
        citation_count: row.citation_count,
        fact_count: row.fact_count,
        citations: maybeJson(row.citations_json, []),
      })),
      safety: {
        modelCallExecuted: false,
        qdrantWriteExecuted: false,
        neo4jWriteExecuted: false,
      },
    };
  }

  async getVectorRouterStatus() {
    const db = await this.db();
    const report = db.prepare("SELECT * FROM runtime_reports WHERE report_name = 'vector_collection_router_smoke' LIMIT 1").get();
    const raw = maybeJson(report?.raw_json, {});
    return {
      schemaVersion: "stage7_atlas_api.vector_router_status.v1",
      ok: Boolean(raw.ok ?? true),
      decision: raw.decision || report?.decision || "local_sqlite_vector_report_loaded",
      generatedAt: raw.generated_at || null,
      sampleSizePerCollection: raw.sample_size_per_collection || 0,
      topK: raw.top_k || 0,
      collectionGroups: raw.collection_groups || {},
      channelProbeSummary: raw.channel_probes || {},
      routerCases: (raw.router_cases || []).map((item) => ({
        id: item.id || "",
        lang: item.lang || "",
        routedChannels: item.routed_channels || [],
        fusedCount: Array.isArray(item.fused) ? item.fused.length : 0,
      })),
      safety: {
        modelLoaded: Boolean(raw.safety?.model_loaded),
        embeddingCallExecuted: Boolean(raw.safety?.embedding_call_executed),
        qdrantWriteExecuted: Boolean(raw.safety?.qdrant_write_executed),
        qdrantAliasChangeExecuted: Boolean(raw.safety?.qdrant_alias_change_executed),
        productionPublishExecuted: Boolean(raw.safety?.production_publish_executed),
      },
      serviceIntegration: {
        liveVectorSearchEnabled: false,
        searchMode: "sqlite_fts5_trigram",
      },
    };
  }
}
