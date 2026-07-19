import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dataDir = path.resolve(process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR || path.join(repoRoot, "services/weekly_activity_cloudrun/data"));

test("DJ external links accepted candidate: gate, role filter, and candidateOnly flag", async () => {
  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.join(dataDir, "atlas_index.json.gz");
  process.env.ATLAS_DJ_EXTERNAL_LINKS = path.join(dataDir, "dj_external_links_accepted_candidate.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.join(dataDir, "radio_programs_candidate.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.join(dataDir, "dj_relation_trajectory_lens.json.gz");

  const api = await import("../src/miniappAtlasApi.mjs");
  api.__resetMiniappAtlasApiCachesForTests();

  // shanghaiqiutian has accepted external links (bandcamp, etc.)
  const result = await api.getArtistById("dj:shanghaiqiutian");
  assert.equal(result.found, true, "shanghaiqiutian should be found");

  const links = result.profile?.externalLinks ?? [];
  assert.ok(links.length >= 1, "should expose at least one external link");

  // No 'other' role should appear (gate rule)
  const otherRoles = links.filter((l) => l.role === "other");
  assert.equal(otherRoles.length, 0, "other-role links must be filtered from public DTO");

  // All links must carry candidateOnly flag
  const withoutFlag = links.filter((l) => l.candidateOnly !== true);
  assert.equal(withoutFlag.length, 0, "every accepted link must carry candidateOnly:true");

  // URL must be present and non-empty
  for (const lk of links) {
    assert.ok(lk.url && lk.url.startsWith("http"), `link url must be valid http(s): ${lk.url}`);
  }

  // DJ with 'other'-only links should have those stripped but still return found=true
  const djWithOther = await api.getArtistById("dj:dauerstate");
  assert.equal(djWithOther.found, true);
  const dauerLinks = djWithOther.profile?.externalLinks ?? [];
  const dauerOther = dauerLinks.filter((l) => l.role === "other");
  assert.equal(dauerOther.length, 0, "dauerstate: no other-role links in public DTO");
});
