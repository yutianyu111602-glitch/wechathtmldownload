import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

// Locks the global atlas search endpoint (entry to all subject types, ranked by event_count).
test("atlas search: all-type + type-filter, ranked by popularity", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "atlas-search-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const index = {
    v: 4,
    subjects: [
      { i: "dj:hot", t: "dj", n: "Mika", nn: "mika", a: ["MIKA"], c: "上海", ec: 900 },
      { i: "dj:cold", t: "dj", n: "Mika Mini", nn: "mika mini", a: [], c: "北京", ec: 5 },
      { i: "venue:m", t: "venue", n: "Mika Bar", nn: "mika bar", a: [], c: "成都", ec: 40 },
    ],
    profiles: {}, events: {}, dj_venues: {}, venue_events: {}, venue_by_name: {}, collabs: {}, source_refs: {},
  };
  await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify(index), "utf8")));
  process.env.ATLAS_MINIAPP_INDEX = indexPath;

  const { getSearch } = await import(new URL(`../src/miniappAtlasApi.mjs?case=${Date.now()}`, import.meta.url).href);

  const all = await getSearch({ q: "mika" });
  assert.equal(all.found, true);
  assert.ok(all.results.length >= 3, "matches all three");
  assert.equal(all.results[0].id, "dj:hot", "highest event_count ranked first");
  assert.deepEqual(all.results[0].aliases, ["MIKA"]);

  const venuesOnly = await getSearch({ q: "mika", type: "venue" });
  assert.equal(venuesOnly.results.length, 1, "type filter keeps only venues");
  assert.equal(venuesOnly.results[0].type, "venue");

  const none = await getSearch({ q: "zzzznomatch" });
  assert.equal(none.found, false);
  assert.equal(none.reason, "no_match");

  const blank = await getSearch({ q: "" });
  assert.equal(blank.reason, "missing_query");

  await rm(dir, { recursive: true, force: true });
});
