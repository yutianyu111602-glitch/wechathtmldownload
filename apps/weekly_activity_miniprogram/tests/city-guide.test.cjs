const assert = require("node:assert/strict");
const test = require("node:test");

const { buildCityGuide, cityMatches } = require("../utils/cityGuide");

const cities = [
  { city_key: "hangzhou", city: "杭州", displayCity: "杭州", item_count: 3 },
  { city_key: "shanghai", city: "上海", displayCity: "上海", item_count: 2 },
  { city_key: "empty", city: "空城", displayCity: "空城", item_count: 0 },
];

const items = [
  {
    id: "hz-late",
    city_key: "hangzhou",
    title: "Warehouse techno night",
    date: "2026-06-28",
    venueLabel: "DONG",
    lineupLabel: "Alpha / Beta",
    styleLabel: "Techno",
    sourceHash: "src:hz-late",
    hasMapLocation: true,
  },
  {
    id: "hz-near",
    city_key: "hangzhou",
    title: "杭州 bass club session",
    date: "2026-06-26",
    venueLabel: "DONG",
    lineupLabel: "Gamma",
    styleLabel: "Bass",
    sourceHash: "src:hz-near",
  },
  {
    id: "hz-missing",
    city_key: "hangzhou",
    title: "电子音乐线索",
    date: "2026-06-27",
    styleLabel: "Electronic",
  },
  {
    id: "sh-good",
    city_key: "shanghai",
    title: "Shanghai house night",
    date: "2026-06-26",
    venueLabel: "ALL",
    lineupLabel: "Delta",
    styleLabel: "House",
  },
  {
    id: "hz-rock",
    city_key: "hangzhou",
    title: "杭州摇滚乐队专场",
    date: "2026-06-26",
    venueLabel: "Live Bar",
    styleLabel: "Rock",
  },
];

test("city guide without selection returns city candidates only", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "", lang: "zh" });

  assert.equal(guide.hasSelection, false);
  assert.equal(guide.cities.length, 2);
  assert.equal(guide.cities[0].key, "hangzhou");
  assert.deepEqual(guide.decisionCards, []);
  assert.deepEqual(guide.venueLeads, []);
});

test("city guide filters to selected city and removes non-electronic items", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "hangzhou", lang: "zh" });

  assert.equal(guide.hasSelection, true);
  assert.equal(guide.selectedCityLabel, "杭州");
  assert.equal(guide.eventCount, 3);
  assert.ok(guide.items.every((item) => cityMatches(item, "hangzhou")));
  assert.equal(guide.items.some((item) => item.id === "hz-rock"), false);
  assert.ok(guide.decisionCards.length >= 2);
});

test("city guide chooses nearest dated item before higher-info later item", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "hangzhou", lang: "zh" });
  const nearest = guide.decisionCards.find((card) => card.key === "nearest");

  assert.ok(nearest);
  assert.equal(nearest.item.id, "hz-near");
  assert.equal(nearest.item.compactDate, "06.26");
});

test("city guide aggregates venue leads by selected city", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "hangzhou", lang: "zh" });

  assert.equal(guide.venueLeads[0].name, "DONG");
  assert.equal(guide.venueLeads[0].count, 2);
  assert.match(guide.venueLeads[0].meta, /2 场本周活动/);
});

test("decision cards carry a tags array after nightDecisionTags integration", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "hangzhou", lang: "zh" });
  guide.decisionCards.forEach(function (card) {
    assert.ok(Array.isArray(card.item.tags), "card " + card.key + " must have tags array");
  });
  // hz-near (nearest) has venue + lineup + source → at least venueClear/lineupClear/hasSource
  const nearest = guide.decisionCards.find(function (card) { return card.key === "nearest"; });
  assert.ok(nearest && nearest.item.tags.length > 0, "nearest card should have at least one evidence tag");
});

test("non-electronic rock item does not receive dancefloor tag (leak guard via city-guide path)", () => {
  const { buildNightDecisionTags } = require("../utils/nightDecisionTags");
  const rockItem = { id: "r1", title: "摇滚乐队专场", venueLabel: "Live Bar", styleLabel: "Rock" };
  const keys = buildNightDecisionTags(rockItem, "zh").map(function (t) { return t.key; });
  assert.ok(keys.indexOf("dancefloor") === -1, "rock item must not get dancefloor tag");
});

test("P1: decision card labels use tonight-decision framing", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "hangzhou", lang: "zh" });
  const nearest = guide.decisionCards.find((c) => c.key === "nearest");
  const clear = guide.decisionCards.find((c) => c.key === "clear");
  const dance = guide.decisionCards.find((c) => c.key === "dancefloor");
  assert.equal(nearest && nearest.label, "今晚可直接去");
  assert.equal(clear && clear.label, "第一次去更稳");
  // dancefloor card may be absent if deduplicated against "clear"; when present it must say 偏舞池
  if (dance) assert.equal(dance.label, "偏舞池");
});

test("P3: decision cards carry a nightType phrase for electronic dance items", () => {
  const guide = buildCityGuide({ cities, items, selectedCityKey: "hangzhou", lang: "zh" });
  guide.decisionCards.forEach(function (card) {
    assert.ok(typeof card.item.nightType === "string", "card " + card.key + " must have nightType string");
  });
  // hz-late (Techno) is the "clear" (best-info) card — should get dancefloor nightType phrase
  // Note: "dancefloor" key may be deduped away if it shares the same item as "clear"
  const clearCard = guide.decisionCards.find(function (c) { return c.key === "clear"; });
  assert.ok(clearCard && clearCard.item.nightType.length > 0, "clear (techno) card should have nightType phrase");
  assert.ok(clearCard.item.nightType.includes("club night"), "techno card nightType should mention club night");
});

test("city guide degrades safely when event fields are sparse", () => {
  const guide = buildCityGuide({
    cities: [{ city_key: "xiamen", city: "厦门", displayCity: "厦门", item_count: 1 }],
    items: [{ id: "xm-1", city_key: "xiamen", title: "厦门电子夜", styleLabel: "Electronic" }],
    selectedCityKey: "xiamen",
    lang: "zh",
  });

  assert.equal(guide.eventCount, 1);
  assert.equal(guide.decisionCards[0].item.title, "厦门电子夜");
  assert.match(guide.decisionCards[0].item.reason, /风格|基础活动线索/);
});
