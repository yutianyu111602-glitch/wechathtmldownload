const { buildExternalLinkAction } = require("./externalLinkAction.js");

const CATEGORY_ORDER = {
  source_article: 10,
  instagram: 20,
  mixtape_music: 30,
  radio: 40,
  video: 50,
  interview: 60,
  public_profile: 90,
  external: 100,
};

const CATEGORY_LABELS = {
  zh: {
    source_article: "原文",
    instagram: "Instagram",
    mixtape_music: "Mixtape",
    radio: "电台",
    video: "视频",
    interview: "采访",
    public_profile: "主页",
    external: "外链",
  },
  en: {
    source_article: "Source",
    instagram: "Instagram",
    mixtape_music: "Mixtape",
    radio: "Radio",
    video: "Video",
    interview: "Interview",
    public_profile: "Profile",
    external: "Link",
  },
};

const GENERATED_BIO_PREFIX_RE = /^\s*(证据来源|风格线索|来源关键词|来源线索|style clues?|source terms?)\s*[:：]/i;

function normalizeLang(value) {
  return value === "en" ? "en" : "zh";
}

function camelOrSnake(item, camel, snake) {
  if (!item || typeof item !== "object") return undefined;
  return item[camel] !== undefined ? item[camel] : item[snake];
}

function normalizeCategory(value) {
  const category = String(value || "external").trim().toLowerCase();
  return CATEGORY_ORDER[category] ? category : "external";
}

function normalizeScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function dedupeUrl(value) {
  try {
    const parsed = new URL(String(value || "").trim());
    if (parsed.pathname !== "/" && parsed.pathname.endsWith("/")) {
      parsed.pathname = parsed.pathname.replace(/\/+$/, "");
    }
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return String(value || "").trim();
  }
}

function displayLabelForLink(item, lang) {
  const labels = CATEGORY_LABELS[normalizeLang(lang)];
  const category = normalizeCategory(camelOrSnake(item, "publicCategory", "public_category"));
  const explicit = camelOrSnake(item, "displayLabel", "display_label");
  if (String(explicit || "").trim()) return String(explicit).trim();
  return labels[category] || labels.external;
}

function displayAllowed(item) {
  const allowed = camelOrSnake(item, "miniappDisplayAllowedCandidate", "miniapp_display_allowed_candidate");
  return allowed === true;
}

function blockReasons(item) {
  const value = camelOrSnake(item, "blockReasons", "block_reasons");
  return Array.isArray(value) ? value : [];
}

function normalizeExternalLink(item, lang, options = {}) {
  if (!item || typeof item !== "object") return null;
  if (options.requireDisplayAllowed !== false && !displayAllowed(item)) return null;
  if (blockReasons(item).length) return null;

  const category = normalizeCategory(camelOrSnake(item, "publicCategory", "public_category"));
  if (!CATEGORY_ORDER[category]) return null;

  const confidenceBand = String(camelOrSnake(item, "confidenceBand", "confidence_band") || "");
  const confidenceScore = normalizeScore(camelOrSnake(item, "confidenceScore", "confidence_score"));
  if (options.requireHighConfidence !== false && (confidenceBand !== "high" || confidenceScore < 85)) return null;

  const action = buildExternalLinkAction(item.url, lang, { linkType: category });
  if (!action.ok) return null;

  return {
    itemId: String(camelOrSnake(item, "itemId", "item_id") || action.url),
    entitySearchId: String(camelOrSnake(item, "entitySearchId", "entity_search_id") || ""),
    entityName: String(camelOrSnake(item, "entityName", "entity_name") || ""),
    entityType: String(camelOrSnake(item, "entityType", "entity_type") || ""),
    platform: String(item.platform || action.platform || "external"),
    publicCategory: category,
    displayLabel: displayLabelForLink(item, lang),
    displayGroup: String(camelOrSnake(item, "displayGroup", "display_group") || displayLabelForLink(item, lang)),
    displayPriority: CATEGORY_ORDER[category],
    url: action.url,
    sourceRef: String(camelOrSnake(item, "sourceRef", "source_ref") || ""),
    confidenceScore,
    confidenceBand: "high",
    action,
  };
}

function normalizeExternalLinks(items, lang, options = {}) {
  const perEntityLimit = Number.isFinite(options.perEntityLimit) ? options.perEntityLimit : 12;
  const totalLimit = Number.isFinite(options.limit) ? options.limit : 48;
  const seen = new Set();
  const perEntityCounts = new Map();
  const normalized = [];

  for (const item of Array.isArray(items) ? items : []) {
    const link = normalizeExternalLink(item, lang, options);
    if (!link) continue;
    const entityKey = link.entitySearchId || link.entityName || "_";
    const dedupeKey = `${entityKey}|${dedupeUrl(link.url)}`;
    if (seen.has(dedupeKey)) continue;
    if ((perEntityCounts.get(entityKey) || 0) >= perEntityLimit) continue;
    seen.add(dedupeKey);
    perEntityCounts.set(entityKey, (perEntityCounts.get(entityKey) || 0) + 1);
    normalized.push(link);
  }

  normalized.sort((a, b) => {
    const entityCompare = a.entityName.localeCompare(b.entityName, "zh-Hans-CN");
    if (entityCompare) return entityCompare;
    if (a.displayPriority !== b.displayPriority) return a.displayPriority - b.displayPriority;
    if (a.confidenceScore !== b.confidenceScore) return b.confidenceScore - a.confidenceScore;
    return a.url.localeCompare(b.url);
  });

  return normalized.slice(0, totalLimit);
}

function groupExternalLinksForDisplay(items, lang, options = {}) {
  const links = normalizeExternalLinks(items, lang, options);
  const groups = [];
  const index = new Map();
  for (const link of links) {
    const key = link.entitySearchId || link.entityName || "_";
    if (!index.has(key)) {
      index.set(key, {
        entitySearchId: link.entitySearchId,
        entityName: link.entityName,
        entityType: link.entityType,
        links: [],
      });
      groups.push(index.get(key));
    }
    index.get(key).links.push(link);
  }
  return groups;
}

function normalizeBioAtoms(value, options = {}) {
  const limit = Number.isFinite(options.bioAtomLimit) ? options.bioAtomLimit : 4;
  const requireSource = options.requireSourceBackedBioAtoms !== false;
  const raw = Array.isArray(value) ? value : [];
  const output = [];
  const seen = new Set();
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const text = typeof item === "string" ? item : camelOrSnake(item, "text", "text");
    const normalized = String(text || "").trim();
    if (!normalized) continue;
    if (GENERATED_BIO_PREFIX_RE.test(normalized)) continue;
    const sourceRef = String(camelOrSnake(item, "sourceRef", "source_ref") || "").trim();
    if (requireSource && !sourceRef) continue;
    const key = normalized.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push({
      text: normalized,
      sourceRef,
      verbatimSource: camelOrSnake(item, "verbatimSource", "verbatim_source") !== false,
    });
    if (output.length >= limit) break;
  }
  return output;
}

function normalizeDjDiscoverySectionsForDisplay(sections, lang, options = {}) {
  const perDjLinkLimit = Number.isFinite(options.perDjLinkLimit) ? options.perDjLinkLimit : 5;
  const totalSectionLimit = Number.isFinite(options.sectionLimit) ? options.sectionLimit : 24;
  const normalized = [];
  const seen = new Set();

  for (const section of Array.isArray(sections) ? sections : []) {
    if (!section || typeof section !== "object") continue;
    const name = String(camelOrSnake(section, "name", "name") || camelOrSnake(section, "displayName", "display_name") || "").trim();
    if (!name) continue;
    const nameKey = String(camelOrSnake(section, "nameKey", "name_key") || name.toLowerCase()).trim();
    const dedupeKey = nameKey || name.toLowerCase();
    if (seen.has(dedupeKey)) continue;

    const rawLinks = camelOrSnake(section, "links", "links") || camelOrSnake(section, "externalLinks", "external_links") || [];
    const links = normalizeExternalLinks(rawLinks, lang, {
      ...options,
      limit: perDjLinkLimit,
      perEntityLimit: perDjLinkLimit,
    });
    const bioAtoms = normalizeBioAtoms(camelOrSnake(section, "bioAtoms", "bio_atoms"), options);
    if (!links.length && !bioAtoms.length) continue;

    seen.add(dedupeKey);
    normalized.push({
      name,
      nameKey,
      source: String(section.source || ""),
      links,
      bioAtoms,
      hasLinks: links.length > 0,
      hasBioAtoms: bioAtoms.length > 0,
    });
    if (normalized.length >= totalSectionLimit) break;
  }

  return normalized;
}

function buildExternalLinkActionFromItem(item, lang) {
  const category = normalizeCategory(camelOrSnake(item, "publicCategory", "public_category"));
  return buildExternalLinkAction(item && item.url, lang, { linkType: category });
}

module.exports = {
  CATEGORY_ORDER,
  buildExternalLinkActionFromItem,
  displayLabelForLink,
  groupExternalLinksForDisplay,
  normalizeDjDiscoverySectionsForDisplay,
  normalizeExternalLink,
  normalizeExternalLinks,
};
