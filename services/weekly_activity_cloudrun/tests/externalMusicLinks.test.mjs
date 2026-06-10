import assert from "node:assert/strict";
import test from "node:test";
import { buildInterviewExternalLinkFields, cleanExternalUrl, platformFromUrl } from "../src/externalMusicLinks.mjs";

test("external music links normalize interview urls into copyright-safe canonical fields", () => {
  const fields = buildInterviewExternalLinkFields({
    instagramUrl: "https://instagram.com/djspell",
    mixtapeUrl: "https://soundcloud.com/djspell/mix-001",
    sourceUrl: "javascript:alert(1)",
    consentStatus: "graph_candidate_allowed",
    submittedAt: "2026-05-31T08:31:00+08:00",
  });

  assert.equal(fields.schemaVersion, "atlas_external_music_links.v1");
  assert.equal(fields.externalLinks.length, 2);
  assert.equal(fields.musicLinks.length, 1);
  assert.equal(fields.musicLinks[0].platform, "soundcloud");
  assert.equal(fields.musicLinks[0].rightsStatus, "external_link_only");
  assert.equal(fields.musicLinks[0].mediaHandling.download, false);
  assert.equal(fields.musicLinks[0].mediaHandling.cache, false);
  assert.equal(fields.safety.audioDownloadExecuted, false);
  assert.equal(fields.safety.audioProxyEnabled, false);
  assert.match(fields.musicLinks[0].urlHash, /^[0-9a-f]{16}$/);
  assert.equal(JSON.stringify(fields).includes("javascript:"), false);
});

test("external url helpers reject non-http urls and detect known platforms", () => {
  assert.equal(cleanExternalUrl("ftp://example.com/mix.mp3"), "");
  assert.equal(cleanExternalUrl("https://cdn.example.com/archive/live-set.mp3?download=1"), "");
  assert.equal(cleanExternalUrl("https://cdn.example.com/archive/live-set.mp4"), "");
  assert.equal(platformFromUrl("https://mixcloud.com/djspell/session"), "mixcloud");
  assert.equal(platformFromUrl("https://artist.bandcamp.com/album/demo"), "bandcamp");
  assert.equal(platformFromUrl("https://ra.co/dj/djspell"), "resident_advisor");
});

test("external music links keep platform pages and drop direct media files", () => {
  const fields = buildInterviewExternalLinkFields({
    instagramUrl: "https://instagram.com/djspell",
    mixtapeUrl: "https://cdn.example.com/archive/live-set.wav",
    sourceUrl: "https://mixcloud.com/djspell/session",
    consentStatus: "graph_candidate_allowed",
  });

  assert.equal(fields.externalLinks.length, 2);
  assert.deepEqual(fields.externalLinks.map((item) => item.platform), ["instagram", "mixcloud"]);
  assert.equal(fields.musicLinks.length, 1);
  assert.equal(fields.musicLinks[0].platform, "mixcloud");
  assert.equal(fields.musicLinks[0].rightsStatus, "external_link_only");
  assert.equal(fields.musicLinks[0].mediaHandling.download, false);
});
