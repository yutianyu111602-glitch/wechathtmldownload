// utils/cityFootprint.js
// Geographic "cities played" footprint from a DJ's event list. The curated
// relation-trajectory lens only covers ~220 DJs; ~30% of all DJs play 2+ cities,
// so this surfaces the same story for the long tail from event data already in the
// artist DTO. Pure, ES5 (shared by the artist page and the star-map inspector).

// Placeholder city tokens that carry no geographic meaning.
var CITY_PLACEHOLDERS = {
  "未知": 1, "unknown": 1, "n/a": 1, "na": 1, "tba": 1, "待定": 1, "其他": 1, "online": 1, "线上": 1,
};

// Common English names for scene cities -> canonical Chinese, so "Beijing" and
// "北京" don't split into two undercounted buckets.
var CITY_ALIASES = {
  beijing: "北京", shanghai: "上海", chengdu: "成都", chongqing: "重庆",
  guangzhou: "广州", shenzhen: "深圳", hangzhou: "杭州", wuhan: "武汉",
  "xian": "西安", "xi'an": "西安", changsha: "长沙", nanjing: "南京",
  kunming: "昆明", xiamen: "厦门", tianjin: "天津", qingdao: "青岛",
  dalian: "大连", suzhou: "苏州", hongkong: "香港", "hong kong": "香港",
  macau: "澳门", macao: "澳门", taipei: "台北",
};

// Normalize a raw event city: drop placeholders, merge English aliases, and merge
// 市/省 suffix variants (成都/成都市) so the same city's events don't split.
function normalizeCityName(raw) {
  var c = String(raw || "").trim();
  if (!c) return "";
  var lower = c.toLowerCase();
  if (CITY_ALIASES[lower]) return CITY_ALIASES[lower];
  if (c.length >= 3 && /[市省]$/.test(c)) c = c.slice(0, -1);
  if (CITY_PLACEHOLDERS[c.toLowerCase()]) return "";
  return c;
}

// Aggregate an event list into a city footprint sorted by event count desc.
// Returns { order: [city...], counts: { city: n }, ranges: { city: {first,last} } }.
function cityFootprint(events) {
  var counts = {}, ranges = {}, order = [];
  events = events || [];
  for (var i = 0; i < events.length; i++) {
    var e = events[i];
    var c = normalizeCityName(e && e.city);
    if (!c) continue;
    if (!counts[c]) { counts[c] = 0; order.push(c); ranges[c] = { first: "", last: "" }; }
    counts[c]++;
    var d = String((e && e.date) || "").slice(0, 10);
    if (d) {
      if (!ranges[c].first || d < ranges[c].first) ranges[c].first = d;
      if (!ranges[c].last || d > ranges[c].last) ranges[c].last = d;
    }
  }
  order.sort(function (a, b) { return counts[b] - counts[a]; });
  return { order: order, counts: counts, ranges: ranges };
}

module.exports = { normalizeCityName: normalizeCityName, cityFootprint: cityFootprint };
