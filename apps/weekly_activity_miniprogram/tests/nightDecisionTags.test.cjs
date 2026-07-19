const assert = require("node:assert/strict");
const test = require("node:test");

const { buildNightDecisionTags } = require("../utils/nightDecisionTags");

// ─── fixtures ──────────────────────────────────────────────────────────────

// Full-featured electronic club item (as compactItem would output)
const fullClubItem = {
  id: "full-1",
  displayTitle: "Warehouse Techno Night",
  venueLabel: "OIL",
  hasVenue: true,
  addressLabel: "四川北路 1600 号",
  hasAddress: true,
  hasMapLocation: true,
  mapLocation: { latitude: 31.25, longitude: 121.47 },
  lineupLabel: "Surgeon / Paula Temple",
  hasLineup: true,
  sourceHash: "src:abc",
  hasSource: true,
  hasTrustedTime: true,
  event_date_start: "2026-06-28",
  styleLabel: "Techno",
  musicStyles: ["techno"],
  genres: ["electronic"],
};

// Sparse item — title only, genre unknown
const sparseItem = {
  id: "sparse-1",
  title: "深圳夜晚",
};

// Cocktail bar (non-electronic)
const cocktailItem = {
  id: "bar-1",
  displayTitle: "鸡尾酒私人派对",
  title: "鸡尾酒私人派对",
  venueLabel: "Bar Blue",
  hasVenue: true,
  styleLabel: "Jazz",
};

// Experimental / ambient
const experimentalItem = {
  id: "exp-1",
  displayTitle: "Noise & Drone Set",
  styleLabel: "ambient",
  musicStyles: ["ambient", "experimental"],
  sourceHash: "src:exp",
  hasSource: true,
};

// Commercial EDM
const commercialItem = {
  id: "edm-1",
  displayTitle: "EDM Festival Night",
  styleLabel: "edm",
  musicStyles: ["edm"],
};

// Solo-ready: all four logistics present
const soloReadyItem = {
  id: "solo-ok",
  displayTitle: "Club Night Solo",
  title: "club night",
  venueLabel: "Shelter",
  hasVenue: true,
  addressLabel: "复兴西路 493 号",
  hasAddress: true,
  hasMapLocation: true,
  sourceHash: "src:solo",
  hasSource: true,
  hasTrustedTime: true,
  event_date_start: "2026-06-28",
  styleLabel: "Techno",
  genres: ["electronic"],
};

// Solo missing source — should suppress solo tag
const soloMissingSource = Object.assign({}, soloReadyItem, {
  id: "solo-nosrc",
  hasSource: false,
  sourceHash: null,
});

// ─── tests ─────────────────────────────────────────────────────────────────

test("full club item includes firstTime / solo / travelerFriendly / dancefloor / lineupClear / venueClear / hasMap / hasSource", () => {
  var tags = buildNightDecisionTags(fullClubItem, "zh");
  var keys = tags.map(function (t) { return t.key; });

  assert.ok(keys.indexOf("firstTime") !== -1, "missing firstTime");
  assert.ok(keys.indexOf("solo") !== -1, "missing solo");
  assert.ok(keys.indexOf("travelerFriendly") !== -1, "missing travelerFriendly");
  assert.ok(keys.indexOf("dancefloor") !== -1, "missing dancefloor");
  assert.ok(keys.indexOf("lineupClear") !== -1, "missing lineupClear");
  assert.ok(keys.indexOf("venueClear") !== -1, "missing venueClear");
  assert.ok(keys.indexOf("hasMap") !== -1, "missing hasMap");
  assert.ok(keys.indexOf("hasSource") !== -1, "missing hasSource");
});

test("full club item does NOT contain cautionBar", () => {
  var keys = buildNightDecisionTags(fullClubItem, "zh").map(function (t) { return t.key; });
  assert.ok(keys.indexOf("cautionBar") === -1, "club item must not have cautionBar");
});

test("sparse item returns array without throwing and has no logistics tags", () => {
  var tags = buildNightDecisionTags(sparseItem, "zh");
  assert.ok(Array.isArray(tags), "must return array");
  var keys = tags.map(function (t) { return t.key; });
  assert.ok(keys.indexOf("firstTime") === -1);
  assert.ok(keys.indexOf("solo") === -1);
  assert.ok(keys.indexOf("travelerFriendly") === -1);
  assert.ok(keys.indexOf("dancefloor") === -1);
});

test("cocktail item has cautionBar and does NOT have dancefloor (non-electronic leak guard)", () => {
  var keys = buildNightDecisionTags(cocktailItem, "zh").map(function (t) { return t.key; });
  assert.ok(keys.indexOf("cautionBar") !== -1, "should have cautionBar for cocktail");
  assert.ok(keys.indexOf("dancefloor") === -1, "dancefloor must not leak to cocktail/non-electronic item");
});

test("experimental item has experimental tag", () => {
  var keys = buildNightDecisionTags(experimentalItem, "zh").map(function (t) { return t.key; });
  assert.ok(keys.indexOf("experimental") !== -1, "missing experimental");
});

test("commercial item has commercial tag", () => {
  var keys = buildNightDecisionTags(commercialItem, "zh").map(function (t) { return t.key; });
  assert.ok(keys.indexOf("commercial") !== -1, "missing commercial");
});

test("solo appears when all four logistics present, disappears when source missing", () => {
  var readyKeys = buildNightDecisionTags(soloReadyItem, "zh").map(function (t) { return t.key; });
  var missingKeys = buildNightDecisionTags(soloMissingSource, "zh").map(function (t) { return t.key; });
  assert.ok(readyKeys.indexOf("solo") !== -1, "solo should fire when logistics complete");
  assert.ok(missingKeys.indexOf("solo") === -1, "solo must not fire when source missing");
});

test("deterministic: same input produces identical output on two calls", () => {
  var first = buildNightDecisionTags(fullClubItem, "zh");
  var second = buildNightDecisionTags(fullClubItem, "zh");
  assert.deepEqual(first, second);
});

test("null and undefined return empty array", () => {
  assert.deepEqual(buildNightDecisionTags(null, "zh"), []);
  assert.deepEqual(buildNightDecisionTags(undefined, "zh"), []);
});

test("english labels returned when lang is en", () => {
  var tags = buildNightDecisionTags(fullClubItem, "en");
  var solo = tags.find(function (t) { return t.key === "solo"; });
  assert.ok(solo, "should have solo tag");
  assert.equal(solo.label, "Easy to go solo");
  var first = tags.find(function (t) { return t.key === "firstTime"; });
  assert.equal(first.label, "Good for a first visit");
});

test("each tag has key, label, and reason strings", () => {
  var tags = buildNightDecisionTags(fullClubItem, "zh");
  assert.ok(tags.length > 0, "should have some tags");
  tags.forEach(function (tag) {
    assert.equal(typeof tag.key, "string", "key must be string");
    assert.ok(tag.key.length > 0, "key must not be empty");
    assert.equal(typeof tag.label, "string", "label must be string");
    assert.ok(tag.label.length > 0, "label must not be empty");
    assert.equal(typeof tag.reason, "string", "reason must be string");
    assert.ok(tag.reason.length > 0, "reason must not be empty");
  });
});
