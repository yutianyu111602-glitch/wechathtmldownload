import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

// Locks the serving-layer radio guard added to miniappAtlasApi.radioProgramsForDjFromBundle:
//   - ambiguous attributions (same matchedText -> multiple djIds) are hidden from display
//   - #Top / trailing-slash URL variants are deduped
test("radio programs serving guard: drop ambiguous + dedup #Top", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "radio-guard-"));
  const packPath = path.join(dir, "radio_programs_candidate.json.gz");
  const pack = {
    schemaVersion: "atlas.radio_programs.candidate.v1",
    candidateOnly: true,
    productionWriteExecuted: false,
    oldDatabaseRowsUsed: 0,
    hotlinkPolicy: { mediaEmbedded: false, uiAction: "click_to_open_original_site" },
    programsByDjId: {
      "dj:xinsheng": ["p_clean", "p_clean_top", "p_ambiguous"],
      "dj:xinsheng2": ["p_ambiguous"],
      "dj:april": ["p_month"],
    },
    programs: [
      { programId: "p_clean", stationKey: "byyb", url: "https://byyb.live/shows/xinsheng-wk1", platform: "byyb",
        title: "clean", noHotlink: true, candidateOnly: true,
        djMatches: [{ djId: "dj:xinsheng", displayName: "新生", matchedText: "新生wk1", confidence: 0.8, matchKind: "normalized_substring" }] },
      // #Top variant of the same URL -> must dedup away
      { programId: "p_clean_top", stationKey: "byyb", url: "https://byyb.live/shows/xinsheng-wk1#Top", platform: "byyb",
        title: "clean dup", noHotlink: true, candidateOnly: true,
        djMatches: [{ djId: "dj:xinsheng", displayName: "新生", matchedText: "新生wk1", confidence: 0.8, matchKind: "normalized_substring" }] },
      // ambiguous: matchedText "新生" maps to two distinct djIds -> hidden from both
      { programId: "p_ambiguous", stationKey: "baihui", url: "https://baihui.live/shows/x", platform: "baihui",
        title: "ambiguous", noHotlink: true, candidateOnly: true,
        djMatches: [
          { djId: "dj:xinsheng", displayName: "新生", matchedText: "新生", confidence: 0.76, matchKind: "normalized_substring" },
          { djId: "dj:xinsheng2", displayName: "新生 (新生)", matchedText: "新生", confidence: 0.76, matchKind: "normalized_substring" },
        ] },
      // generic month token: "April" in a HÖR date matched DJ "APRIL" -> must hide
      { programId: "p_month", stationKey: "hor", url: "https://hoer.live/x", platform: "hoer",
        title: "K.HAAZ | HÖR – April 30 / 2026", noHotlink: true, candidateOnly: true,
        djMatches: [{ djId: "dj:april", displayName: "APRIL", matchedText: "April", confidence: 0.8, matchKind: "normalized_substring" }] },
    ],
  };
  await writeFile(packPath, gzipSync(Buffer.from(JSON.stringify(pack), "utf8")));
  process.env.ATLAS_RADIO_PROGRAMS = packPath;

  const { getRadioPrograms } = await import(new URL(`../src/miniappAtlasApi.mjs?case=${Date.now()}`, import.meta.url).href);

  const xinsheng = await getRadioPrograms({ djId: "dj:xinsheng" });
  // p_clean kept; p_clean_top deduped (same base URL); p_ambiguous hidden
  assert.equal(xinsheng.programs.length, 1, "only one clean deduped program");
  assert.equal(xinsheng.programs[0].url, "https://byyb.live/shows/xinsheng-wk1");

  const twin = await getRadioPrograms({ djId: "dj:xinsheng2" });
  assert.equal(twin.found, false, "twin has only the ambiguous program -> hidden");
  assert.equal(twin.programs.length, 0);

  const month = await getRadioPrograms({ djId: "dj:april" });
  assert.equal(month.found, false, "month-token match (HÖR date) -> hidden");
  assert.equal(month.programs.length, 0);

  await rm(dir, { recursive: true, force: true });
});
