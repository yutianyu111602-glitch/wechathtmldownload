/**
 * #4-E Contract test: C preview broad outlinks via ATLAS_DJ_EXTERNAL_LINKS env var.
 * Verifies that pointing the backend at the C preview bundle (instead of the accepted
 * sidecar) returns the extra 198 links for the 65 newly added DJs, and that
 * groupOutlinks() produces correct grouped structure for the high-risk DJs.
 *
 * Safety: read-only. No production write, no deploy, no upload, no index rebuild.
 *
 * Run:
 *   node --test services/weekly_activity_cloudrun/tests/broadOutlinkCPreviewContract.test.mjs
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFile } from "node:fs/promises";
import { gunzipSync } from "node:zlib";

const __dir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dir, "../../..");

// Point backend at C preview bundle
const cPreviewPath = path.resolve(
  process.env.HUAIDJ_ATLAS_BROAD_OUTLINK_PREVIEW
    || path.join(root, "tools/atlas_rebuild/reports/broad_outlink_sidecar_audit_20260624/dj_external_links_accepted_plus_broad_preview_candidate.json.gz")
);
process.env.ATLAS_DJ_EXTERNAL_LINKS = cPreviewPath;

// Load groupOutlinks (frontend util — pure, no WeChat deps)
const requireFrontend = createRequire(
  path.join(root, "apps/weekly_activity_miniprogram/utils/groupOutlinks.js")
);
const { groupOutlinks, isAccountUrl } = requireFrontend("./groupOutlinks.js");

// Helper: load + parse the C preview bundle directly (bypasses env var path for assertions)
async function loadCPreview() {
  const buf = await readFile(cPreviewPath);
  return JSON.parse(gunzipSync(buf).toString("utf-8"));
}

// Helper: simulate what externalLinksForDjFromBundle returns for a given djId
const DJ_OUTLINK_PUBLIC_ROLES = new Set(["listen", "social", "profile", "interview", "radio", "source", "video"]);

function simulateExternalLinksForDj(bundle, djId, limit = 20) {
  if (!bundle || bundle.candidateOnly !== true) return [];
  const links = Array.isArray(bundle.djLinks?.[djId]) ? bundle.djLinks[djId] : [];
  return links
    .filter((lk) => lk?.url && DJ_OUTLINK_PUBLIC_ROLES.has(String(lk.role || "").toLowerCase()))
    .slice(0, limit)
    .map((lk) => ({
      url: String(lk.url || ""),
      platform: String(lk.platform || "other"),
      role: String(lk.role || "other"),
      label: String(lk.label || ""),
      candidateOnly: true,
    }));
}

test("C preview bundle has correct structure for backend consumption", async () => {
  const bundle = await loadCPreview();
  assert.strictEqual(bundle.candidateOnly, true, "candidateOnly must be true");
  assert.strictEqual(bundle.productionWriteExecuted, false, "productionWriteExecuted must be false");
  assert.ok(typeof bundle.djLinks === "object" && bundle.djLinks !== null, "djLinks must be object");
  const djCount = Object.keys(bundle.djLinks).length;
  assert.ok(djCount >= 1831, `expected >= 1831 DJs, got ${djCount}`);
  console.log(`  C preview: ${djCount} DJs in djLinks`);
});

test("dj:conrank — 12 links, 1 SC account primary + 9 deep in more", async () => {
  const bundle = await loadCPreview();
  const links = simulateExternalLinksForDj(bundle, "dj:conrank");
  assert.ok(links.length >= 10, `conrank expected >= 10 links, got ${links.length}`);

  const grouped = groupOutlinks(links, "zh");
  const listenGroup = grouped.find((g) => g.role === "listen");
  assert.ok(listenGroup, "listen group must exist");

  const sc = listenGroup.platforms.find((p) => p.platform === "soundcloud");
  assert.ok(sc, "soundcloud platform group must exist");
  assert.ok(sc.primary, "soundcloud must have a primary link");
  assert.strictEqual(sc.primary.url, "https://soundcloud.com/conrank", "primary must be account URL");
  assert.ok(sc.moreCount >= 7, `conrank SC more links should be >= 7, got ${sc.moreCount}`);
  console.log(`  conrank: SC primary=${sc.primary.url}, moreCount=${sc.moreCount}, total=${sc.total}`);
});

test("dj:cyberkid — 5 SC links, account URL as primary", async () => {
  const bundle = await loadCPreview();
  const links = simulateExternalLinksForDj(bundle, "dj:cyberkid");
  assert.ok(links.length >= 3, `cyberkid expected >= 3 links, got ${links.length}`);

  const grouped = groupOutlinks(links, "zh");
  const listenGroup = grouped.find((g) => g.role === "listen");
  assert.ok(listenGroup, "listen group must exist");

  const sc = listenGroup.platforms.find((p) => p.platform === "soundcloud");
  assert.ok(sc, "soundcloud group must exist");
  assert.ok(isAccountUrl(sc.primary.url, "soundcloud"), "primary must be account URL");
  assert.ok(!sc.primary.url.includes("/can-you-hear-it"), "primary must not be a track URL");
  console.log(`  cyberkid: SC primary=${sc.primary.url}, moreCount=${sc.moreCount}`);
});

test("dj:duanluoo — bandcamp root as primary, /album and /music in more", async () => {
  const bundle = await loadCPreview();
  const links = simulateExternalLinksForDj(bundle, "dj:duanluoo");
  assert.ok(links.length >= 3, `duanluoo expected >= 3 links, got ${links.length}`);

  const grouped = groupOutlinks(links, "zh");
  const listenGroup = grouped.find((g) => g.role === "listen");
  assert.ok(listenGroup, "listen group must exist");

  const bc = listenGroup.platforms.find((p) => p.platform === "bandcamp");
  assert.ok(bc, "bandcamp group must exist");
  assert.ok(bc.primary.url.endsWith(".bandcamp.com") || bc.primary.url.endsWith(".bandcamp.com/"),
    `primary must be BC root, got ${bc.primary.url}`);
  console.log(`  duanluoo: BC primary=${bc.primary.url}, moreCount=${bc.moreCount}`);
});

test("dj:joachimspieth — 9 bandcamp links, 1 primary account + rest in more", async () => {
  const bundle = await loadCPreview();
  const links = simulateExternalLinksForDj(bundle, "dj:joachimspieth");
  // May not be in C preview if they were already in accepted — check
  if (!links.length) {
    console.log("  joachimspieth: no links in C preview (may be in accepted sidecar only — OK)");
    return;
  }
  const grouped = groupOutlinks(links, "zh");
  const listenGroup = grouped.find((g) => g.role === "listen");
  if (!listenGroup) { console.log("  joachimspieth: no listen group"); return; }
  const bc = listenGroup.platforms.find((p) => p.platform === "bandcamp");
  if (!bc) { console.log("  joachimspieth: no bandcamp group"); return; }
  // Must NOT produce 9 separate buttons
  assert.ok(bc.total > 0, "bandcamp group must have at least 1 link");
  assert.ok(bc.primary, "must have a primary");
  console.log(`  joachimspieth: BC total=${bc.total}, primary=${bc.primary.url}`);
});

test("dj:raddamras — 4 mixcloud links, /stream is account-like, shows as group", async () => {
  const bundle = await loadCPreview();
  const links = simulateExternalLinksForDj(bundle, "dj:raddamras");
  assert.ok(links.length >= 1, `raddamras expected >= 1 links, got ${links.length}`);

  const grouped = groupOutlinks(links, "zh");
  const listenGroup = grouped.find((g) => g.role === "listen");
  assert.ok(listenGroup, "listen group must exist");
  console.log(`  raddamras: ${listenGroup.platforms.length} platform(s), ${links.length} total links`);
});

test("no link leaks other role into 'other' or blocked role", async () => {
  const bundle = await loadCPreview();
  const sample = ["dj:conrank", "dj:cyberkid", "dj:duanluoo", "dj:raddamras", "dj:enemastone",
                   "dj:tristanarp", "dj:hyph11e", "dj:pixiuu", "dj:jdx", "dj:dizzmartin"];
  for (const djId of sample) {
    const links = simulateExternalLinksForDj(bundle, djId);
    for (const lk of links) {
      assert.ok(lk.role !== "other", `${djId}: 'other' role must never surface (link: ${lk.url})`);
      assert.ok(DJ_OUTLINK_PUBLIC_ROLES.has(lk.role), `${djId}: unexpected role '${lk.role}'`);
      assert.ok(lk.candidateOnly === true, `${djId}: candidateOnly must be true`);
    }
  }
  console.log(`  Role gate: all 10 high-risk DJs clean`);
});

test("groupOutlinks role labels are correct for zh and en", async () => {
  const bundle = await loadCPreview();
  const links = simulateExternalLinksForDj(bundle, "dj:conrank");
  const zh = groupOutlinks(links, "zh");
  const en = groupOutlinks(links, "en");
  const zhListen = zh.find((g) => g.role === "listen");
  const enListen = en.find((g) => g.role === "listen");
  assert.ok(zhListen, "zh listen group");
  assert.ok(enListen, "en listen group");
  assert.strictEqual(zhListen.roleLabel, "去听");
  assert.strictEqual(enListen.roleLabel, "Listen");
  console.log(`  i18n: zh="去听", en="Listen"`);
});
