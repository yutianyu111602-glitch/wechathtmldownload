const assert = require("node:assert/strict");
const test = require("node:test");

const { buildLdDots, LOADING_MSGS } = require("../utils/atlasLoading.js");

test("buildLdDots returns exactly 12 dots", () => {
  assert.equal(buildLdDots().length, 12);
});

test("all dots have x/y within [0, 100] and delay >= 0", () => {
  buildLdDots().forEach(function (d, i) {
    assert.ok(d.x >= 0 && d.x <= 100, "dot " + i + " x out of range: " + d.x);
    assert.ok(d.y >= 0 && d.y <= 100, "dot " + i + " y out of range: " + d.y);
    assert.ok(d.d >= 0, "dot " + i + " delay negative");
    assert.ok(typeof d.c === "string" && d.c.startsWith("#"), "dot " + i + " color invalid");
  });
});

test("first dot is center at (50, 50) with lime colour", () => {
  const first = buildLdDots()[0];
  assert.equal(first.x, 50);
  assert.equal(first.y, 50);
  assert.equal(first.c, "#A7FF26");
  assert.equal(first.d, 0);
});

test("buildLdDots is deterministic — two calls are identical", () => {
  assert.deepEqual(buildLdDots(), buildLdDots());
});

test("each dot has a unique sequential i index", () => {
  const dots = buildLdDots();
  dots.forEach(function (d, i) {
    assert.equal(d.i, i);
  });
});

test("LOADING_MSGS has 4 non-empty strings", () => {
  assert.equal(LOADING_MSGS.length, 4);
  LOADING_MSGS.forEach(function (msg) {
    assert.ok(typeof msg === "string" && msg.length > 0);
  });
});
