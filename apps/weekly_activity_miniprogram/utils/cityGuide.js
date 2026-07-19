const { filterItemsByElectronic } = require("./genreFilter");
const { buildNightDecisionTags } = require("./nightDecisionTags");
const { itemMatchesDateKey } = require("./datePreview");
const { cityKeysForItem } = require("../services/homeFilters");

function safeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function arrayValues(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(safeText).filter(Boolean);
  return String(value).split(/[\/,，、|｜]/).map(safeText).filter(Boolean);
}

function numberValue(value) {
  var n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}

function cityMatches(item, cityKey) {
  var key = safeText(cityKey).toLowerCase();
  if (!key) return false;
  return cityKeysForItem(item).indexOf(key) !== -1;
}

function isoDate(value) {
  var text = safeText(value);
  var match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? match[1] + "-" + match[2] + "-" + match[3] : "";
}

function itemDate(item) {
  return isoDate(
    (item && (item.event_date_start || item.eventDateStart || item.date || item.dateLabel || item.startDate))
  );
}

function compactDate(value) {
  var date = isoDate(value);
  return date ? date.slice(5).replace("-", ".") : safeText(value);
}

function titleOf(item) {
  return safeText(item && (item.displayTitle || item.title || item.titleLabel || item.rawTitle));
}

function venueOf(item) {
  var direct = safeText(item && (item.venueLabel || item.venue_name || item.venueName || item.promoter));
  if (direct) return direct;
  var venues = arrayValues(item && item.venue);
  return venues[0] || "";
}

function lineupOf(item) {
  var label = safeText(item && (item.lineupLabel || item.lineupText));
  if (label) return label;
  var lineup = arrayValues(item && (item.lineupItems || item.lineup_artists || item.lineup));
  return lineup.slice(0, 4).join(" / ");
}

function styleOf(item) {
  var label = safeText(item && (item.styleLabel || item.genreLabel || item.musicStyle));
  if (label) return label;
  return arrayValues(item && (item.styles || item.style || item.genres)).slice(0, 3).join(" / ");
}

function hasSource(item) {
  return Boolean(item && (
    item.sourceHash || item.source_hash || item.sourceRefId || item.source_ref_id ||
    (item.source_action && item.source_action.available) ||
    (item.source_article && item.source_article.url_hash)
  ));
}

function hasMap(item) {
  return Boolean(item && (item.hasMapLocation || item.mapLocation || item.latitude || item.longitude));
}

function infoScore(item) {
  var score = 0;
  if (itemDate(item)) score += 3;
  if (venueOf(item)) score += 3;
  if (lineupOf(item)) score += 2;
  if (hasSource(item)) score += 2;
  if (hasMap(item)) score += 2;
  if (styleOf(item)) score += 1;
  if (safeText(item && (item.addressLabel || item.address || item.address_full))) score += 1;
  return score;
}

function danceScore(item) {
  var text = [
    titleOf(item),
    venueOf(item),
    lineupOf(item),
    styleOf(item),
    safeText(item && item.summary),
  ].join(" ").toLowerCase();
  var score = infoScore(item);
  if (/techno|house|bass|break|electro|trance|rave|club|dj|舞池|派对|电子|蹦迪|跳舞/i.test(text)) score += 5;
  if (lineupOf(item)) score += 2;
  if (venueOf(item)) score += 1;
  return score;
}

function cityLabelOf(city, lang) {
  return safeText(city && (city.displayCity || city.label || city.city || city.city_name || city.city_key))
    || (lang === "en" ? "City" : "城市");
}

function normalizeCityRows(cities, lang) {
  return (Array.isArray(cities) ? cities : [])
    .map(function (city) {
      var key = safeText(city && (city.city_key || city.key || city.cityKey));
      var count = numberValue(city && (city.item_count || city.count || city.eventCount));
      return {
        key: key,
        city_key: key,
        label: cityLabelOf(city, lang),
        itemCount: count,
      };
    })
    .filter(function (city) { return city.key && city.itemCount > 0; })
    .sort(function (a, b) { return b.itemCount - a.itemCount || a.label.localeCompare(b.label); });
}

function itemSummary(item) {
  var date = compactDate(itemDate(item));
  var venue = venueOf(item);
  var lineup = lineupOf(item);
  return [date, venue, lineup].filter(Boolean).join(" · ");
}

function itemReason(item, lang) {
  var reasons = [];
  if (venueOf(item)) reasons.push(lang === "en" ? "venue" : "场地");
  if (lineupOf(item)) reasons.push(lang === "en" ? "lineup" : "阵容");
  if (hasSource(item)) reasons.push(lang === "en" ? "source" : "来源");
  if (hasMap(item)) reasons.push(lang === "en" ? "map" : "地图");
  if (styleOf(item)) reasons.push(lang === "en" ? "style" : "风格");
  if (!reasons.length) return lang === "en" ? "Basic event lead, open source for details." : "基础活动线索，详情请看原文。";
  return lang === "en"
    ? "Clear " + reasons.slice(0, 4).join(" / ") + " fields."
    : reasons.slice(0, 4).join(" / ") + "字段明确。";
}

var NIGHT_TYPE_PHRASE = {
  cautionBar:   { zh: "更像酒吧暖场，不一定是完整舞池", en: "More bar than club, not a full dancefloor" },
  experimental: { zh: "偏实验，适合想听新声音的人",     en: "Experimental, for those seeking new sounds" },
  commercial:   { zh: "偏商业电子，偏大型派对",         en: "Commercial, festival-adjacent" },
  dancefloor:   { zh: "更像认真跳舞的 club night",      en: "Electronic dance night" },
};
var NIGHT_TYPE_KEYS = ["cautionBar", "experimental", "commercial", "dancefloor"];

function nightTypeSummaryOf(item, lang) {
  var tags = buildNightDecisionTags(item, lang);
  for (var i = 0; i < NIGHT_TYPE_KEYS.length; i++) {
    var k = NIGHT_TYPE_KEYS[i];
    for (var j = 0; j < tags.length; j++) {
      if (tags[j].key === k) {
        var phrase = NIGHT_TYPE_PHRASE[k];
        return phrase ? (lang === "en" ? phrase.en : phrase.zh) : "";
      }
    }
  }
  return "";
}

function projectItem(item, lang) {
  return {
    id: safeText(item && (item.id || item.event_id || item.eventId)),
    title: titleOf(item) || (lang === "en" ? "Untitled event" : "未命名活动"),
    meta: itemSummary(item),
    date: itemDate(item),
    compactDate: compactDate(itemDate(item)),
    venueName: venueOf(item),
    lineup: lineupOf(item),
    style: styleOf(item),
    reason: itemReason(item, lang),
    score: infoScore(item),
    tags: buildNightDecisionTags(item, lang).slice(0, 4),
    nightType: nightTypeSummaryOf(item, lang),
  };
}

function dedupeCards(cards) {
  var seen = {};
  var output = [];
  for (var i = 0; i < cards.length; i += 1) {
    var card = cards[i];
    if (!card || !card.item || !card.item.id) continue;
    if (seen[card.item.id]) continue;
    seen[card.item.id] = true;
    output.push(card);
  }
  return output;
}

function topVenueRows(items, lang) {
  var map = {};
  (items || []).forEach(function (item) {
    var name = venueOf(item);
    if (!name) return;
    var key = name.toLowerCase();
    if (!map[key]) {
      map[key] = {
        key: key,
        name: name,
        city: safeText(item.cityLabel || item.city || ""),
        count: 0,
        eventIds: [],
      };
    }
    map[key].count += 1;
    var id = safeText(item.id || item.event_id || item.eventId);
    if (id) map[key].eventIds.push(id);
  });
  return Object.keys(map)
    .map(function (key) { return map[key]; })
    .sort(function (a, b) { return b.count - a.count || a.name.localeCompare(b.name); })
    .slice(0, 6)
    .map(function (row) {
      return {
        key: row.key,
        name: row.name,
        meta: row.count + " " + (lang === "en" ? "events this week" : "场本周活动"),
        count: row.count,
      };
    });
}

function buildCityGuide(options) {
  options = options || {};
  var lang = options.lang === "en" ? "en" : "zh";
  var selectedCityKey = safeText(options.selectedCityKey);
  var cityRows = normalizeCityRows(options.cities || [], lang);
  var selectedCity = cityRows.filter(function (city) { return city.key === selectedCityKey; })[0] || null;
  var allItems = filterItemsByElectronic(Array.isArray(options.items) ? options.items : []);
  var businessDateKey = isoDate(options.businessDateKey);
  if (businessDateKey) {
    allItems = allItems.filter(function (item) { return itemMatchesDateKey(item, businessDateKey); });
  }
  var cityItems = selectedCityKey
    ? allItems.filter(function (item) { return cityMatches(item, selectedCityKey); })
    : [];
  var datedItems = cityItems
    .map(function (item, index) { return { item: item, index: index, date: itemDate(item), score: infoScore(item) }; })
    .sort(function (a, b) {
      if (a.date && b.date && a.date !== b.date) return a.date.localeCompare(b.date);
      if (a.date && !b.date) return -1;
      if (!a.date && b.date) return 1;
      return b.score - a.score || a.index - b.index;
    });
  var byInfo = cityItems.slice().sort(function (a, b) { return infoScore(b) - infoScore(a); });
  var byDance = cityItems.slice().sort(function (a, b) { return danceScore(b) - danceScore(a); });
  var cards = dedupeCards([
    datedItems[0] && {
      key: "nearest",
      label: lang === "en" ? "Tonight's pick" : "今晚可直接去",
      item: projectItem(datedItems[0].item, lang),
    },
    byInfo[0] && {
      key: "clear",
      label: lang === "en" ? "Best for first-timers" : "第一次去更稳",
      item: projectItem(byInfo[0], lang),
    },
    byDance[0] && {
      key: "dancefloor",
      label: lang === "en" ? "Dancefloor" : "偏舞池",
      item: projectItem(byDance[0], lang),
    },
  ]);
  var activeDates = {};
  cityItems.forEach(function (item) {
    var date = itemDate(item);
    if (date) activeDates[date] = true;
  });
  return {
    hasSelection: Boolean(selectedCityKey),
    selectedCityKey: selectedCityKey,
    selectedCityLabel: selectedCity ? selectedCity.label : "",
    cities: cityRows,
    items: cityItems,
    eventCount: cityItems.length,
    activeDateCount: Object.keys(activeDates).length,
    decisionCards: selectedCityKey ? cards : [],
    venueLeads: selectedCityKey ? topVenueRows(cityItems, lang) : [],
  };
}

module.exports = {
  buildCityGuide: buildCityGuide,
  cityMatches: cityMatches,
};
