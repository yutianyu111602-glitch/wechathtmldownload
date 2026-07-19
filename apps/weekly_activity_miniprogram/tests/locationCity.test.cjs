const assert = require("node:assert/strict");
const test = require("node:test");
const { nearestCityKey } = require("../utils/locationCity");
const { translateCity } = require("../utils/i18n");

test("chengdu center → chengdu", () => {
  assert.equal(nearestCityKey(30.572, 104.066), "chengdu");
});

test("beijing center → beijing", () => {
  assert.equal(nearestCityKey(39.909, 116.397), "beijing");
});

test("shanghai center → shanghai (not suzhou ~85km away)", () => {
  assert.equal(nearestCityKey(31.228, 121.474), "shanghai");
});

test("suzhou center → suzhou (not shanghai)", () => {
  assert.equal(nearestCityKey(31.299, 120.585), "suzhou");
});

test("foshan center → foshan (not guangzhou ~18km away)", () => {
  assert.equal(nearestCityKey(23.027, 113.122), "foshan");
});

test("guangzhou center → guangzhou (not foshan)", () => {
  assert.equal(nearestCityKey(23.129, 113.264), "guangzhou");
});

test("coords >80km from any city → empty string", () => {
  // middle of Pacific, far from everything
  assert.equal(nearestCityKey(0, 0), "");
});

test("invalid inputs → empty string", () => {
  assert.equal(nearestCityKey(null, null), "");
  assert.equal(nearestCityKey("35", "110"), "");
  assert.equal(nearestCityKey(undefined, undefined), "");
});

test("deterministic: same input twice → same output", () => {
  assert.equal(nearestCityKey(30.572, 104.066), nearestCityKey(30.572, 104.066));
});

// Cities that had activities but were missing from the location list (2026-07-01):
// their local feeds must now boost, and the "◉ X 优先" chip needs a zh label.
test("activity cities added 2026-07-01 resolve and have zh labels", () => {
  const cases = [
    [45.803, 126.534, "harbin", "哈尔滨"],
    [43.817, 125.324, "changchun", "长春"],
    [38.914, 121.615, "dalian", "大连"],
    [46.589, 125.104, "daqing", "大庆"],
    [40.842, 111.750, "hohhot", "呼和浩特"],
    [36.061, 103.834, "lanzhou", "兰州"],
    [22.817, 108.366, "nanning", "南宁"],
    [43.825, 87.617, "urumqi", "乌鲁木齐"],
  ];
  for (const [lat, lng, key, zh] of cases) {
    assert.equal(nearestCityKey(lat, lng), key, `${key} center should resolve to ${key}`);
    assert.equal(translateCity("", "zh", key), zh, `${key} needs zh label for the boost chip`);
  }
});
