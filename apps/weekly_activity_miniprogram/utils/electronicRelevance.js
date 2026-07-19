const ELECTRONIC_EVIDENCE_RE = /\b(?:dj|djs|club|techno|house|rave|electro|disco|ambient|bass|trance|dnb|drum\s*(?:and|&)?\s*bass|breakbeat|dub|garage|jungle|idm|hardstyle|amapiano)\b|电子音乐|电子|俱乐部|夜店|舞池|派对|厂牌/i;

const NON_ELECTRONIC_RULES = [
  { reason: "standup", pattern: /脱口秀|单口喜剧|stand[-\s]?up|comedy/i },
  { reason: "cocktail", pattern: /鸡尾酒|cocktail/i },
  { reason: "folk", pattern: /民谣|\bfolk\b/i },
  { reason: "rock", pattern: /摇滚乐|摇滚专场|摇滚现场|摇滚演出|\brock\s*(?:band|festival|concert|show|live)\b/i },
];

function collectText(value, out) {
  if (value === null || value === undefined) return;
  if (typeof value === "string" || typeof value === "number") {
    out.push(String(value));
    return;
  }
  if (Array.isArray(value)) {
    for (const entry of value) collectText(entry, out);
  }
}

function activityRelevanceText(item) {
  const out = [];
  const keys = [
    "title",
    "title_display",
    "summary",
    "description",
    "description_text",
    "promoter",
    "organizer",
    "organizer_name",
    "venue",
    "venue_name",
    "lineup",
    "genres",
    "genre",
    "tags",
    "category",
    "evidence",
    "description_original_lines",
  ];
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(item || {}, key)) {
      collectText(item[key], out);
    }
  }
  return out.join(" ");
}

function nonElectronicExclusionReason(item) {
  const text = activityRelevanceText(item);
  if (!text) return "";
  if (ELECTRONIC_EVIDENCE_RE.test(text)) return "";
  for (const rule of NON_ELECTRONIC_RULES) {
    if (rule.pattern.test(text)) return rule.reason;
  }
  return "";
}

function isElectronicMusicRelevantItem(item) {
  return !nonElectronicExclusionReason(item);
}

module.exports = {
  isElectronicMusicRelevantItem,
  nonElectronicExclusionReason,
};
