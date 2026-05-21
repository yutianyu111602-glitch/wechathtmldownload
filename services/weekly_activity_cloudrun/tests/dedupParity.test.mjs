import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { WeeklyActivityDataStore } from "../src/dataStore.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(moduleDir, "../../..");
const specPath = path.join(repoRoot, "tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json");

async function writeJson(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

function ready(item) {
  return {
    quality_status: "READY",
    event_date_iso_guesses: [item.event_date_start || item.event_date_iso_guess],
    city_keys: [item.city_key],
    ...item,
  };
}

test("CloudRun current feed dedupe follows weekly_dedup_spec.v1", async () => {
  const spec = JSON.parse(await readFile(specPath, "utf8"));
  assert.equal(spec.schema_version, "weekly_dedup_spec.v1");

  for (const item of spec.cases) {
    const dir = await mkdtemp(path.join(os.tmpdir(), `weekly-dedup-${item.id}-`));
    await writeJson(path.join(dir, "manifest.json"), {
      schema_version: "weekly_activity_miniprogram_api.v1",
      generated_at: "2026-05-21T00:00:00Z",
      item_count: 2,
    });
    await writeJson(path.join(dir, "current.json"), {
      schema_version: "weekly_activity_miniprogram_current.v1",
      generated_at: "2026-05-21T00:00:00Z",
      item_count: 2,
      items: [ready(item.left), ready(item.right)],
    });

    const store = new WeeklyActivityDataStore({ baseDir: dir });
    const current = await store.getCurrent({ limit: 10 });
    assert.equal(
      current.page.total,
      item.expected_duplicate ? 1 : 2,
      `${item.id}: ${item.reason}`,
    );
  }
});
