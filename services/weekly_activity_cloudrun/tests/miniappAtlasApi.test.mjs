import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

test("miniapp Atlas API resolves legacy slug subject IDs to canonical hash IDs", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "miniapp-atlas-api-legacy-id-"));
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_STARMAP_LENSES: process.env.ATLAS_STARMAP_LENSES,
    ATLAS_DJ_RELATION_TRAJECTORY_LENS: process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS,
    ATLAS_RADIO_PROGRAMS: process.env.ATLAS_RADIO_PROGRAMS,
    ATLAS_RADIO_PROGRAM_MATCH_REVIEW: process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW,
    ATLAS_NEIGHBORHOOD_BUNDLE: process.env.ATLAS_NEIGHBORHOOD_BUNDLE,
    ATLAS_DJ_EXTERNAL_LINKS: process.env.ATLAS_DJ_EXTERNAL_LINKS,
    ATLAS_DJ_BIO_CANDIDATES: process.env.ATLAS_DJ_BIO_CANDIDATES,
    ATLAS_DJ_BIO_SNIPPETS: process.env.ATLAS_DJ_BIO_SNIPPETS,
    ATLAS_SCENE_CLUSTERS: process.env.ATLAS_SCENE_CLUSTERS,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };

  try {
    const indexPath = path.join(dir, "atlas_index.json.gz");
    const lensesPath = path.join(dir, "atlas_starmap_lenses.json.gz");
    const neighborhoodPath = path.join(dir, "atlas_neighborhood.json.gz");
    const radioProgramsPath = path.join(dir, "radio_programs_candidate.json.gz");
    const radioReviewPath = path.join(dir, "radio_program_match_review.json");
    const relationPath = path.join(dir, "dj_relation_trajectory_lens.json.gz");
    const mergeMapPath = path.join(dir, "cross_db_merge_map.json");

    await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify({
      v: 4,
      subjects: [
        { i: "dj:alpha", t: "dj", n: "ALPHA", nn: "alpha", a: ["Alpha"], c: "", ec: 1 },
        { i: "dj:hash-alpha", t: "dj", n: "Alpha", nn: "alpha", a: ["Alpha"], c: "上海", ec: 12 },
        { i: "dj:low-nisip", t: "dj", n: "NISIP1 D", nn: "nisip1 d", a: ["NISIP1 D"], c: "", ec: 6 },
        { i: "dj:hash-nisip", t: "dj", n: "NISIP1D", nn: "nisip1d", a: ["NISIP1D"], c: "深圳", ec: 392 },
        { i: "venue:room", t: "venue", n: "Room", nn: "room", a: [], c: "上海", ec: 4 },
      ],
      profiles: {
        "dj:alpha": { n: "ALPHA", c: "", ec: 1 },
        "dj:hash-alpha": { n: "Alpha", c: "上海", ec: 12 },
        "dj:hash-nisip": { n: "NISIP1D", c: "深圳", ec: 392 },
      },
      events: {
        "dj:alpha": [{ eid: "event:alpha-low", t: "Alpha Low", d: "2026-06-20", v: "Room", ci: "" }],
        "dj:hash-alpha": [{ eid: "event:alpha", t: "Alpha Night", d: "2026-06-28", v: "Room", ci: "上海" }],
        "dj:hash-nisip": [{ eid: "event:nisip", t: "NISIP1D Night", d: "2026-06-29", v: "Room", ci: "深圳" }],
      },
      dj_venues: { "dj:hash-alpha": [], "dj:hash-nisip": [] },
      collabs: { "dj:hash-alpha": [], "dj:hash-nisip": [] },
      source_refs: {},
    }), "utf8")));
    await writeFile(neighborhoodPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
      generation: { nodeCount: 3, edgeCount: 2 },
      byNode: {
        "dj:alpha": [{ u: "dj:nisip1d", rt: "collab", w: 10, rs: 6 }],
        "dj:nisip1d": [{ u: "dj:alpha", rt: "collab", w: 10, rs: 6 }],
      },
    }), "utf8")));
    await writeFile(lensesPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.starmap.lenses.v1",
      generatedAt: "2026-06-28T04:40:00+08:00",
      source: { candidateOnly: true, productionWriteExecuted: false },
      counts: { subjects: 2 },
      lenses: {
        subject: {
          subjects: {
            "dj:alpha": { id: "dj:alpha", type: "dj", name: "Alpha" },
            "dj:nisip1d": { id: "dj:nisip1d", type: "dj", name: "NISIP1D" },
          },
        },
      },
    }), "utf8")));
    await writeFile(radioProgramsPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.radio_programs.candidate.v1",
      generatedAt: "2026-06-28T04:40:00+08:00",
      candidateOnly: true,
      productionWriteExecuted: false,
      oldDatabaseRowsUsed: 0,
      source: { mode: "fixture" },
      hotlinkPolicy: { mediaEmbedded: false, uiAction: "click_to_open_original_site" },
      counts: { programs: 1 },
      programsByDjId: { "dj:alpha": ["radio:alpha"] },
      programs: [{
        programId: "radio:alpha",
        stationKey: "byyb",
        stationName: "BYYB",
        title: "Alpha Session",
        url: "https://example.com/alpha",
        platform: "byyb",
        candidateOnly: true,
        openMode: "external_original_site",
        noHotlink: true,
        djMatches: [{ djId: "dj:alpha", displayName: "Alpha", matchedText: "Alpha" }],
      }],
    }), "utf8")));
    await writeFile(radioReviewPath, JSON.stringify({ candidateOnly: true, productionWriteExecuted: false, rows: [] }), "utf8");
    await writeFile(relationPath, gzipSync(Buffer.from(JSON.stringify({ lenses: { relation: {}, trajectory: {} } }), "utf8")));
    await writeFile(mergeMapPath, JSON.stringify({ db2_to_db3_map: {}, existing_subject_map: {} }), "utf8");

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = indexPath;
    process.env.ATLAS_STARMAP_LENSES = lensesPath;
    process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = relationPath;
    process.env.ATLAS_RADIO_PROGRAMS = radioProgramsPath;
    process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = radioReviewPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = neighborhoodPath;
    process.env.ATLAS_DJ_EXTERNAL_LINKS = path.join(dir, "missing-external-links.json.gz");
    process.env.ATLAS_DJ_BIO_CANDIDATES = path.join(dir, "missing-bio-candidates.jsonl");
    process.env.ATLAS_DJ_BIO_SNIPPETS = path.join(dir, "missing-bio-snippets.jsonl");
    process.env.ATLAS_SCENE_CLUSTERS = path.join(dir, "missing-scene-clusters.json.gz");
    process.env.CROSS_DB_MERGE_MAP = mergeMapPath;

    const moduleUrl = new URL(`../src/miniappAtlasApi.mjs?legacy-id=${Date.now()}`, import.meta.url);
    const api = await import(moduleUrl.href);
    api.__resetMiniappAtlasApiCachesForTests();

    const artist = await api.getArtistById("dj:alpha", { eventLimit: 1 });
    assert.equal(artist.found, true);
    assert.equal(artist.query, "dj:alpha");
    assert.equal(artist.subjectId, "dj:hash-alpha");
    assert.equal(artist.requestedSubjectId, "dj:alpha");
    assert.equal(artist.resolvedVia, "legacy_slug");
    assert.equal(artist.profile.subjectId, "dj:hash-alpha");
    assert.equal(artist.profile.djId, "dj:hash-alpha");
    assert.equal(artist.events[0].eventId, "event:alpha");
    assert.equal(artist.radioPrograms[0].programId, "radio:alpha");

    const ranked = await api.getArtistById("dj:nisip1d", { eventLimit: 1 });
    assert.equal(ranked.found, true);
    assert.equal(ranked.subjectId, "dj:hash-nisip");
    assert.equal(ranked.profile.displayName, "NISIP1D");

    const neighborhood = await api.getNeighborhood({ subjectId: "dj:alpha", limit: 1 });
    assert.equal(neighborhood.found, true);
    assert.equal(neighborhood.query.subjectId, "dj:hash-alpha");
    assert.equal(neighborhood.query.requestedSubjectId, "dj:alpha");
    assert.equal(neighborhood.center.id, "dj:hash-alpha");
    assert.equal(neighborhood.edges[0].sourceGraphId, "dj:alpha");
    assert.equal(neighborhood.edges[0].targetGraphId, "dj:nisip1d");

    const pathResult = await api.getPath({ from: "dj:alpha", to: "dj:nisip1d" });
    assert.equal(pathResult.found, true);
    assert.equal(pathResult.query.from, "dj:hash-alpha");
    assert.equal(pathResult.query.to, "dj:hash-nisip");
    assert.equal(pathResult.query.requestedFrom, "dj:alpha");
    assert.equal(pathResult.query.requestedTo, "dj:nisip1d");

    const subjectLens = await api.getStarmapLens({ name: "subject", subjectId: "dj:alpha" });
    assert.equal(subjectLens.found, true);
    assert.equal(subjectLens.subjectId, "dj:hash-alpha");
    assert.equal(subjectLens.requestedSubjectId, "dj:alpha");
    assert.equal(subjectLens.data.name, "Alpha");

    const radio = await api.getRadioPrograms({ djId: "dj:alpha" });
    assert.equal(radio.found, true);
    assert.equal(radio.djId, "dj:hash-alpha");
    assert.equal(radio.requestedDjId, "dj:alpha");
    assert.equal(radio.programs[0].programId, "radio:alpha");
  } finally {
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});

test("miniapp Atlas API exposes source refs for artist and venue history", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "miniapp-atlas-api-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const lensesPath = path.join(dir, "atlas_starmap_lenses.json.gz");
  const relationTrajectoryPath = path.join(dir, "dj_relation_trajectory_lens.json.gz");
  const radioExternalLinksPath = path.join(dir, "radio_external_links_public_seed_candidate.json.gz");
  const radioProgramsPath = path.join(dir, "radio_programs_candidate.json.gz");
  const radioProgramReviewPath = path.join(dir, "radio_program_match_review.json");
  const payload = {
    v: 4,
    subjects: [
      { i: "dj:a", t: "dj", n: "DJ A", nn: "dja", a: [], c: "上海", ec: 1 },
      { i: "dj:z", t: "dj", n: "DJ Z", nn: "djz", a: [], c: "成都", ec: 2 },
      { i: "venue:club", t: "venue", n: "Club A", nn: "cluba", a: [], c: "上海", ec: 1 },
    ],
    profiles: {
      "dj:a": {
        n: "DJ A", c: "上海", ec: 1, vc: 1, cc: 1,
        s: { soundcloud: "https://soundcloud.example/dja", instagram: "@dja" },
        ba: [{ t: "DJ A is a Shenzhen techno selector.", sr: "src:a", st: "Club A archive post", lang: "en", cf: 0.92 }],
        x: [
          { u: "https://instagram.com/dja", p: "instagram", r: "social", l: "IG" },
          { u: "https://soundcloud.com/dja", p: "soundcloud", r: "listen", l: "SC · DJ A", sr: "src:a" },
          { u: "https://nts.live/dja", p: "nts", r: "radio", l: "NTS" },
        ],
      },
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
    related_columns: {
      "dj:a": [{ id: "col:a", t: "DJ A column", s: "Interview and archive profile.", sr: "src:a", p: "2025-12-01" }],
    },
    dj_external_links: {
      "dj:z": [{ u: "https://mixcloud.com/djz", p: "mixcloud", sr: "src:a" }],
    },
  };
  await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify(payload), "utf8")));
  await writeFile(lensesPath, gzipSync(Buffer.from(JSON.stringify({
    schemaVersion: "atlas.starmap.lenses.v1",
    generatedAt: "2026-06-22T00:00:00+0800",
    source: { candidateOnly: true, productionWriteExecuted: false },
    counts: { futureEvents: 1, djTrajItems: 1, neighborhoodItems: 1, subjects: 2 },
    lenses: {
      future: { today: "2026-06-22", events: [{ eventId: "event:f", title: "Future Night", lineup: [{ id: "dj:a", name: "DJ A" }] }] },
      dj_traj: { items: [{ djId: "dj:a", name: "DJ A", events: [{ eventId: "event:a" }] }] },
      neighborhood: { items: [{ subjectId: "dj:a", neighbors: [{ id: "venue:club", type: "resident_at", weight: 3 }] }] },
      subject: { subjects: { "dj:a": { id: "dj:a", type: "dj", name: "DJ A" }, "venue:club": { id: "venue:club", type: "venue", name: "Club A" } } },
    },
  }), "utf8")));
  await writeFile(relationTrajectoryPath, gzipSync(Buffer.from(JSON.stringify({
    schemaVersion: "atlas.dj_relation_trajectory.lens.v1",
    generatedAt: "2026-06-23T01:47:00+0800",
    source: { candidateOnly: true, productionWriteExecuted: false, v2: "candidate-v2.sqlite" },
    counts: { djs: 2, relations: 1, subjects: 3 },
    lenses: {
      dj: { items: [{ id: "dj:a", type: "dj", name: "DJ A", eventCount: 9 }] },
      relation: {
        relations: [{ srcDjId: "dj:a", dstDjId: "dj:b", sameEventCount: 4, label: "同台" }],
        collaborators: { "dj:a": [{ djId: "dj:b", name: "DJ B", sameEventCount: 4 }] },
      },
      trajectory: {
        venues: { "dj:a": [{ venueId: "venue:club", venueName: "Club A", eventCount: 3 }] },
        cities: { "dj:a": [{ city: "上海", eventCount: 3 }] },
        events: { "dj:a": [{ eventId: "event:a", title: "Archive Night", sourceRefId: "src:a" }] },
      },
      subject: { subjects: { "dj:a": { id: "dj:a", type: "dj", name: "DJ A" } } },
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
    counts: { stations: 2, links: 2, verifiedLinks: 2, blockedLinks: 0, oldDatabaseRowsUsed: 0 },
    stations: [
      {
        stationKey: "byyb",
        stationName: "BYYB",
        links: [{ url: "https://byyb.live/", platform: "byyb", role: "radio", openMode: "external_original_site", noHotlink: true }],
      },
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
    programsByDjId: { "dj:a": ["radio_program:byyb:a", "radio_program:byyb:takeover", "radio_program:byyb:alias"] },
    programs: [
      {
        programId: "radio_program:byyb:a",
        stationKey: "byyb",
        stationName: "BYYB",
        title: "DJ A live session",
        url: "https://byyb.live/shows/dj-a-live-session",
        platform: "byyb",
        publishedAt: "2026-06-20",
        description: "Original station page.",
        sourceUrl: "https://byyb.live/",
        openMode: "external_original_site",
        noHotlink: true,
        candidateOnly: true,
        djMatches: [{ djId: "dj:a", displayName: "DJ A", matchedText: "DJ A", confidence: 0.91, matchKind: "fixture" }],
      },
      {
        programId: "radio_program:byyb:takeover",
        stationKey: "byyb",
        stationName: "BYYB",
        title: "CHAOS RADIO takeover",
        url: "https://byyb.live/set/chaos-radio-takeover",
        platform: "byyb",
        sourceUrl: "https://byyb.live/",
        openMode: "external_original_site",
        noHotlink: true,
        candidateOnly: true,
        djMatches: [{ djId: "dj:a", displayName: "DJ A", matchedText: "Take Over", confidence: 0.76, matchKind: "normalized_substring" }],
      },
      {
        programId: "radio_program:byyb:alias",
        stationKey: "byyb",
        stationName: "BYYB",
        title: "DJ A alias radio",
        url: "https://byyb.live/set/dj-a-alias-radio",
        platform: "byyb",
        sourceUrl: "https://byyb.live/",
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
        programId: "radio_program:byyb:takeover",
        djId: "dj:a",
        displayName: "DJ A",
        matchedText: "Take Over",
        reasons: ["generic_term"],
        decision: "hard_hide",
      },
      {
        programId: "radio_program:byyb:alias",
        djId: "dj:a",
        displayName: "DJ A",
        matchedText: "Alias A",
        reasons: ["alias_surface_mismatch"],
        decision: "review_only",
      },
    ],
  }), "utf8");
  process.env.ATLAS_MINIAPP_INDEX = indexPath;
  process.env.ATLAS_STARMAP_LENSES = lensesPath;
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = relationTrajectoryPath;
  process.env.ATLAS_RADIO_EXTERNAL_LINKS = radioExternalLinksPath;
  process.env.ATLAS_RADIO_PROGRAMS = radioProgramsPath;
  process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = radioProgramReviewPath;

  const moduleUrl = new URL(`../src/miniappAtlasApi.mjs?case=${Date.now()}`, import.meta.url);
  const { getArtist, getArtistById, getVenue, getSourceEvidence, getStarmapLens, getRadioExternalLinks, getRadioPrograms } = await import(moduleUrl.href);
  const artist = await getArtist({ name: "DJ A" });
  const artistById = await getArtistById("dj:a");
  const venue = await getVenue({ name: "Club A", eventLimit: 1 });
  const evidence = await getSourceEvidence("src:a");
  const activityEvidence = await getSourceEvidence("activity_src:b");
  const futureLens = await getStarmapLens({ name: "future" });
  const subjectLens = await getStarmapLens({ name: "subject", subjectId: "dj:a" });
  const subjectLensFallback = await getStarmapLens({ name: "subject", subjectId: "dj:z" });
  const relationTrajectoryLens = await getStarmapLens({ name: "relationTrajectory" });
  const missingSubjectLens = await getStarmapLens({ name: "subject", subjectId: "dj:missing" });
  const missingLens = await getStarmapLens({ name: "missing" });
  const radioLinks = await getRadioExternalLinks();
  const cdcrRadioLinks = await getRadioExternalLinks({ stationKey: "cdcr" });
  const missingRadioLinks = await getRadioExternalLinks({ stationKey: "missing" });
  const radioPrograms = await getRadioPrograms({ djId: "dj:a" });
  const radioProgramsWithReviewOnly = await getRadioPrograms({ djId: "dj:a", includeReviewOnly: true });

  assert.equal(artist.events[0].sourceRefId, "src:a");
  assert.equal(artist.events[0].sourceHash, "hash-a");
  assert.equal(artist.events[0].sourceTitle, "Club A archive post");
  assert.equal(artist.venues.length, 1);
  assert.equal(artist.venues[0].venueName, "Club A");
  assert.equal(artist.collaborators.length, 1);
  assert.equal(artist.collaborators[0].sameEventCount, 3);
  assert.equal(artist.profile.social.soundcloud, "https://soundcloud.example/dja");
  assert.equal(artist.social.instagram, "@dja");
  assert.equal(artist.profile.bioAtoms[0].text, "DJ A is a Shenzhen techno selector.");
  assert.equal(artist.bioAtoms[0].sourceRefId, "src:a");
  assert.equal(artist.relatedColumns[0].title, "DJ A column");
  assert.equal(artistById.profile.social.soundcloud, "https://soundcloud.example/dja");
  assert.equal(artistById.relatedColumns[0].columnId, "col:a");
  assert.equal(artist.profile.externalLinks.length, 3);
  // role ordering enforced by API: listen -> social -> radio (input was social,listen,radio)
  assert.deepEqual(artist.profile.externalLinks.map(l => l.role), ["listen", "social", "radio"]);
  assert.equal(artist.profile.externalLinks[0].url, "https://soundcloud.com/dja");
  assert.equal(artist.profile.externalLinks[0].platform, "soundcloud");
  assert.equal(artist.profile.externalLinks[0].sourceRefId, "src:a");
  assert.equal(artist.profile.externalLinks[0].sourceTitle, "Club A archive post");
  assert.equal(Object.hasOwn(artist.profile.externalLinks[0], "sourceHash"), false);
  assert.equal(artist.radioPrograms.length, 1);
  assert.equal(artist.profile.radioPrograms[0].programId, "radio_program:byyb:a");
  assert.equal(artist.profile.radioPrograms[0].openMode, "external_original_site");
  assert.equal(artist.profile.radioPrograms[0].noHotlink, true);
  assert.equal(artist.profile.radioPrograms[0].reviewDecision, "safe_display");
  assert.equal(artist.profile.radioPrograms[0].djMatches[0].djId, "dj:a");
  assert.equal(artist.relationTrajectory.schemaVersion, "atlas_miniapp.artist_relation_trajectory.v1");
  assert.equal(artist.relationTrajectory.source.candidateOnly, true);
  assert.equal(artist.relationTrajectory.source.productionWriteExecuted, false);
  assert.equal(artist.relationTrajectory.collaborators[0].displayName, "DJ B");
  assert.equal(artist.relationTrajectory.collaborators[0].sameEventCount, 4);
  assert.equal(artist.relationTrajectory.venues[0].venueName, "Club A");
  assert.equal(artist.relationTrajectory.cities[0].city, "上海");
  assert.equal(artist.relationTrajectory.events[0].sourceRefId, "src:a");
  assert.equal(artist.profile.relationTrajectory.events[0].title, "Archive Night");
  assert.equal(artistById.profile.externalLinks[0].role, "listen");
  assert.equal(artistById.radioPrograms[0].url, "https://byyb.live/shows/dj-a-live-session");
  assert.equal(artistById.relationTrajectory.venues[0].eventCount, 3);
  assert.equal(subjectLensFallback.data.name, "DJ Z");
  assert.equal(subjectLensFallback.sourceFallback, "atlas_index");
  const artistZById = await getArtistById("dj:z");
  assert.equal(artistZById.profile.externalLinks[0].role, "other");
  assert.equal(artistZById.profile.externalLinks[0].platform, "mixcloud");
  assert.equal(artistZById.profile.externalLinks[0].sourceTitle, "Club A archive post");
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
  assert.equal(futureLens.found, true);
  assert.equal(futureLens.data.events[0].lineup[0].id, "dj:a");
  assert.equal(subjectLens.data.name, "DJ A");
  assert.equal(relationTrajectoryLens.found, true);
  assert.equal(relationTrajectoryLens.schemaVersion, "atlas_miniapp.starmap_lens_response.v1");
  assert.equal(relationTrajectoryLens.lens, "relationTrajectory");
  assert.equal(relationTrajectoryLens.source.candidateOnly, true);
  assert.equal(relationTrajectoryLens.source.productionWriteExecuted, false);
  assert.equal(relationTrajectoryLens.counts.relations, 1);
  assert.equal(relationTrajectoryLens.data.schemaVersion, "atlas.dj_relation_trajectory.lens.v1");
  assert.equal(relationTrajectoryLens.data.relation.relations[0].srcDjId, "dj:a");
  assert.equal(relationTrajectoryLens.data.trajectory.venues["dj:a"][0].venueName, "Club A");
  assert.equal(missingSubjectLens.found, false);
  assert.equal(missingSubjectLens.reason, "subject_not_found");
  assert.equal(missingSubjectLens.data, null);
  assert.equal(missingLens.found, false);
  assert.equal(missingLens.reason, "lens_not_found");
  assert.deepEqual(missingLens.available, ["dj_traj", "future", "neighborhood", "relationTrajectory", "subject"]);
  assert.equal(radioLinks.found, true);
  assert.equal(radioLinks.schemaVersion, "atlas_miniapp.radio_external_links_response.v1");
  assert.equal(radioLinks.candidateOnly, true);
  assert.equal(radioLinks.productionWriteExecuted, false);
  assert.equal(radioLinks.oldDatabaseRowsUsed, 0);
  assert.equal(radioLinks.hotlinkPolicy.uiAction, "click_to_open_original_site");
  assert.equal(radioLinks.hotlinkPolicy.mediaEmbedded, false);
  assert.equal(radioLinks.stations.length, 2);
  assert.equal(cdcrRadioLinks.found, true);
  assert.equal(cdcrRadioLinks.stations.length, 1);
  assert.equal(cdcrRadioLinks.stations[0].links[0].url, "https://space.bilibili.com/478422575/");
  assert.equal(cdcrRadioLinks.stations[0].links[0].noHotlink, true);
  assert.equal(missingRadioLinks.found, false);
  assert.equal(missingRadioLinks.reason, "station_not_found");
  assert.deepEqual(missingRadioLinks.available, ["byyb", "cdcr"]);
  assert.equal(radioPrograms.found, true);
  assert.equal(radioPrograms.schemaVersion, "atlas_miniapp.radio_programs_response.v1");
  assert.equal(radioPrograms.candidateOnly, true);
  assert.equal(radioPrograms.productionWriteExecuted, false);
  assert.equal(radioPrograms.oldDatabaseRowsUsed, 0);
  assert.equal(radioPrograms.hotlinkPolicy.mediaEmbedded, false);
  assert.equal(radioPrograms.matchReview.available, true);
  assert.equal(radioPrograms.matchReview.counts.decision_hard_hide, 1);
  assert.equal(radioPrograms.programs[0].programId, "radio_program:byyb:a");
  assert.deepEqual(radioPrograms.programs.map((program) => program.programId), ["radio_program:byyb:a"]);
  assert.deepEqual(radioProgramsWithReviewOnly.programs.map((program) => program.programId), ["radio_program:byyb:a", "radio_program:byyb:alias"]);
  assert.equal(radioProgramsWithReviewOnly.programs[1].reviewDecision, "review_only");
  assert.deepEqual(radioProgramsWithReviewOnly.programs[1].reviewReasons, ["alias_surface_mismatch"]);
});

test("relation trajectory lens loads from its standalone artifact without the base lens bundle", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "miniapp-atlas-relation-lens-"));
  const relationTrajectoryPath = path.join(dir, "dj_relation_trajectory_lens.json.gz");
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_STARMAP_LENSES: process.env.ATLAS_STARMAP_LENSES,
    ATLAS_DJ_RELATION_TRAJECTORY_LENS: process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS,
  };
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

    const moduleUrl = new URL(`../src/miniappAtlasApi.mjs?case=standalone-relation-${Date.now()}`, import.meta.url);
    const { getStarmapLens } = await import(moduleUrl.href);
    const relationTrajectoryLens = await getStarmapLens({ name: "relationTrajectory" });
    const missingLens = await getStarmapLens({ name: "future" });

    assert.equal(relationTrajectoryLens.found, true);
    assert.equal(relationTrajectoryLens.lens, "relationTrajectory");
    assert.equal(relationTrajectoryLens.source.candidateOnly, true);
    assert.equal(relationTrajectoryLens.source.productionWriteExecuted, false);
    assert.equal(relationTrajectoryLens.counts.relations, 1);
    assert.equal(relationTrajectoryLens.data.schemaVersion, "atlas.dj_relation_trajectory.lens.v1");
    assert.equal(relationTrajectoryLens.data.relation.relations[0].sameEventCount, 3);
    assert.equal(relationTrajectoryLens.data.trajectory.venues["dj:a"][0].venueName, "Club A");
    assert.equal(missingLens.found, false);
    assert.equal(missingLens.reason, "lens_not_found");
    assert.deepEqual(missingLens.available, ["relationTrajectory"]);
  } finally {
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});
