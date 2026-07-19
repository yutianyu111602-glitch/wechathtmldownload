// utils/nightDecisionTags.js
// Evidence-based decision tags for the 坏DJ night-decision tool.
// Input: a single compactItem-normalised event (raw aliases also accepted).
// Output: ordered [{key, label, reason}], max ~12 tags; caller slices to display budget.
// Pure, ES5. No wx. No scores, no opinions — every tag derives from field facts.

var genreFilter = require("./genreFilter");

// ─── text helpers (mirrors cityGuide accessors) ────────────────────────────

function safeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function arrayValues(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(safeText).filter(Boolean);
  return String(value).split(/[\/,，、|｜]/).map(safeText).filter(Boolean);
}

// ─── field accessors (tolerant of compactItem booleans + raw aliases) ────────

function hasVenueOf(item) {
  if (!item) return false;
  return Boolean(
    item.hasVenue ||
    item.venueLabel || item.venue_name || item.venueName || item.promoter ||
    (Array.isArray(item.venue) && item.venue.length)
  );
}

function hasAddressOf(item) {
  if (!item) return false;
  return Boolean(item.hasAddress || item.addressLabel || item.address || item.address_full);
}

function hasMapOf(item) {
  if (!item) return false;
  return Boolean(item.hasMapLocation || item.mapLocation || item.latitude || item.longitude);
}

function hasSourceOf(item) {
  if (!item) return false;
  return Boolean(
    item.hasSource ||
    item.sourceHash || item.source_hash ||
    item.sourceRefId || item.source_ref_id ||
    (item.source_action && item.source_action.available) ||
    (item.source_article && item.source_article.url_hash)
  );
}

function hasLineupOf(item) {
  if (!item) return false;
  return Boolean(
    item.hasLineup ||
    item.lineupLabel || item.lineupText ||
    (Array.isArray(item.lineupItems) && item.lineupItems.length) ||
    (Array.isArray(item.lineup_artists) && item.lineup_artists.length) ||
    (Array.isArray(item.lineup) && item.lineup.length)
  );
}

function hasTrustedTimeOf(item) {
  if (!item) return false;
  return Boolean(
    item.hasTrustedTime ||
    item.event_date_start || item.eventDateStart ||
    item.starts_at || item.dateLabel || item.date
  );
}

function hasPriceOf(item) {
  if (!item) return false;
  return Boolean(
    item.hasPrice ||
    (Array.isArray(item.price) && item.price.length) ||
    item.priceLabel || item.price_text || item.ticketing || item.ticketing_text
  );
}

function styleTextOf(item) {
  if (!item) return "";
  var parts = []
    .concat(Array.isArray(item.musicStyles) ? item.musicStyles : [])
    .concat(Array.isArray(item.music_styles) ? item.music_styles : [])
    .concat(Array.isArray(item.styles) ? item.styles : [])
    .concat(Array.isArray(item.genres) ? item.genres : [])
    .concat(item.styleLabel ? [item.styleLabel] : [])
    .concat(item.genre ? [item.genre] : []);
  return parts.join(" ").toLowerCase();
}

function allTextOf(item) {
  if (!item) return "";
  return [
    safeText(item.displayTitle || item.title || ""),
    safeText(item.venueLabel || item.venue_name || ""),
    safeText(item.lineupLabel || ""),
    styleTextOf(item),
    safeText(item.summary || ""),
  ].join(" ").toLowerCase();
}

// ─── detection helpers ─────────────────────────────────────────────────────

// ponytail: regex literals share the exact keyword set from cityGuide.danceScore so they stay in sync
var DANCE_RE = /techno|house|bass|break|electro|trance|rave|club|dj|舞池|派对|电子|蹦迪|跳舞/i;
var EXPERIMENTAL_RE = /ambient|experimental|idm|modular|drone|noise|实验|氛围/i;
var COMMERCIAL_RE = /\bedm\b|mainstage|big.room|progressive.house|商业/i;
var CAUTION_COCKTAIL_RE = /鸡尾酒|cocktail/i;
var CAUTION_BAR_RE = /\bbar\b|lounge|酒吧|酒水节/i;
var STRONG_ELECTRONIC_RE = /\b(?:dj|djs|club|techno|house|rave|electro|disco|ambient|bass|trance|dnb)\b|电子音乐|电子|俱乐部|夜店|舞池|派对|厂牌/i;

function isCautionBar(item) {
  var text = allTextOf(item);
  // Strong: cocktail/鸡尾酒 keyword is a clear non-dancefloor signal
  if (CAUTION_COCKTAIL_RE.test(text)) return true;
  // Weak: bar/lounge words without any strong electronic evidence
  if (CAUTION_BAR_RE.test(text) && !STRONG_ELECTRONIC_RE.test(text)) return true;
  return false;
}

function isDancefloor(item) {
  if (genreFilter.itemGenreOf(item) !== "electronic") return false;
  return DANCE_RE.test(allTextOf(item));
}

function isExperimental(item) {
  return EXPERIMENTAL_RE.test(styleTextOf(item));
}

function isCommercial(item) {
  return COMMERCIAL_RE.test(styleTextOf(item));
}

// ─── tag builder ───────────────────────────────────────────────────────────

function buildNightDecisionTags(item, lang) {
  if (!item || typeof item !== "object") return [];
  var zh = lang !== "en";
  var caution = isCautionBar(item);
  var isElectronic = genreFilter.itemGenreOf(item) === "electronic";
  var tags = [];

  // firstTime: electronic + venue + source, no bar/cocktail warning
  if (isElectronic && hasVenueOf(item) && hasSourceOf(item) && !caution) {
    tags.push({
      key: "firstTime",
      label: zh ? "适合第一次去" : "Good for a first visit",
      reason: zh
        ? "场地和原文都明确，适合第一次去的新人"
        : "Venue and source confirmed — comfortable first visit.",
    });
  }

  // solo: full logistics — address + map + source + trusted time
  if (hasAddressOf(item) && hasMapOf(item) && hasSourceOf(item) && hasTrustedTimeOf(item)) {
    tags.push({
      key: "solo",
      label: zh ? "适合一个人去" : "Easy to go solo",
      reason: zh
        ? "地址、地图、原文、时间齐全，一个人也可以直接出发"
        : "Address, map, source and time all confirmed.",
    });
  }

  // travelerFriendly: address + map (direct navigation even without source)
  if (hasAddressOf(item) && hasMapOf(item)) {
    tags.push({
      key: "travelerFriendly",
      label: zh ? "旅行者友好" : "Traveler-friendly",
      reason: zh
        ? "有明确地址与地图，外地人可直接导航"
        : "Address and map available — navigate straight there.",
    });
  }

  // cautionBar shown early so users see the warning before dancefloor tags
  if (caution) {
    tags.push({
      key: "cautionBar",
      label: zh ? "慎选：更像酒吧不是 club" : "More bar than club",
      reason: zh
        ? "只有酒水或调酒线索，不一定是完整舞池"
        : "Cocktail / bar signals without clear dancefloor evidence.",
    });
  }

  // dancefloor: electronic genre + dance/club keywords — no bar leakage
  if (!caution && isDancefloor(item)) {
    tags.push({
      key: "dancefloor",
      label: zh ? "偏舞池" : "Dancefloor",
      reason: zh
        ? "风格或场景有明确舞池/俱乐部线索"
        : "Style or context confirms dancefloor focus.",
    });
  }

  // experimental: style signals
  if (isExperimental(item)) {
    tags.push({
      key: "experimental",
      label: zh ? "偏实验" : "Experimental",
      reason: zh
        ? "偏实验/氛围向音乐，适合想听新声音的人"
        : "Experimental or ambient focus — for adventurous ears.",
    });
  }

  // commercial: EDM/festival style
  if (isCommercial(item)) {
    tags.push({
      key: "commercial",
      label: zh ? "偏商业" : "Commercial",
      reason: zh
        ? "风格偏商业电子或大型节日向"
        : "Commercial / festival-style electronic.",
    });
  }

  // factual info tags (useful for quick decision-making)
  if (hasLineupOf(item)) {
    tags.push({
      key: "lineupClear",
      label: zh ? "阵容明确" : "Lineup confirmed",
      reason: zh ? "已知阵容" : "Lineup listed.",
    });
  }

  if (hasVenueOf(item)) {
    tags.push({
      key: "venueClear",
      label: zh ? "场地明确" : "Venue confirmed",
      reason: zh ? "已知场地名" : "Venue listed.",
    });
  }

  if (hasMapOf(item)) {
    tags.push({
      key: "hasMap",
      label: zh ? "有地图" : "Map available",
      reason: zh ? "有坐标或地图定位" : "Location coordinates available.",
    });
  }

  if (hasSourceOf(item)) {
    tags.push({
      key: "hasSource",
      label: zh ? "有原文" : "Source article",
      reason: zh ? "有公众号原文可查" : "Source article linked.",
    });
  }

  if (hasPriceOf(item)) {
    tags.push({
      key: "needTicket",
      label: zh ? "需要购票" : "Ticketed",
      reason: zh ? "有票价或购票信息" : "Ticket info available.",
    });
  }

  return tags;
}

module.exports = {
  buildNightDecisionTags: buildNightDecisionTags,
};
