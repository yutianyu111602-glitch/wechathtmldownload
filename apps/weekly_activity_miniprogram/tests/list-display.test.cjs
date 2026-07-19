const assert = require("node:assert/strict");
const test = require("node:test");

const { listLocationLabel, withListLocationLabels } = require("../utils/listDisplay");

test("all-city list keeps city label for non-Shanghai scanning", () => {
  const item = {
    cityLabel: "杭州",
    venueLabel: "loopy Club",
    cardLocationLabel: "杭州",
  };

  assert.equal(listLocationLabel(item, ""), "杭州 · loopy Club");
});

test("city-filtered list shows venue or club name under event title", () => {
  const item = {
    cityLabel: "杭州",
    venueLabel: "loopy Club",
    cardLocationLabel: "杭州",
  };

  assert.equal(listLocationLabel(item, "hangzhou"), "杭州 · loopy Club");
});

test("decorates list rows without mutating source items", () => {
  const source = [{ id: "evt-1", cityLabel: "杭州", venueLabel: "DONG", cardLocationLabel: "杭州" }];
  const decorated = withListLocationLabels(source, "hangzhou");

  assert.equal(decorated[0].listLocationLabel, "杭州 · DONG");
  assert.equal(source[0].listLocationLabel, undefined);
});

test("source overview rows do not receive city or venue fallback labels", () => {
  const item = {
    isSourceOverview: true,
    cityLabel: "杭州",
    venueLabel: "loopy Club",
    cardLocationLabel: "杭州",
  };

  assert.equal(listLocationLabel(item, ""), "");
  assert.equal(listLocationLabel(item, "hangzhou"), "");
});

test("home page source overview rows are rendered as calendar placeholders", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const root = path.resolve(__dirname, "..");
  const indexJs = fs.readFileSync(path.join(root, "pages", "index", "index.js"), "utf8");
  const indexWxml = fs.readFileSync(path.join(root, "pages", "index", "index.wxml"), "utf8");

  assert.match(indexJs, /filterItemsByPreviewRange/);
  assert.match(indexJs, /itemMatchesDateKey/);
  assert.match(indexWxml, /calendarPreviewLabel/);
  assert.match(indexWxml, /dateRangeCompact/);
});
