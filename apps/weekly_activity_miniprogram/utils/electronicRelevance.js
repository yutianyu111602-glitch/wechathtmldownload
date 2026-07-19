const ELECTRONIC_RELEVANCE_CONTRACT_VERSION = "weekly_electronic_relevance.v2";

// Keep this contract behaviorally equivalent to the CloudRun adapter. The
// parity corpus and fingerprint test fail if either runtime's rules drift.
const STRONG_ELECTRONIC_PATTERN_SOURCE = [
  "\\b(?:techno|house|rave|electro|electronic|electronica|disco|ambient|trance|dnb|breakbeat|breaks|dubstep|psydub|garage|ukg|jungle|idm|hardstyle|amapiano|acid|hardgroove|psytrance|goa|downtempo|ebm|gabber|neorave|footwork|juke|leftfield|edm|synth|modular)\\b",
  "\\bdrum\\s*(?:and|&)\\s*bass\\b",
  "\\b(?:bass\\s+music|uk\\s+bass|heavy\\s+bass|baile\\s+funk|future\\s+funk|club\\s+trax|latin\\s+club|jersey\\s+club)\\b",
  "电子音乐|电子|浩室|铁克诺|锐舞|迷幻电子",
].join("|");

const WEAK_ELECTRONIC_PATTERN_SOURCE = [
  "\\b(?:dj|djs|club|party|dub|bass|label)\\b",
  "俱乐部|夜店|舞池|派对|厂牌",
].join("|");

const NEGATED_ELECTRONIC_PATTERN_SOURCE = "\\bnon[_ -]?electronic\\b|非电子(?:音乐)?";

const NON_ELECTRONIC_RULE_DEFINITIONS = [
  ["standup", "脱口秀|单口喜剧|stand[-\\s]?up"],
  ["cocktail", "鸡尾酒|cocktail"],
  ["comedy", "喜剧|comedy|相声"],
  ["jazz", "爵士|\\bjazz(?:y)?\\b"],
  ["band", "乐队|\\bband\\b"],
  ["funk", "放克|\\bfunk\\b"],
  ["swing", "\\bswing\\b"],
  ["folk", "民谣|民歌|\\bfolk\\b"],
  ["rock", "摇滚|后摇|朋克|\\b(?:rock|punk|post[-\\s]?rock|emo)\\b"],
  ["rap", "嘻哈|说唱|\\b(?:hip[-\\s]?hop|rap)\\b"],
  ["classical", "古典|合唱|长笛|\\b(?:classical|flute)\\b"],
  ["pop", "流行(?:演唱会|音乐|歌手)|\\b(?:k[-\\s]?pop|c[-\\s]?pop|pop)\\b"],
  ["non_music_event", "婚礼|酒节|市集|漫展|放映|话剧|音乐剧|\\b(?:wedding|screening|film)\\b"],
];

const STRONG_ELECTRONIC_EVIDENCE_KEYS = [
  "title",
  "title_display",
  "title_original",
  "displayTitle",
  "summary",
  "description",
  "description_text",
  "genres",
  "genre",
  "music_styles",
  "styles",
  "styleLabel",
  "tags",
  "category",
  "evidence",
  "description_original_lines",
];

const ACTIVITY_RELEVANCE_KEYS = STRONG_ELECTRONIC_EVIDENCE_KEYS.concat([
  "promoter",
  "organizer",
  "organizer_name",
  "venue",
  "venue_name",
  "lineup",
]);

const STRONG_ELECTRONIC_EVIDENCE_RE = new RegExp(STRONG_ELECTRONIC_PATTERN_SOURCE, "i");
const WEAK_ELECTRONIC_EVIDENCE_RE = new RegExp(WEAK_ELECTRONIC_PATTERN_SOURCE, "i");
const NEGATED_ELECTRONIC_RE = new RegExp(NEGATED_ELECTRONIC_PATTERN_SOURCE, "gi");
const NON_ELECTRONIC_RULES = NON_ELECTRONIC_RULE_DEFINITIONS.map(([reason, source]) => ({
  reason,
  pattern: new RegExp(source, "i"),
}));

const ELECTRONIC_RELEVANCE_HINTS = Object.freeze([
  STRONG_ELECTRONIC_PATTERN_SOURCE,
  WEAK_ELECTRONIC_PATTERN_SOURCE,
]);
const NON_ELECTRONIC_RELEVANCE_HINTS = Object.freeze(
  NON_ELECTRONIC_RULE_DEFINITIONS.map(([, source]) => source),
);

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

function collectItemText(item, keys) {
  const out = [];
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(item || {}, key)) {
      collectText(item[key], out);
    }
  }
  return out.join(" ");
}

function activityRelevanceText(item) {
  return collectItemText(item, ACTIVITY_RELEVANCE_KEYS);
}

function strongElectronicEvidenceText(item) {
  return collectItemText(item, STRONG_ELECTRONIC_EVIDENCE_KEYS).replace(NEGATED_ELECTRONIC_RE, " ");
}

function exclusionReasonForText(text) {
  for (const rule of NON_ELECTRONIC_RULES) {
    if (rule.pattern.test(text)) return rule.reason;
  }
  return "";
}

function nonElectronicExclusionReason(item) {
  const text = activityRelevanceText(item);
  const strongText = strongElectronicEvidenceText(item);
  if (!text || STRONG_ELECTRONIC_EVIDENCE_RE.test(strongText)) return "";
  return exclusionReasonForText(text);
}

function classifyElectronicMusicRelevance(item) {
  const text = activityRelevanceText(item);
  if (!text) return "unknown";
  if (STRONG_ELECTRONIC_EVIDENCE_RE.test(strongElectronicEvidenceText(item))) return "electronic";
  if (exclusionReasonForText(text)) return "non_electronic";
  if (WEAK_ELECTRONIC_EVIDENCE_RE.test(text)) return "electronic";
  return "unknown";
}

function isElectronicMusicRelevantItem(item) {
  return classifyElectronicMusicRelevance(item) !== "non_electronic";
}

function electronicRelevanceContractFingerprint() {
  return JSON.stringify({
    version: ELECTRONIC_RELEVANCE_CONTRACT_VERSION,
    strong: STRONG_ELECTRONIC_PATTERN_SOURCE,
    weak: WEAK_ELECTRONIC_PATTERN_SOURCE,
    negatedElectronic: NEGATED_ELECTRONIC_PATTERN_SOURCE,
    nonElectronic: NON_ELECTRONIC_RULE_DEFINITIONS,
    strongEvidenceKeys: STRONG_ELECTRONIC_EVIDENCE_KEYS,
    relevanceKeys: ACTIVITY_RELEVANCE_KEYS,
  });
}

module.exports = {
  ELECTRONIC_RELEVANCE_HINTS,
  NON_ELECTRONIC_RELEVANCE_HINTS,
  activityRelevanceText,
  classifyElectronicMusicRelevance,
  electronicRelevanceContractFingerprint,
  isElectronicMusicRelevantItem,
  nonElectronicExclusionReason,
};
