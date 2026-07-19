const assert = require("node:assert/strict");
const test = require("node:test");
const { buildFootprintCard } = require("../utils/footprintCard");

test("footprint card: aggregates merged cities, dedupes DJs, edges only among visited", () => {
  const profiles = [
    { name: "Alpha", city: "上海", events: [{ city: "上海" }, { city: "上海市" }, { city: "北京" }], peers: ["Beta", "Ghost"] },
    { name: "Beta", city: "北京", events: [{ city: "北京" }, { city: "北京" }, { city: "成都" }], peers: ["Alpha"] },
    { name: "alpha", city: "上海", events: [], peers: [] }, // dup of Alpha (case-insensitive) -> dropped
  ];
  const card = buildFootprintCard(profiles, 6);

  assert.equal(card.djCount, 2); // Alpha + Beta; "alpha" deduped
  assert.equal(card.cityCount, 3); // 上海(+上海市 merge) / 北京 / 成都
  assert.equal(card.topCities[0].city, "北京"); // 北京 ×3 (Alpha 1 + Beta 2)
  assert.equal(card.topCities[0].count, 3);
  assert.equal(card.miniGraph.edges.length, 1); // single undirected Alpha<->Beta; Ghost not visited
  assert.deepEqual([card.miniGraph.edges[0].a, card.miniGraph.edges[0].b].sort(), ["Alpha", "Beta"]);
});

test("footprint card: empty input -> zeros, never throws", () => {
  const card = buildFootprintCard([], 6);
  assert.equal(card.djCount, 0);
  assert.equal(card.cityCount, 0);
  assert.equal(card.topCities.length, 0);
  assert.equal(card.miniGraph.edges.length, 0);
});
