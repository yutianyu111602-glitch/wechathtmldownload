import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

const FETCH_BLOCKED_PORTS = new Set([
  1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79,
  87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137,
  139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532,
  540, 548, 554, 556, 563, 587, 601, 636, 989, 990, 993, 995, 1719, 1720,
  1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668,
  6669, 6697, 10080,
]);

async function listen(serverInstance) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise((resolve, reject) => {
      const onError = (error) => {
        serverInstance.off("listening", onListening);
        reject(error);
      };
      const onListening = () => {
        serverInstance.off("error", onError);
        resolve();
      };
      serverInstance.once("error", onError);
      serverInstance.once("listening", onListening);
      serverInstance.listen(0, "127.0.0.1");
    });
    const address = serverInstance.address();
    if (!FETCH_BLOCKED_PORTS.has(address.port)) {
      return `http://127.0.0.1:${address.port}`;
    }
    await new Promise((resolve) => serverInstance.close(resolve));
  }
  throw new Error("Could not allocate a fetch-compatible local test port");
}

test("miniapp Atlas HTTP routes return candidate-only DTO contracts", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "miniapp-atlas-api-http-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const lensesPath = path.join(dir, "atlas_starmap_lenses.json.gz");
  const relationTrajectoryPath = path.join(dir, "dj_relation_trajectory_lens.json.gz");
  const radioExternalLinksPath = path.join(dir, "radio_external_links_public_seed_candidate.json.gz");
  const radioProgramsPath = path.join(dir, "radio_programs_candidate.json.gz");
  const radioProgramReviewPath = path.join(dir, "radio_program_match_review.json");
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_STARMAP_LENSES: process.env.ATLAS_STARMAP_LENSES,
    ATLAS_DJ_RELATION_TRAJECTORY_LENS: process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS,
    ATLAS_RADIO_EXTERNAL_LINKS: process.env.ATLAS_RADIO_EXTERNAL_LINKS,
    ATLAS_RADIO_PROGRAMS: process.env.ATLAS_RADIO_PROGRAMS,
    ATLAS_RADIO_PROGRAM_MATCH_REVIEW: process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  let server;
  try {
    await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify({
      v: 4,
      subjects: [
        { i: "dj:a", t: "dj", n: "DJ A", nn: "dja", a: [], c: "Shanghai", ec: 1 },
      ],
      profiles: {
        "dj:a": {
          n: "DJ A", c: "Shanghai", ec: 1, vc: 1, cc: 0,
          s: JSON.stringify({ soundcloud: "https://soundcloud.example/dja" }),
          ba: JSON.stringify([{ t: "Source-backed bio.", sr: "src:a", lang: "en" }]),
          x: JSON.stringify([{ u: "https://soundcloud.com/dja", p: "soundcloud", r: "listen", sr: "src:a" }]),
        },
      },
      events: {
        "dj:a": [{ eid: "event:a", t: "Archive Night", d: "2026-06-22", v: "Club A", ci: "Shanghai", sr: "src:a" }],
      },
      dj_venues: { "dj:a": [{ vn: "Club A", ec: 1 }] },
      collabs: { "dj:a": [] },
      source_refs: {
        "src:a": { h: "hash-a", a: "Club A", t: "Club A archive post", p: "2026-06-22", k: "queue_token_account_title_exact" },
      },
      related_columns: {
        "dj:a": [{ id: "col:a", t: "DJ A column", sr: "src:a" }],
      },
    }), "utf8")));
    await writeFile(lensesPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.starmap.lenses.v1",
      generatedAt: "2026-06-22T00:00:00+0800",
      source: { candidateOnly: true, productionWriteExecuted: false },
      counts: { futureEvents: 1, subjects: 1 },
      lenses: {
        future: { events: [{ eventId: "event:f", title: "Future Night" }] },
        subject: { subjects: { "dj:a": { id: "dj:a", type: "dj", name: "DJ A" } } },
      },
    }), "utf8")));
    await writeFile(relationTrajectoryPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.dj_relation_trajectory.lens.v1",
      generatedAt: "2026-06-23T01:47:00+0800",
      source: { candidateOnly: true, productionWriteExecuted: false, v2: "candidate-v2.sqlite" },
      counts: { djs: 1, relations: 1, subjects: 2 },
      lenses: {
        dj: { items: [{ id: "dj:a", type: "dj", name: "DJ A", eventCount: 4 }] },
        relation: {
          relations: [{ srcDjId: "dj:a", dstDjId: "dj:b", sameEventCount: 3, label: "同台" }],
          collaborators: { "dj:a": [{ djId: "dj:b", name: "DJ B", sameEventCount: 3 }] },
        },
        trajectory: {
          venues: { "dj:a": [{ venueId: "venue:club", venueName: "Club A", eventCount: 2 }] },
          cities: { "dj:a": [{ city: "Shanghai", eventCount: 2 }] },
          events: { "dj:a": [{ eventId: "event:a", title: "Archive Night", sourceRefId: "src:a" }] },
        },
      },
    }), "utf8")));
    await writeFile(radioExternalLinksPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.radio_external_links.public_seed_candidate.v1",
      generatedAt: "2026-06-23T03:30:00+0800",
      candidateOnly: true,
      productionWriteExecuted: false,
      oldDatabaseRowsUsed: 0,
      source: { mode: "public_url_seed", usesOldDbData: false },
      hotlinkPolicy: {
        mediaEmbedded: false,
        assetDownloaded: false,
        assetCached: false,
        proxyCached: false,
        uiAction: "click_to_open_original_site",
      },
      counts: { stations: 1, links: 1, verifiedLinks: 1, blockedLinks: 0, oldDatabaseRowsUsed: 0 },
      stations: [
        {
          stationKey: "cdcr",
          stationName: "CDCR",
          links: [{ url: "https://space.bilibili.com/478422575/", platform: "bilibili", role: "radio", openMode: "external_original_site", noHotlink: true }],
        },
      ],
    }), "utf8")));
    await writeFile(radioProgramsPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.radio_programs.candidate.v1",
      generatedAt: "2026-06-23T04:30:00+0800",
      candidateOnly: true,
      productionWriteExecuted: false,
      oldDatabaseRowsUsed: 0,
      source: { mode: "public_station_program_candidate", usesOldDbData: false },
      hotlinkPolicy: {
        mediaEmbedded: false,
        assetDownloaded: false,
        assetCached: false,
        proxyCached: false,
        uiAction: "click_to_open_original_site",
      },
      counts: { stations: 1, programs: 3, matchedPrograms: 3, unmatchedPrograms: 0, djMatches: 3, matchedDjs: 1, oldDatabaseRowsUsed: 0 },
      programsByDjId: { "dj:a": ["radio_program:cdcr:a", "radio_program:cdcr:takeover", "radio_program:cdcr:alias"] },
      programs: [
        {
          programId: "radio_program:cdcr:a",
          stationKey: "cdcr",
          stationName: "CDCR",
          title: "DJ A radio session",
          url: "https://space.bilibili.com/478422575/channel/collectiondetail?sid=1",
          platform: "bilibili",
          sourceUrl: "https://space.bilibili.com/478422575/",
          openMode: "external_original_site",
          noHotlink: true,
          candidateOnly: true,
          djMatches: [{ djId: "dj:a", displayName: "DJ A", matchedText: "DJ A", confidence: 0.9, matchKind: "fixture" }],
        },
        {
          programId: "radio_program:cdcr:takeover",
          stationKey: "cdcr",
          stationName: "CDCR",
          title: "CDCR takeover",
          url: "https://space.bilibili.com/478422575/channel/collectiondetail?sid=2",
          platform: "bilibili",
          sourceUrl: "https://space.bilibili.com/478422575/",
          openMode: "external_original_site",
          noHotlink: true,
          candidateOnly: true,
          djMatches: [{ djId: "dj:a", displayName: "DJ A", matchedText: "Take Over", confidence: 0.76, matchKind: "normalized_substring" }],
        },
        {
          programId: "radio_program:cdcr:alias",
          stationKey: "cdcr",
          stationName: "CDCR",
          title: "DJ A alias session",
          url: "https://space.bilibili.com/478422575/channel/collectiondetail?sid=3",
          platform: "bilibili",
          sourceUrl: "https://space.bilibili.com/478422575/",
          openMode: "external_original_site",
          noHotlink: true,
          candidateOnly: true,
          djMatches: [{ djId: "dj:a", displayName: "DJ A", matchedText: "Alias A", confidence: 0.76, matchKind: "normalized_substring" }],
        },
      ],
    }), "utf8")));
    await writeFile(radioProgramReviewPath, JSON.stringify({
      schemaVersion: "atlas.radio_program_match_review.v1",
      generatedAt: "2026-06-24T02:08:00+0800",
      candidateOnly: true,
      productionWriteExecuted: false,
      counts: { flagged_match_rows: 2, decision_hard_hide: 1, decision_review_only: 1, decision_safe_display: 1 },
      rows: [
        {
          programId: "radio_program:cdcr:takeover",
          djId: "dj:a",
          displayName: "DJ A",
          matchedText: "Take Over",
          reasons: ["generic_term"],
          decision: "hard_hide",
        },
        {
          programId: "radio_program:cdcr:alias",
          djId: "dj:a",
          displayName: "DJ A",
          matchedText: "Alias A",
          reasons: ["alias_surface_mismatch"],
          decision: "review_only",
        },
      ],
    }), "utf8");

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = indexPath;
    process.env.ATLAS_STARMAP_LENSES = lensesPath;
    process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = relationTrajectoryPath;
    process.env.ATLAS_RADIO_EXTERNAL_LINKS = radioExternalLinksPath;
    process.env.ATLAS_RADIO_PROGRAMS = radioProgramsPath;
    process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = radioProgramReviewPath;
    process.env.CROSS_DB_MERGE_MAP = path.join(dir, "empty-merge-map.json");

    const { __resetMiniappAtlasApiCachesForTests } = await import("../src/miniappAtlasApi.mjs");
    __resetMiniappAtlasApiCachesForTests();
    const { createServer } = await import(`../src/server.mjs?case=${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);

    const artistRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/artist?name=DJ%20A&eventLimit=1`);
    assert.equal(artistRes.status, 200);
    const artist = await artistRes.json();
    assert.equal(artist.schemaVersion, "atlas_miniapp.artist_response.v1");
    assert.equal(artist.found, true);
    assert.equal(artist.profile.externalLinks[0].role, "listen");
    assert.equal(artist.profile.externalLinks[0].sourceTitle, "Club A archive post");
    assert.equal(Object.hasOwn(artist.profile.externalLinks[0], "sourceHash"), false);
    assert.equal(artist.profile.radioPrograms[0].programId, "radio_program:cdcr:a");
    assert.equal(artist.profile.radioPrograms[0].openMode, "external_original_site");
    assert.equal(artist.radioPrograms[0].noHotlink, true);
    assert.equal(artist.relationTrajectory.schemaVersion, "atlas_miniapp.artist_relation_trajectory.v1");
    assert.equal(artist.relationTrajectory.source.candidateOnly, true);
    assert.equal(artist.relationTrajectory.source.productionWriteExecuted, false);
    assert.equal(artist.relationTrajectory.collaborators[0].displayName, "DJ B");
    assert.equal(artist.relationTrajectory.venues[0].venueName, "Club A");
    assert.equal(artist.relationTrajectory.cities[0].city, "Shanghai");
    assert.equal(artist.profile.relationTrajectory.events[0].sourceRefId, "src:a");
    assert.equal(artist.bioAtoms[0].sourceRefId, "src:a");
    assert.equal(artist.relatedColumns[0].columnId, "col:a");
    assert.equal(artist.events[0].sourceHash, "hash-a");

    const lensRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/starmap/lens?name=subject&subjectId=dj%3Aa`);
    assert.equal(lensRes.status, 200);
    const lens = await lensRes.json();
    assert.equal(lens.schemaVersion, "atlas_miniapp.starmap_lens_response.v1");
    assert.equal(lens.found, true);
    assert.equal(lens.source.candidateOnly, true);
    assert.equal(lens.source.productionWriteExecuted, false);
    assert.equal(lens.data.name, "DJ A");

    const relationLensRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/starmap/lens?name=relationTrajectory`);
    assert.equal(relationLensRes.status, 200);
    const relationLens = await relationLensRes.json();
    assert.equal(relationLens.schemaVersion, "atlas_miniapp.starmap_lens_response.v1");
    assert.equal(relationLens.found, true);
    assert.equal(relationLens.source.candidateOnly, true);
    assert.equal(relationLens.source.productionWriteExecuted, false);
    assert.equal(relationLens.counts.relations, 1);
    assert.equal(relationLens.data.schemaVersion, "atlas.dj_relation_trajectory.lens.v1");
    assert.equal(relationLens.data.relation.relations[0].sameEventCount, 3);
    assert.equal(relationLens.data.trajectory.cities["dj:a"][0].city, "Shanghai");

    const missingLensRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/starmap/lens?name=missing`);
    assert.equal(missingLensRes.status, 200);
    const missingLens = await missingLensRes.json();
    assert.equal(missingLens.found, false);
    assert.equal(missingLens.reason, "lens_not_found");
    assert.equal(missingLens.available.includes("relationTrajectory"), true);

    const radioRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/radio-external-links?stationKey=cdcr`);
    assert.equal(radioRes.status, 200);
    const radio = await radioRes.json();
    assert.equal(radio.schemaVersion, "atlas_miniapp.radio_external_links_response.v1");
    assert.equal(radio.found, true);
    assert.equal(radio.candidateOnly, true);
    assert.equal(radio.productionWriteExecuted, false);
    assert.equal(radio.oldDatabaseRowsUsed, 0);
    assert.equal(radio.hotlinkPolicy.uiAction, "click_to_open_original_site");
    assert.equal(radio.stations.length, 1);
    assert.equal(radio.stations[0].links[0].url, "https://space.bilibili.com/478422575/");
    assert.equal(radio.stations[0].links[0].noHotlink, true);

    const radioProgramsRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/radio-programs?djId=dj%3Aa&stationKey=cdcr`);
    assert.equal(radioProgramsRes.status, 200);
    const radioPrograms = await radioProgramsRes.json();
    assert.equal(radioPrograms.schemaVersion, "atlas_miniapp.radio_programs_response.v1");
    assert.equal(radioPrograms.found, true);
    assert.equal(radioPrograms.candidateOnly, true);
    assert.equal(radioPrograms.productionWriteExecuted, false);
    assert.equal(radioPrograms.oldDatabaseRowsUsed, 0);
    assert.equal(radioPrograms.hotlinkPolicy.mediaEmbedded, false);
    assert.equal(radioPrograms.matchReview.available, true);
    assert.equal(radioPrograms.programs[0].programId, "radio_program:cdcr:a");
    assert.deepEqual(radioPrograms.programs.map((program) => program.programId), ["radio_program:cdcr:a"]);

    const radioProgramsWithReviewRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/radio-programs?djId=dj%3Aa&stationKey=cdcr&includeReviewOnly=1`);
    assert.equal(radioProgramsWithReviewRes.status, 200);
    const radioProgramsWithReview = await radioProgramsWithReviewRes.json();
    assert.deepEqual(radioProgramsWithReview.programs.map((program) => program.programId), ["radio_program:cdcr:a", "radio_program:cdcr:alias"]);
    assert.equal(radioProgramsWithReview.programs[1].reviewDecision, "review_only");
    assert.deepEqual(radioProgramsWithReview.programs[1].reviewReasons, ["alias_surface_mismatch"]);
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});

test("miniapp Atlas HTTP relation trajectory lens works with only the standalone artifact", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "miniapp-atlas-api-http-relation-"));
  const relationTrajectoryPath = path.join(dir, "dj_relation_trajectory_lens.json.gz");
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_STARMAP_LENSES: process.env.ATLAS_STARMAP_LENSES,
    ATLAS_DJ_RELATION_TRAJECTORY_LENS: process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  let server;
  try {
    await writeFile(relationTrajectoryPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.dj_relation_trajectory.lens.v1",
      generatedAt: "2026-06-23T01:47:00+0800",
      source: { candidateOnly: true, productionWriteExecuted: false, v2: "candidate-v2.sqlite" },
      counts: { djs: 1, relations: 1, subjects: 2 },
      lenses: {
        dj: { items: [{ id: "dj:a", type: "dj", name: "DJ A", eventCount: 4 }] },
        relation: {
          relations: [{ srcDjId: "dj:a", dstDjId: "dj:b", sameEventCount: 3, label: "同台" }],
          collaborators: { "dj:a": [{ djId: "dj:b", name: "DJ B", sameEventCount: 3 }] },
        },
        trajectory: {
          venues: { "dj:a": [{ venueId: "venue:club", venueName: "Club A", eventCount: 2 }] },
          cities: { "dj:a": [{ city: "Shanghai", eventCount: 2 }] },
          events: { "dj:a": [{ eventId: "event:a", title: "Archive Night", sourceRefId: "src:a" }] },
        },
        subject: { subjects: { "dj:a": { id: "dj:a", type: "dj", name: "DJ A" } } },
      },
    }), "utf8")));

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_STARMAP_LENSES = path.join(dir, "missing-atlas-starmap-lenses.json.gz");
    process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = relationTrajectoryPath;
    process.env.CROSS_DB_MERGE_MAP = path.join(dir, "empty-merge-map.json");

    const { __resetMiniappAtlasApiCachesForTests } = await import("../src/miniappAtlasApi.mjs");
    __resetMiniappAtlasApiCachesForTests();
    const { createServer } = await import(`../src/server.mjs?case=standalone-relation-${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);

    const relationLensRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/starmap/lens?name=relationTrajectory`);
    assert.equal(relationLensRes.status, 200);
    const relationLens = await relationLensRes.json();
    assert.equal(relationLens.schemaVersion, "atlas_miniapp.starmap_lens_response.v1");
    assert.equal(relationLens.found, true);
    assert.equal(relationLens.source.candidateOnly, true);
    assert.equal(relationLens.source.productionWriteExecuted, false);
    assert.equal(relationLens.counts.relations, 1);
    assert.equal(relationLens.data.schemaVersion, "atlas.dj_relation_trajectory.lens.v1");
    assert.equal(relationLens.data.relation.relations[0].sameEventCount, 3);

    const missingLensRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/starmap/lens?name=future`);
    assert.equal(missingLensRes.status, 200);
    const missingLens = await missingLensRes.json();
    assert.equal(missingLens.found, false);
    assert.equal(missingLens.reason, "lens_not_found");
    assert.deepEqual(missingLens.available, ["relationTrajectory"]);
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});
