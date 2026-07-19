// Tests for utils/groupOutlinks.js — samples from the C preview audit.
// Run: node apps/weekly_activity_miniprogram/tests/group-outlinks.test.cjs

"use strict";
const assert = require("assert");
const path = require("path");
const { groupOutlinks, isAccountUrl } = require(path.join(__dirname, "../utils/groupOutlinks.js"));

// ── isAccountUrl ──────────────────────────────────────────────────────────────

assert.ok(isAccountUrl("https://soundcloud.com/cyber-kid-30108351", "soundcloud"), "SC: 1-seg = account");
assert.ok(!isAccountUrl("https://soundcloud.com/cyber-kid-30108351/can-you-hear-it", "soundcloud"), "SC: 2-seg = deep");
assert.ok(!isAccountUrl("https://soundcloud.com/cyber-kid-30108351/popular-tracks", "soundcloud"), "SC: popular-tracks = deep");
assert.ok(!isAccountUrl("https://soundcloud.com/JD_X/88-rising-radio", "soundcloud"), "SC: show = deep");
assert.ok(isAccountUrl("https://soundcloud.com/jd-x", "soundcloud"), "SC: handle only = account");

assert.ok(isAccountUrl("https://duanluoo.bandcamp.com", "bandcamp"), "BC: root = account");
assert.ok(isAccountUrl("https://duanluoo.bandcamp.com/", "bandcamp"), "BC: trailing slash = account");
assert.ok(!isAccountUrl("https://duanluoo.bandcamp.com/album/homeparty", "bandcamp"), "BC: album = deep");
assert.ok(!isAccountUrl("https://duanluoo.bandcamp.com/music", "bandcamp"), "BC: /music = deep");
assert.ok(!isAccountUrl("https://duanluoo.bandcamp.com/track/foo", "bandcamp"), "BC: track = deep");
assert.ok(!isAccountUrl("https://enemastone.bandcamp.com/community", "bandcamp"), "BC: community = deep");

assert.ok(isAccountUrl("https://www.mixcloud.com/raddam-ras", "mixcloud"), "MC: handle = account");
assert.ok(isAccountUrl("https://www.mixcloud.com/JD_X/stream/", "mixcloud"), "MC: /stream = account-like");
assert.ok(!isAccountUrl("https://www.mixcloud.com/raddam-ras/raddam-ras-dada-style/", "mixcloud"), "MC: show = deep");

assert.ok(isAccountUrl("https://beatport.com/artist/dizz-martin/262503", "beatport"), "Beatport: artist page = account");
assert.ok(!isAccountUrl("https://beatport.com/artist/dizz-martin/262503/charts", "beatport"), "Beatport: charts = deep");
assert.ok(!isAccountUrl("https://beatport.com/artist/dizz-martin/262503/tracks", "beatport"), "Beatport: tracks = deep");

assert.ok(isAccountUrl("https://instagram.com/hyph11e", "instagram"), "IG: account");
assert.ok(isAccountUrl("https://linktr.ee/piporomero", "linktree"), "Linktree: account");

console.log("✓ isAccountUrl: all 17 assertions passed");

// ── groupOutlinks ─────────────────────────────────────────────────────────────

// Empty / null guard
assert.deepStrictEqual(groupOutlinks([]), []);
assert.deepStrictEqual(groupOutlinks(null), []);
assert.deepStrictEqual(groupOutlinks(undefined), []);
console.log("✓ empty/null input handled");

// dj:cyberkid — 3 soundcloud links (1 account + 2 deep)
const cyberkidLinks = [
  { url: "https://soundcloud.com/cyber-kid-30108351", platform: "soundcloud", role: "listen", label: "SoundCloud · CYBER KID" },
  { url: "https://soundcloud.com/cyber-kid-30108351/can-you-hear-it", platform: "soundcloud", role: "listen", label: "SoundCloud · CYBER KID" },
  { url: "https://soundcloud.com/cyber-kid-30108351/popular-tracks", platform: "soundcloud", role: "listen", label: "SoundCloud · CYBER KID" },
];
{
  const g = groupOutlinks(cyberkidLinks);
  assert.strictEqual(g.length, 1, "cyberkid: 1 role group");
  assert.strictEqual(g[0].role, "listen");
  assert.strictEqual(g[0].platforms.length, 1);
  const sc = g[0].platforms[0];
  assert.strictEqual(sc.platform, "soundcloud");
  assert.strictEqual(sc.primary.url, "https://soundcloud.com/cyber-kid-30108351");
  assert.strictEqual(sc.moreCount, 2);
  assert.strictEqual(sc.total, 3);
  console.log("✓ cyberkid: SC account as primary, 2 deep in more");
}

// dj:conrank — simulated 10 soundcloud links (1 account + 9 deep)
const conrankLinks = Array.from({ length: 10 }, function(_, i) {
  return {
    url: i === 0 ? "https://soundcloud.com/conrank" : "https://soundcloud.com/conrank/track-" + i,
    platform: "soundcloud", role: "listen", label: "SoundCloud · Conrank",
  };
});
{
  const g = groupOutlinks(conrankLinks);
  const sc = g[0].platforms[0];
  assert.strictEqual(sc.primary.url, "https://soundcloud.com/conrank", "conrank primary is account URL");
  assert.strictEqual(sc.moreCount, 9);
  assert.strictEqual(sc.total, 10);
  // Critical: must NOT produce 10 separate display buttons
  assert.ok(sc.total > 1, "total > 1");
  assert.ok(sc.moreCount > 0, "extra links go into more, not flat list");
  console.log("✓ conrank: 1 primary + 9 more (no 10-button flat list)");
}

// dj:duanluoo — 3 bandcamp (1 root account + 2 deep) + 1 instagram social
const duanluooLinks = [
  { url: "https://duanluoo.bandcamp.com", platform: "bandcamp", role: "listen", label: "Bandcamp · Duanluoo" },
  { url: "https://duanluoo.bandcamp.com/album/homeparty", platform: "bandcamp", role: "listen", label: "Bandcamp · Duanluoo" },
  { url: "https://duanluoo.bandcamp.com/music", platform: "bandcamp", role: "listen", label: "Bandcamp · Duanluoo" },
  { url: "https://instagram.com/duanluoo", platform: "instagram", role: "social", label: "Instagram · Duanluoo" },
];
{
  const g = groupOutlinks(duanluooLinks);
  assert.strictEqual(g.length, 2, "listen + social");
  assert.strictEqual(g[0].role, "listen", "listen comes first");
  assert.strictEqual(g[1].role, "social");
  const bc = g[0].platforms[0];
  assert.strictEqual(bc.platform, "bandcamp");
  assert.strictEqual(bc.primary.url, "https://duanluoo.bandcamp.com");
  assert.strictEqual(bc.moreCount, 2);
  const ig = g[1].platforms[0];
  assert.strictEqual(ig.primary.url, "https://instagram.com/duanluoo");
  assert.strictEqual(ig.moreCount, 0);
  console.log("✓ duanluoo: listen(BC 1+2) + social(IG)");
}

// dj:dizzmartin — beatport artist page (account) + deep links
const dizzLinks = [
  { url: "https://beatport.com/artist/dizz-martin/262503", platform: "beatport", role: "listen", label: "Beatport · Dizz Martin" },
  { url: "https://beatport.com/artist/dizz-martin/262503/charts", platform: "beatport", role: "listen", label: "Beatport · Dizz Martin" },
  { url: "https://beatport.com/artist/dizz-martin/262503/tracks", platform: "beatport", role: "listen", label: "Beatport · Dizz Martin" },
];
{
  const g = groupOutlinks(dizzLinks);
  const bp = g[0].platforms[0];
  assert.strictEqual(bp.platform, "beatport");
  assert.strictEqual(bp.primary.url, "https://beatport.com/artist/dizz-martin/262503");
  assert.strictEqual(bp.moreCount, 2);
  console.log("✓ dizzmartin: beatport artist page = primary, charts+tracks in more");
}

// No account URL: first deep link promoted to primary
const allDeepLinks = [
  { url: "https://soundcloud.com/conrank/track-1", platform: "soundcloud", role: "listen", label: "SC track" },
  { url: "https://soundcloud.com/conrank/track-2", platform: "soundcloud", role: "listen", label: "SC track 2" },
];
{
  const g = groupOutlinks(allDeepLinks);
  const sc = g[0].platforms[0];
  assert.strictEqual(sc.primary.url, "https://soundcloud.com/conrank/track-1", "first link promoted to primary");
  assert.strictEqual(sc.moreCount, 1);
  console.log("✓ no account URL: first deep link promoted to primary");
}

// Role order: listen > profile > social > video > interview > radio > source
const mixedRoles = [
  { url: "https://instagram.com/test", platform: "instagram", role: "social", label: "IG" },
  { url: "https://soundcloud.com/test", platform: "soundcloud", role: "listen", label: "SC" },
  { url: "https://example.com/profile", platform: "website", role: "profile", label: "Profile" },
  { url: "https://example.com/interview", platform: "website", role: "interview", label: "Interview" },
];
{
  const g = groupOutlinks(mixedRoles);
  const roles = g.map(function(x) { return x.role; });
  assert.strictEqual(roles[0], "listen", "listen first");
  assert.strictEqual(roles[1], "profile", "profile second");
  assert.strictEqual(roles[2], "social", "social third");
  assert.strictEqual(roles[3], "interview", "interview fourth");
  console.log("✓ role order: listen > profile > social > interview");
}

// Chinese role labels
{
  const g = groupOutlinks(cyberkidLinks, "zh");
  assert.strictEqual(g[0].roleLabel, "去听", "zh label: 去听");
  const g2 = groupOutlinks(cyberkidLinks, "en");
  assert.strictEqual(g2[0].roleLabel, "Listen", "en label: Listen");
  console.log("✓ i18n role labels");
}

// Unknown role is dropped
const unknownRole = [
  { url: "https://soundcloud.com/test", platform: "soundcloud", role: "unknown_role", label: "SC" },
  { url: "https://soundcloud.com/test2", platform: "soundcloud", role: "listen", label: "SC2" },
];
{
  const g = groupOutlinks(unknownRole);
  assert.strictEqual(g.length, 1, "only listen group, unknown role dropped");
  console.log("✓ unknown role dropped");
}

// Links missing required fields are skipped
const malformed = [
  { url: "", platform: "soundcloud", role: "listen", label: "empty url" },
  { platform: "soundcloud", role: "listen", label: "no url" },
  { url: "https://soundcloud.com/test", role: "listen", label: "no platform" },
  { url: "https://soundcloud.com/test", platform: "soundcloud", label: "no role" },
  { url: "https://soundcloud.com/valid", platform: "soundcloud", role: "listen", label: "valid" },
];
{
  const g = groupOutlinks(malformed);
  assert.strictEqual(g.length, 1, "only valid link produces group");
  assert.strictEqual(g[0].platforms[0].primary.url, "https://soundcloud.com/valid");
  console.log("✓ malformed links skipped gracefully");
}

console.log("\n✓ All group-outlinks tests passed");
