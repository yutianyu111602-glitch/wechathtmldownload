const assert = require("node:assert/strict");
const test = require("node:test");
const { normalizeCityName, cityFootprint } = require("../utils/cityFootprint");

test("normalizeCityName drops placeholders, merges 市/省 suffix and English aliases", () => {
  assert.equal(normalizeCityName("未知"), "");
  assert.equal(normalizeCityName("online"), "");
  assert.equal(normalizeCityName(""), "");
  assert.equal(normalizeCityName("成都市"), "成都");
  assert.equal(normalizeCityName("四川省"), "四川");
  assert.equal(normalizeCityName("Beijing"), "北京");
  assert.equal(normalizeCityName(" SHANGHAI "), "上海");
  assert.equal(normalizeCityName("Hong Kong"), "香港");
  assert.equal(normalizeCityName("成都"), "成都"); // already canonical, untouched
  assert.equal(normalizeCityName("柏林"), "柏林"); // non-aliased city passes through
});

test("cityFootprint aggregates, merges variants, and sorts by event count desc", () => {
  const fp = cityFootprint([
    { city: "Beijing", date: "2025-01-01" },
    { city: "北京", date: "2025-03-01" },
    { city: "北京市", date: "2025-02-01" },
    { city: "成都", date: "2025-04-01" },
    { city: "未知", date: "2025-05-01" },
    { city: "", date: "2025-06-01" },
  ]);
  // Beijing + 北京 + 北京市 all merge -> 北京 = 3; 成都 = 1; placeholders dropped.
  assert.deepEqual(fp.order, ["北京", "成都"]);
  assert.equal(fp.counts["北京"], 3);
  assert.equal(fp.counts["成都"], 1);
  // Date range tracked across the merged bucket.
  assert.equal(fp.ranges["北京"].first, "2025-01-01");
  assert.equal(fp.ranges["北京"].last, "2025-03-01");
});
