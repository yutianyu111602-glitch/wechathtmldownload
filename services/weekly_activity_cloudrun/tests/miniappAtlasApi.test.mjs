import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

test("miniapp Atlas API exposes source refs for artist and venue history", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "miniapp-atlas-api-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const payload = {
    v: 4,
    subjects: [
      { i: "dj:a", t: "dj", n: "DJ A", nn: "dja", a: [], c: "上海", ec: 1 },
      { i: "venue:club", t: "venue", n: "Club A", nn: "cluba", a: [], c: "上海", ec: 1 },
    ],
    profiles: {
      "dj:a": { n: "DJ A", c: "上海", ec: 1, vc: 1, cc: 1 },
    },
    events: {
      "dj:a": [{ eid: "event:a", t: "Archive Night", d: "2025-12-20", v: "Club A", vi: "venue:club", ci: "上海", sr: "src:a" }],
    },
    dj_venues: {
      "dj:a": [{ vn: "Club A", ec: 1, vi: "venue:club" }],
    },
    collabs: {
      "dj:a": [{ di: "dj:b", n: "DJ B", ec: 3 }],
    },
    venue_events: {
      "venue:club": [
        { eid: "event:a", t: "Archive Night", d: "2025-12-20", di: "dj:a", ci: "上海", sr: "src:a" },
        { eid: "event:b", t: "Deep Archive", d: "2024-12-20", di: "dj:b", ci: "上海", sr: "activity_src:b" },
      ],
    },
    venue_by_name: {
      cluba: ["venue:club"],
    },
    source_refs: {
      "src:a": { h: "hash-a", a: "Club A", t: "Club A archive post", p: "2025-12-01", k: "queue_token_account_title_exact" },
      "activity_src:b": { h: "hash-b", a: "Club A", t: "Club A activity sidecar", p: "2024-12-01", k: "atlas_activity_sidecar" },
    },
  };
  await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify(payload), "utf8")));
  process.env.ATLAS_MINIAPP_INDEX = indexPath;

  const moduleUrl = new URL(`../src/miniappAtlasApi.mjs?case=${Date.now()}`, import.meta.url);
  const { getArtist, getVenue, getSourceEvidence } = await import(moduleUrl.href);
  const artist = await getArtist({ name: "DJ A" });
  const venue = await getVenue({ name: "Club A", eventLimit: 1 });
  const evidence = await getSourceEvidence("src:a");
  const activityEvidence = await getSourceEvidence("activity_src:b");

  assert.equal(artist.events[0].sourceRefId, "src:a");
  assert.equal(artist.events[0].sourceHash, "hash-a");
  assert.equal(artist.events[0].sourceTitle, "Club A archive post");
  assert.equal(artist.venues.length, 1);
  assert.equal(artist.venues[0].venueName, "Club A");
  assert.equal(artist.collaborators.length, 1);
  assert.equal(artist.collaborators[0].sameEventCount, 3);
  assert.equal(venue.events.length, 1);
  assert.equal(venue.events[0].sourceRefId, "src:a");
  assert.equal(venue.events[0].sourceHash, "hash-a");
  assert.equal(venue.residentDJs.length, 2);
  assert.equal(venue.residentDJs.some((dj) => dj.djId === "dj:b"), true);
  assert.equal(venue.events[0].sourceAccountName, "Club A");
  assert.equal(evidence.schemaVersion, "atlas.evidence.v1");
  assert.equal(evidence.sourceTitle, "Club A archive post");
  assert.equal(activityEvidence.sourceTitle, "Club A activity sidecar");
  assert.equal(evidence.safety.rawSourceUrlExposed, false);
});
