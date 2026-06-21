const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function pageNameFromPath(pagePath) {
  const parts = pagePath.split("/");
  return parts[parts.length - 1];
}

function lineNumberAt(source, index) {
  return source.slice(0, index).split(/\r?\n/).length;
}

function staticHandlersFromWxml(wxml) {
  const handlers = [];
  const re = /\b(?:bind|catch)[\w:-]+\s*=\s*"([^"]+)"/g;
  let match;
  while ((match = re.exec(wxml))) {
    const handler = match[1].trim();
    if (!handler || handler.includes("{{")) continue;
    handlers.push({ handler, line: lineNumberAt(wxml, match.index) });
  }
  return handlers;
}

function scriptDefinesHandler(script, handler) {
  return new RegExp(`\\b${escapeRegExp(handler)}\\b`).test(script);
}

test("all mini-program WXML event handlers resolve to page methods", () => {
  const appJson = JSON.parse(read("app.json"));
  const failures = [];

  for (const pagePath of appJson.pages) {
    const page = pageNameFromPath(pagePath);
    const wxmlPath = `${pagePath}.wxml`;
    const jsPath = `${pagePath}.js`;
    const wxml = read(wxmlPath);
    const script = read(jsPath);
    const handlers = staticHandlersFromWxml(wxml);

    assert.notEqual(handlers.length, 0, `${pagePath} should expose at least one static event handler`);

    for (const { handler, line } of handlers) {
      if (!scriptDefinesHandler(script, handler)) {
        failures.push(`${wxmlPath}:${line} -> ${handler} missing in ${jsPath}`);
      }
    }
  }

  assert.deepEqual(failures, []);
});

test("home poster images expose load and error counters for rendered proof", () => {
  const wxml = read("pages/index/index.wxml");
  const script = read("pages/index/index.js");

  assert.match(wxml, /class="event-poster"[\s\S]*bindload="onPosterImageLoad"/);
  assert.match(wxml, /class="event-poster"[\s\S]*binderror="onPosterImageError"/);
  assert.doesNotMatch(wxml, /<image\s+lazy-load[^>]*class="event-poster"/);
  assert.match(wxml, /data-src="\{\{item\.coverUrl\}\}"/);
  assert.match(script, /posterImageLoadCount:\s*0/);
  assert.match(script, /posterImageErrorCount:\s*0/);
  assert.match(script, /\bonPosterImageLoad\s*\(/);
  assert.match(script, /\bonPosterImageError\s*\(/);
  assert.match(script, /\bwarmPosterImages\s*\(/);
  assert.match(script, /retryResolvePosters/);
  assert.match(script, /mergeResolvedPopularItems/);
  assert.match(script, /wx\.getImageInfo/);
});

test("artist and venue pages use stable event dedupe keys", () => {
  const artist = read("pages/artist/artist.js");
  const venue = read("pages/venue/venue.js");

  assert.match(artist, /function eventDedupeKey/);
  assert.match(artist, /atlasEventKeys/);
  assert.match(venue, /function eventDedupeKey/);
  assert.match(venue, /dedupeEvents\(\[\.\.\.events, \.\.\.filteredAtlas\]\)/);
});

test("home projected list items keep city identity for filter proof", () => {
  const script = read("pages/index/index.js");

  assert.match(script, /city_key: item\.city_key \|\| ""/);
  assert.match(script, /city_keys: Array\.isArray\(item\.city_keys\) \? item\.city_keys : \(item\.city_key \? \[item\.city_key\] : \[\]\)/);
});

test("home filter handlers reload with explicit selected filter state", () => {
  const script = read("pages/index/index.js");

  assert.match(script, /const selectedCityKey = opts\.cityKey !== undefined \? opts\.cityKey : this\.data\.selectedCity/);
  assert.match(script, /const selectedDateKey = opts\.date !== undefined \? opts\.date : this\.data\.selectedDate/);
  assert.match(script, /this\.fetchAllCurrentItems\(labels, \{ cityKey: "", date: "", lookbackDays: 0, loadSeq \}\)/);
  assert.match(script, /filterItemsByActiveFilters\(filterSourceItems, resolvedCityKey, resolvedDateKey\)/);
  assert.match(script, /selectedCity: resolvedCityKey/);
  assert.match(script, /selectedDate: resolvedDateKey/);

  assert.match(script, /chooseDraftCity\(event\) \{[\s\S]*?selectedDate: ""[\s\S]*?this\.loadData\(\{ haptic: true, cityKey: key, date: "" \}\);/);
  assert.match(script, /chooseDraftDate\(event\) \{[\s\S]*?this\.loadData\(\{ haptic: true, date: key \}\);/);
  assert.match(script, /resetLocation\(\) \{[\s\S]*?this\.loadData\(\{ haptic: true, cityKey: "" \}\);/);
  assert.match(script, /resetDate\(\) \{[\s\S]*?this\.loadData\(\{ haptic: true, date: "" \}\);/);
  assert.match(script, /applyLocation\(\) \{[\s\S]*?selectedDate: ""[\s\S]*?this\.loadData\(\{ haptic: true, cityKey: key, date: "" \}\);/);
});

test("home first load does not wait on slow filter metadata before rendering events", () => {
  const script = read("pages/index/index.js");

  assert.match(script, /FILTER_META_TIMEOUT_MS\s*=\s*\d+/);
  assert.match(script, /withFilterMetaTimeout\(requestApi\("\/api\/v1\/weekly\/cities"\)/);
  assert.match(script, /withFilterMetaTimeout\(requestApi\("\/api\/v1\/weekly\/dates"\)/);
  assert.match(script, /buildCityFiltersFallback\(cityFilterSourceItems/);
  assert.match(script, /dateIndexKeys = datesResult\.status === "fulfilled" \? dateKeySetFromIndex\(datesResult\.value\) : null/);
  assert.match(script, /buildDateFiltersFallback\(dateFilterSourceItems, lang, this\.data\.t\.allDates, dateIndexKeys\)/);
});

test("home date filters are derived from local activity bounds clamped by API date index", () => {
  const script = read("pages/index/index.js");

  assert.match(script, /itemDateBounds/);
  assert.match(script, /dateKeysForFilter/);
  assert.match(script, /function dateKeySetFromIndex\(payload\)/);
  assert.match(script, /if \(allowedKeys && !allowedKeys\.has\(key\)\) continue/);
  assert.match(script, /dateFilterSourceItems = resolvedCityKey/);
  assert.match(script, /resolvedDateKey = selectedDate\.key \? selectedDateKey : ""/);
});
