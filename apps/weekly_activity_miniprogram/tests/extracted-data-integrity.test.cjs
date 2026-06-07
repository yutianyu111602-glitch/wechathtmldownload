const assert = require("node:assert/strict");
const test = require("node:test");

test("extracted addressBook preserves original entries", () => {
  const { VERIFIED_ADDRESS_BOOK } = require("../utils/addressBook");
  assert.ok(Array.isArray(VERIFIED_ADDRESS_BOOK), "addressBook must be an array");
  assert.ok(VERIFIED_ADDRESS_BOOK.length >= 3, `expected >= 3 entries, got ${VERIFIED_ADDRESS_BOOK.length}`);
  for (const entry of VERIFIED_ADDRESS_BOOK) {
    assert.ok(Array.isArray(entry.keys), `entry must have keys array`);
    assert.ok(entry.keys.length > 0, `entry must have at least one key`);
    assert.ok(typeof entry.address === "string" && entry.address.length > 0, `entry must have non-empty address`);
  }
});

test("extracted mapLocationBook preserves original entries", () => {
  const { VERIFIED_MAP_LOCATION_BOOK } = require("../utils/mapLocationBook");
  assert.ok(Array.isArray(VERIFIED_MAP_LOCATION_BOOK), "mapLocationBook must be an array");
  assert.ok(VERIFIED_MAP_LOCATION_BOOK.length >= 100, `expected >= 100 entries, got ${VERIFIED_MAP_LOCATION_BOOK.length}`);
  for (const entry of VERIFIED_MAP_LOCATION_BOOK) {
    assert.ok(Array.isArray(entry.keys), `entry must have keys array`);
    assert.ok(entry.keys.length > 0, `entry must have at least one key`);
    assert.ok(Number.isFinite(entry.latitude) && Math.abs(entry.latitude) <= 90, `invalid latitude in ${entry.name}`);
    assert.ok(Number.isFinite(entry.longitude) && Math.abs(entry.longitude) <= 180, `invalid longitude in ${entry.name}`);
    assert.ok(typeof entry.name === "string" && entry.name.length > 0, `entry must have non-empty name`);
  }
});

test("extracted styleRules preserves original entries", () => {
  const { STYLE_RULES, NON_ARTIST_LINEUP_NAMES, TRUSTED_TIME_SOURCES } = require("../utils/styleRules");
  assert.ok(Array.isArray(STYLE_RULES), "STYLE_RULES must be an array");
  assert.ok(STYLE_RULES.length >= 20, `expected >= 20 style rules, got ${STYLE_RULES.length}`);
  for (const rule of STYLE_RULES) {
    assert.ok(typeof rule.label === "string" && rule.label.length > 0, "rule must have label");
    assert.ok(Array.isArray(rule.aliases) && rule.aliases.length > 0, `rule ${rule.label} must have aliases`);
  }
  assert.ok(NON_ARTIST_LINEUP_NAMES.length >= 5, `expected >= 5 non-artist names, got ${NON_ARTIST_LINEUP_NAMES.length}`);
  assert.ok(TRUSTED_TIME_SOURCES.length >= 4, `expected >= 4 trusted time sources, got ${TRUSTED_TIME_SOURCES.length}`);
});

test("extracted offlineSnapshot preserves original entries", () => {
  const { OFFLINE_SNAPSHOT, OFFLINE_SOURCE_URLS } = require("../utils/offlineSnapshot");
  assert.ok(OFFLINE_SNAPSHOT && typeof OFFLINE_SNAPSHOT === "object", "OFFLINE_SNAPSHOT must be an object");
  assert.ok(Array.isArray(OFFLINE_SNAPSHOT.cities), "cities must be an array");
  assert.ok(OFFLINE_SNAPSHOT.cities.length >= 10, `expected >= 10 cities, got ${OFFLINE_SNAPSHOT.cities.length}`);
  assert.ok(Array.isArray(OFFLINE_SNAPSHOT.dates), "dates must be an array");
  assert.ok(OFFLINE_SNAPSHOT.dates.length >= 5, `expected >= 5 dates, got ${OFFLINE_SNAPSHOT.dates.length}`);
  assert.ok(Array.isArray(OFFLINE_SNAPSHOT.items), "items must be an array");
  assert.ok(OFFLINE_SNAPSHOT.items.length >= 30, `expected >= 30 items, got ${OFFLINE_SNAPSHOT.items.length}`);
  assert.ok(OFFLINE_SOURCE_URLS && typeof OFFLINE_SOURCE_URLS === "object", "OFFLINE_SOURCE_URLS must be an object");
  assert.ok(Object.keys(OFFLINE_SOURCE_URLS).length >= 3, `expected >= 3 source URLs, got ${Object.keys(OFFLINE_SOURCE_URLS).length}`);
});
