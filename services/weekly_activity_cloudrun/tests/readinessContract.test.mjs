import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { createServer } from "../src/server.mjs";
import { WeeklyActivityDataStore } from "../src/dataStore.mjs";

async function writeJson(filePath, value) {
  await writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

async function createReadyFixture() {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-ready-"));
  await mkdir(path.join(dir, "by-id"), { recursive: true });
  const generationId = `weekly-sha256-${"a".repeat(64)}`;
  const item = {
    id: "ready-item",
    title: "Ready Techno Night",
    city_key: "shanghai",
    city_keys: ["shanghai"],
    city: ["上海"],
    event_date_start: "2026-07-25",
    event_date_end: "2026-07-25",
    quality_status: "READY",
    styles: ["techno"],
  };
  await writeJson(path.join(dir, "manifest.json"), {
    schema_version: "weekly_activity_miniprogram_api.v1",
    generated_at: "2026-07-19T18:00:00+08:00",
    generation_id: generationId,
    item_count: 1,
    window_start: "2026-07-19",
    window_end: "2026-08-19",
  });
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-07-19T18:00:00+08:00",
    generation_id: generationId,
    item_count: 1,
    items: [item],
  });
  await writeJson(path.join(dir, "by-id", "ready-item.json"), {
    schema_version: "weekly_activity_miniprogram_detail.v1",
    generated_at: "2026-07-19T18:00:00+08:00",
    generation_id: generationId,
    item,
  });
  return { dir, generationId };
}

async function withServer(options, fn) {
  const server = createServer(options);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const { port } = server.address();
  try {
    await fn(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("readyz proves the active package identity and by-id closure", async () => {
  const { dir, generationId } = await createReadyFixture();
  await withServer({ baseDir: dir, env: { WEEKLY_ACTIVITY_TODAY: "2026-07-19" } }, async (baseUrl) => {
    const response = await fetch(`${baseUrl}/readyz`);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.ok, true);
    assert.equal(body.generationId, generationId);
    assert.equal(body.packageItemCount, 1);
    assert.equal(body.derivedDetailCount, 1);
    assert.match(body.itemIdDigest, /^[a-f0-9]{64}$/);
  });
});
test("a missing package is not converted into a cacheable HTTP 200 empty feed", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-not-ready-"));
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });
  await assert.rejects(
    () => store.getCurrent({ scope: "current", limit: 100 }),
    (error) => error && error.code === "WEEKLY_CURRENT_UNAVAILABLE",
  );

  await withServer({ baseDir: dir, env: { WEEKLY_ACTIVITY_TODAY: "2026-07-19" } }, async (baseUrl) => {
    const ready = await fetch(`${baseUrl}/readyz`);
    assert.equal(ready.status, 503);
    const readiness = await ready.json();
    assert.equal(readiness.error.code, "WEEKLY_NOT_READY");

    for (let attempt = 0; attempt < 2; attempt += 1) {
      const current = await fetch(`${baseUrl}/api/v1/weekly/current?scope=current&limit=100`);
      assert.equal(current.status, 500);
      assert.notEqual(current.headers.get("x-weekly-cache"), "HIT");
    }
  });
});
