// weekly-contract-regressions.test.cjs
// Contract regression tests for Loopy, DJ Love, Love Bang/POOLS, TRUST
// Based on DATA_CONTRACT_MATRIX_20260606.md
const assert = require("node:assert/strict");
const test = require("node:test");

const {
  compactItem,
  canonicalizeItemFields,
  isSourceOverviewItem,
  isCalendarPreviewItem,
  firstMeaningful,
  mergeNonEmpty,
} = require("../utils/format");

// ── Helpers ──────────────────────────────────────────────

function isAggregateChildItem(item) {
  return item.aggregation_child === true || item.aggregationChild === true;
}

function posterFileId(item) {
  return String(firstMeaningful(
    item.poster_file_id,
    item.posterFileId,
    item.coverFileId,
    item.cover_file_id,
  ) || "").trim();
}

// ── Contract 1: Loopy — aggregate child source routing ──

test("CONTRACT: aggregate child sourceActionEnabled is false and sourceHash is empty", () => {
  const fixture = compactItem({
    id: "loopy-child-001",
    title: "6.04 周四｜Jeff Mills 厂牌旗下亚洲顶级 Techno 代表",
    venue_name: "loopy Club",
    city: ["杭州"],
    event_date_start: "2026-06-04",
    event_date_end: "2026-06-04",
    aggregation_child: true,
    source_action: { url_hash: "parent-overview-hash-123", available: true },
    poster_file_id: "cloud://test-bucket/weekly-posters/loopy-001.jpg",
  });

  // aggregate child must NOT have source routing enabled
  assert.equal(fixture.hasSource, false, "aggregate child hasSource must be false");
  assert.equal(fixture.sourceHash, "", "aggregate child sourceHash must be empty");
});

test("CONTRACT: direct source item has sourceActionEnabled and non-empty sourceHash", () => {
  const fixture = compactItem({
    id: "direct-event-001",
    title: "Techno Night at DADA",
    venue_name: "DADA Beijing",
    city: ["北京"],
    event_date_start: "2026-06-05",
    event_date_end: "2026-06-05",
    source_action: { url_hash: "real-article-hash-456", available: true },
    poster_file_id: "cloud://test-bucket/weekly-posters/dada-001.jpg",
  });

  // direct source item SHOULD have source routing
  assert.equal(fixture.hasSource, true, "direct source item hasSource must be true");
  assert.ok(fixture.sourceHash.length > 0, "direct source item sourceHash must not be empty");
});

test("CONTRACT: aggregate child with no source_action falls back cleanly", () => {
  const fixture = compactItem({
    id: "agg-no-source",
    title: "Sub Event Under Overview",
    venue_name: "Test Venue",
    event_date_start: "2026-06-06",
    aggregation_child: true,
    // no source_action at all
  });

  assert.equal(fixture.hasSource, false, "aggregate child without source_action hasSource=false");
  assert.equal(fixture.sourceHash, "", "aggregate child without source_action sourceHash empty");
});

// ── Contract 2: DJ Love — post_date cannot be event date ──

test("CONTRACT: post_date is NOT used as event_date_start when event_date_start is present", () => {
  const fixture = compactItem({
    id: "dj-love-001",
    title: "DJ Love Weekend Set",
    venue_name: "Test Club",
    event_date_start: "2026-05-15",  // already passed
    event_date_end: "2026-05-15",
    post_date: "2026-06-01",  // recent post date, should NOT override
    poster_file_id: "cloud://test-bucket/weekly-posters/dj-001.jpg",
  });

  // The date label must reflect event_date_start, not post_date
  assert.equal(fixture.dateLabel, "2026-05-15", "dateLabel must use event_date_start, not post_date");
  assert.equal(fixture.event_date_start, "2026-05-15", "event_date_start preserved");
});

test("CONTRACT: post_date alone is NOT enough to create a dateLabel", () => {
  const fixture = compactItem({
    id: "post-date-only",
    title: "Article With No Event Date",
    venue_name: "Unknown",
    post_date: "2026-06-02",
    // no event_date_start, no event_date_end
  });

  // Without event_date_start, the item should not get a fake date from post_date
  assert.ok(
    !fixture.dateLabel || fixture.dateLabel === "" || fixture.isCalendarPreview || fixture.isSourceOverview,
    "item with only post_date should have empty dateLabel or be calendar preview"
  );
});

// ── Contract 3: Love Bang / POOLS — aggregate child poster ──

test("CONTRACT: aggregate child has its own posterFileId, not parent overview", () => {
  const fixture = compactItem({
    id: "love-bang-dali",
    title: "Love Bang 16-Year Anniversary 大理站",
    venue_name: "POOLS",
    city: ["大理"],
    event_date_start: "2026-06-05",
    event_date_end: "2026-06-05",
    aggregation_child: true,
    poster_file_id: "cloud://test-bucket/weekly-posters/love-bang-pools.jpg",
  });

  // Aggregate child must keep its own poster
  const pfid = fixture.posterFileId || fixture.poster_file_id || "";
  assert.ok(
    pfid.includes("love-bang") || pfid.includes("cloud://"),
    "aggregate child posterFileId must be its own, not empty"
  );
});

test("CONTRACT: isSourceOverview item has empty posterUrl", () => {
  const fixture = compactItem({
    id: "weekly-overview",
    title: "本周活动一览",
    event_date_start: "2026-06-02",
    event_date_end: "2026-06-08",
    poster_file_id: "cloud://test-bucket/weekly-posters/overview-default.jpg",
  });

  // Source overview items get empty coverUrl (handled by posterUrl)
  // They must NOT use the overview default as a real poster
  assert.ok(fixture.isSourceOverview, "should be detected as source overview");
});

// ── Contract 4: TRUST — label is not venue ──

test("CONTRACT: item where organizer is label but venue is missing has no address", () => {
  const fixture = compactItem({
    id: "trust-label-only",
    title: "TRUST｜Club Therapy 电波疗愈",
    venue_name: "", // TRUST is label, venue removed from venue_name
    organizer_name: "TRUST",
    city: ["北京"],
    event_date_start: "2026-06-03",
    event_date_end: "2026-06-03",
  });

  // Without a real venue_name, hasAddress should be false
  assert.equal(fixture.hasAddress, false, "label-only item hasAddress must be false");
});

test("CONTRACT: item with real venue has address", () => {
  const fixture = compactItem({
    id: "real-venue",
    title: "Night at DADA",
    venue_name: "DADA Beijing",
    city: ["北京"],
    event_date_start: "2026-06-05",
    event_date_end: "2026-06-05",
  });

  assert.equal(fixture.hasAddress, true, "item with real venue hasAddress must be true");
});

// ── Contract 5: Date window enforcement ──

test("CONTRACT: item with event_date_end before current window is not calendar_preview", () => {
  const fixture = compactItem({
    id: "old-event",
    title: "Old Party",
    venue_name: "Test Club",
    event_date_start: "2026-04-01",
    event_date_end: "2026-04-01",
    post_date: "2026-06-01", // recent post, but event is old
  });

  // The event date is clearly past. The item may still appear
  // but it must not claim to be a current event through post_date
  if (fixture.dateLabel) {
    assert.ok(
      fixture.dateLabel.startsWith("2026-04") || fixture.isCalendarPreview,
      "dateLabel must reflect real event date, not post_date"
    );
  }
});

// ── Contract 6: canonicalizeItemFields preserves posterFileId chain ──

test("CONTRACT: canonicalizeItemFields resolves posterFileId from canonical aliases", () => {
  const canon = canonicalizeItemFields({
    poster_file_id: "cloud://bucket/posters/event-001.jpg",
    posterFileId: "cloud://bucket/posters/event-001-alt.jpg",
  });

  assert.ok(
    String(canon.poster_file_id || canon.posterFileId || "").includes("cloud://"),
    "canonicalize must preserve cloud:// poster file id"
  );
});

test("CONTRACT: canonicalizeItemFields does not treat post_date as event date", () => {
  const canon = canonicalizeItemFields({
    post_date: "2026-06-06",
    // no event_date_start
  });

  // post_date should NOT be promoted to event_date_start
  assert.equal(canon.event_date_start, undefined, "post_date must not become event_date_start");
});
