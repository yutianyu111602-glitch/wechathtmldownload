const { test } = require("node:test");
const assert = require("node:assert");
const {
  mergeVenues,
  mergeCollaborators,
  mergeResidentDjs,
  eventStartISO,
  partitionEventsByDate,
} = require("../utils/atlasContract");

test("mergeVenues collapses orthographic name variants and sums counts", () => {
  // Generic normalisation merges case/spacing/punct and English club/bar suffixes
  // (Dada Beijing == Dada Bar Beijing, OIL == OIL CLUB). Cross-language aliases
  // (OIL vs OIL油) are left to the atlas rebuild — see the contract doc.
  const merged = mergeVenues([
    { venueName: "Dada Beijing", eventCount: 335 },
    { venueName: "Dada Bar Beijing", eventCount: 148 },
    { venueName: "OIL", eventCount: 9 },
    { venueName: "OIL CLUB", eventCount: 2 },
    { venueName: "WITH BAR", eventCount: 23 },
  ]);
  assert.equal(merged.length, 3); // Dada, OIL, WITH BAR
  assert.equal(merged.find((v) => /dada/i.test(v.venueName)).eventCount, 483);
  assert.equal(merged.find((v) => /oil/i.test(v.venueName)).eventCount, 11);
  assert.ok(merged[0].eventCount >= merged[1].eventCount); // sorted desc
});

test("mergeVenues accepts raw index short keys {vn,ec}", () => {
  const merged = mergeVenues([
    { vn: "ZhaoDai", ec: 70 },
    { vn: "ZHAO DAI", ec: 7 },
    { vn: "zhaodai club", ec: 2 },
  ]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].eventCount, 79);
});

test("mergeCollaborators collapses case/spacing identity variants", () => {
  const merged = mergeCollaborators([
    { displayName: "MOON", sameEventCount: 134 },
    { displayName: "moon", sameEventCount: 10 },
    { displayName: "Moon", sameEventCount: 6 },
    { displayName: "LIst", sameEventCount: 20 },
    { displayName: "LIst", sameEventCount: 19 },
  ]);
  assert.equal(merged.length, 2);
  assert.equal(merged.find((c) => /moon/i.test(c.displayName)).sameEventCount, 150);
  assert.equal(merged.find((c) => /list/i.test(c.displayName)).sameEventCount, 39);
});

test("mergeResidentDjs preserves the eventCount field name", () => {
  const merged = mergeResidentDjs([
    { displayName: "badbadbad", eventCount: 268 },
    { displayName: "BadBadBad", eventCount: 2 },
  ]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].eventCount, 270);
});

test("eventStartISO reads multiple date shapes", () => {
  assert.equal(eventStartISO({ eventDateStart: "2026-06-27" }), "2026-06-27");
  assert.equal(eventStartISO({ event_date_start: "2026-06-27" }), "2026-06-27");
  assert.equal(eventStartISO({ date: "2026-06-27 23:00" }), "2026-06-27");
  assert.equal(eventStartISO({ dateLabel: "soon" }), "");
});

test("partitionEventsByDate splits upcoming/past, drops absurd-future and undated into past", () => {
  const events = [
    { id: "a", eventDateStart: "2026-06-27" }, // upcoming
    { id: "b", eventDateStart: "2026-06-20" }, // today => upcoming
    { id: "c", eventDateStart: "2026-06-10" }, // past
    { id: "d", eventDateStart: "2046-12-25" }, // garbage far-future => past
    { id: "e", eventDateStart: "" },           // undated => past
  ];
  const { upcoming, past } = partitionEventsByDate(events, { todayISO: "2026-06-20" });
  assert.deepEqual(upcoming.map((e) => e.id), ["b", "a"]); // ascending
  assert.deepEqual(past.map((e) => e.id).sort(), ["c", "d", "e"]);
});
