const assert = require("node:assert/strict");
const test = require("node:test");

const { currentFeedBehindManifest } = require("../services/generationContract");

test("current feed compares exact generationId before timestamps", () => {
  assert.equal(currentFeedBehindManifest(
    { generationId: "sha256:same", generated_at: "2026-07-19T09:00:00Z" },
    { generationId: "sha256:same", generatedAt: "2026-07-19T08:00:00Z" },
    60_000,
  ), false);
  assert.equal(currentFeedBehindManifest(
    { generation_id: "sha256:new", generated_at: "2026-07-19T08:00:00Z" },
    { generationId: "sha256:old", generatedAt: "2026-07-19T08:00:00Z" },
    60_000,
  ), true);
  assert.equal(currentFeedBehindManifest(
    { generation_id: "sha256:new" },
    { generatedAt: "2026-07-19T08:00:00Z" },
    60_000,
  ), true);
});

test("legacy packages without generationId retain generatedAt grace fallback", () => {
  assert.equal(currentFeedBehindManifest(
    { generated_at: "2026-07-19T08:00:30Z" },
    { generatedAt: "2026-07-19T08:00:00Z" },
    60_000,
  ), false);
  assert.equal(currentFeedBehindManifest(
    { generated_at: "2026-07-19T08:02:00Z" },
    { generatedAt: "2026-07-19T08:00:00Z" },
    60_000,
  ), true);
});
