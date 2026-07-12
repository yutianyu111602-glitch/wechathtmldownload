const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appJs = fs.readFileSync(path.resolve(__dirname, "../app.js"), "utf8");
const apiJs = fs.readFileSync(path.resolve(__dirname, "../utils/api.js"), "utf8");
const cacheJs = fs.readFileSync(path.resolve(__dirname, "../utils/api/cache.js"), "utf8");
const currentReleaseDir = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/current_release");

function numericConfig(name) {
  const match = appJs.match(new RegExp(`${name}:\\s*(-?\\d+)`));
  assert.ok(match, `missing ${name}`);
  return Number(match[1]);
}

function itemDate(item) {
  return item.event_date_start || item.eventDateStart || item.event_date || item.eventDate || item.date || item.event_date_iso_guess || "";
}

function eventEndDate(item) {
  return item.event_date_end || item.eventDateEnd || item.event_date_start || item.eventDateStart || item.event_date || item.eventDate || item.date || "";
}

function stringValue(item, key) {
  return String((item && item[key]) || "").trim();
}

function isAggregateChild(item) {
  return Boolean(item && item.aggregation_child === true)
    || String((item && (item.id || item.event_id)) || "").startsWith("agg-child-");
}

test("production config keeps offline fallback without letting snapshots race the current feed", () => {
  const publicFallbackDelayMs = numericConfig("publicFallbackDelayMs");
  const publicRequestTimeoutMs = numericConfig("publicRequestTimeoutMs");
  const cacheFallbackDelayMs = numericConfig("cacheFallbackDelayMs");
  const offlineSnapshotFallbackDelayMs = numericConfig("offlineSnapshotFallbackDelayMs");

  assert.match(appJs, /offlineSnapshotFallback:\s*true/);
  assert.match(appJs, /fastOfflineSnapshotFallback:\s*false/);
  assert.ok(offlineSnapshotFallbackDelayMs < 0, "snapshot delay must stay disabled for the online current feed");
  assert.ok(publicRequestTimeoutMs >= 3000, "public request timeout must leave room for normal mobile latency");
  assert.ok(
    cacheFallbackDelayMs > publicFallbackDelayMs,
    "cache fallback must wait until the public API path has had a chance to return",
  );
  assert.match(cacheJs, /weeklyActivityApiCache:v20260704:/);
});

test("current release package uses its published data window with CloudBase poster file IDs", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(currentReleaseDir, "manifest.json"), "utf8"));
  const current = JSON.parse(fs.readFileSync(path.join(currentReleaseDir, "current.json"), "utf8"));
  const items = Array.isArray(current) ? current : current.items || current.events || [];
  const itemIds = new Set(items.map((item) => String(item.id || item.event_id || "")));
  const dates = items.map(itemDate).filter(Boolean).sort();
  const forbiddenDates = new Set(["2026-05-29", "2026-06-18", "2026-06-27"]);
  const outsideWindowItems = items.filter((item) => {
    const start = itemDate(item);
    const end = eventEndDate(item);
    return end < manifest.window_start || start > manifest.window_end;
  });
  const coverKeys = ["coverUrl", "cover_url", "coverImageUrl", "cover_image_url", "poster", "posterUrl", "poster_url", "raw_cover_url"];
  const fileIdKeys = ["poster_file_id", "posterFileId", "cloudFileId", "cloud_file_id", "cover_file_id", "coverFileId"];
  const posterStorageKeys = ["poster_storage", "posterStorage"];
  const runtimePosterStateKeys = [
    "posterTempUrl",
    "poster_temp_url",
    "tempFileURL",
    "tempFileUrl",
    "temp_file_url",
    "posterDownloadFallbackTried",
    "posterFileIdFallbackTried",
    "posterLoadFailed",
  ];
  const aggregateChildren = items.filter(isAggregateChild);
  const nonAggregateItems = items.filter((item) => !isAggregateChild(item));
  const nonAggregateItemsWithCloudFileId = nonAggregateItems.filter((item) => (
    fileIdKeys.some((key) => /^cloud:\/\/[^/]+\/weekly-posters\/\d{8}\//i.test(stringValue(item, key)))
  ));
  const nonAggregateQpicFallbackItems = nonAggregateItems.filter((item) => (
    !nonAggregateItemsWithCloudFileId.includes(item)
    && coverKeys.some((key) => /^https:\/\/(?:mmbiz|mmecoa)\.qpic\.cn\//i.test(stringValue(item, key)))
  ));
  const itemsWithCloudbaseStorage = items.filter((item) => (
    posterStorageKeys.some((key) => /^cloudbase$/i.test(stringValue(item, key)))
  ));
  const publicPosterItems = items.filter((item) => (
    [...coverKeys, ...fileIdKeys].some((key) => /(?:mmbiz|mmecoa)\.qpic\.cn|mp\.weixin\.qq\.com|https?:\/\/|\/api\/v1\/weekly\/poster\/|wxfile:\/\/|blob:/i.test(stringValue(item, key)))
  ));
  const runtimePosterStateItems = items.filter((item) => (
    runtimePosterStateKeys.some((key) => Object.prototype.hasOwnProperty.call(item, key))
  ));
  const aggregateSourceResidue = aggregateChildren.filter((item) => {
    const sourceAction = item.source_action && typeof item.source_action === "object" ? item.source_action : {};
    const sourceArticle = item.source_article && typeof item.source_article === "object" ? item.source_article : {};
    return sourceAction.available === true
      || stringValue(sourceAction, "url_hash")
      || stringValue(sourceArticle, "url_hash")
      || stringValue(item, "sourceHash")
      || stringValue(item, "source_hash");
  });

  assert.ok(Date.parse(manifest.generated_at) >= Date.parse("2026-06-02T19:14:20+08:00"));
  assert.equal(manifest.window_start, "2026-06-02");
  assert.equal(manifest.window_end, "2026-06-25");
  assert.ok(manifest.item_count >= 155, `expected >= 155 items, got ${manifest.item_count}`);
  assert.equal(items.length, manifest.item_count);
  assert.ok(dates.includes(manifest.window_start));
  assert.equal([...forbiddenDates].some((date) => dates.includes(date)), false);
  assert.equal(itemIds.has("loopy_club:2eee2bb226cf7550"), false);
  assert.equal(itemIds.has("abyss_shanghai:ce6995b838e0fa6a"), false);
  assert.equal(itemIds.has("with_bar:9295cbeb1714fba5"), false);
  assert.equal(itemIds.has("agg-child-9b66fa225a0606d8"), false);
  assert.equal(itemIds.has("agg-child-4031b3921f885e8e"), false);
  assert.equal(itemIds.has("agg-child-13e3c9e711931629"), false);
  assert.equal(items.some((item) => /dj\s*love/i.test(String(item.title || item.title_display || ""))), false);
  assert.equal(outsideWindowItems.length, 0);
  assert.equal(aggregateChildren.length, 11);
  assert.equal(aggregateSourceResidue.length, 0);
  assert.ok(
    nonAggregateItemsWithCloudFileId.length >= Math.ceil(nonAggregateItems.length * 0.9),
    `expected >=90% non-aggregate items with cloud file ID, got ${nonAggregateItemsWithCloudFileId.length}/${nonAggregateItems.length}`,
  );
  assert.equal(
    nonAggregateItemsWithCloudFileId.length + nonAggregateQpicFallbackItems.length,
    nonAggregateItems.length,
    "every non-aggregate poster must use a cloud file ID or a proxy-compatible qpic fallback",
  );
  assert.ok(nonAggregateQpicFallbackItems.length <= 15, `expected <=15 legacy qpic fallbacks, got ${nonAggregateQpicFallbackItems.length}`);
  assert.equal(itemsWithCloudbaseStorage.length, items.length);
  assert.equal(publicPosterItems.length, nonAggregateQpicFallbackItems.length);
  assert.equal(runtimePosterStateItems.length, 0);
});
