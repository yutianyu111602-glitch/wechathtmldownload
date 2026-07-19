import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { WeeklyActivityDataStore } from "../src/dataStore.mjs";

async function writeJson(filePath, value) {
  await writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

function event(id, cityKey, start, end = start) {
  return {
    id,
    title: `${id} techno club night`,
    city_key: cityKey,
    city_keys: [cityKey],
    city: [cityKey === "shanghai" ? "上海" : "北京"],
    event_date_start: start,
    event_date_end: end,
    event_date_iso_guess: start,
    quality_status: "READY",
    venue: ["Test Club"],
  };
}

async function createVisibilityFixture() {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-visibility-contract-"));
  await mkdir(path.join(dir, "by-city"), { recursive: true });
  await mkdir(path.join(dir, "by-date"), { recursive: true });
  const items = [
    event("expired-shanghai", "shanghai", "2026-07-18"),
    event("friday-shanghai", "shanghai", "2026-07-24"),
    event("saturday-shanghai", "shanghai", "2026-07-25"),
    event("sunday-beijing", "beijing", "2026-07-26"),
    event("range-beijing", "beijing", "2026-07-23", "2026-07-27"),
  ];
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-07-18T19:58:51+08:00",
    item_count: items.length,
    items,
  });
  // Deliberately package-wide and stale. Default facets must not expose it.
  await writeJson(path.join(dir, "by-city", "index.json"), {
    schema_version: "weekly_activity_miniprogram_city_index.v1",
    generated_at: "2026-07-18T19:58:51+08:00",
    item_count: 999,
    cities: [
      { city_key: "shanghai", city: "上海", item_count: 777 },
      { city_key: "beijing", city: "北京", item_count: 222 },
    ],
  });
  return dir;
}

function cityCounts(payload) {
  return Object.fromEntries((payload.cities || []).map((entry) => [entry.city_key, entry.item_count]));
}

test("current, city and date projections share one explicit visibility window", async () => {
  const dir = await createVisibilityFixture();
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  const current = await store.getCurrent({ limit: 100 });
  const cities = await store.getCities();
  const dates = await store.getDates();

  assert.equal(current.page.total, 4);
  assert.equal(cities.scope, "current");
  assert.equal(cities.item_count, current.page.total);
  assert.deepEqual(cityCounts(cities), { beijing: 2, shanghai: 2 });
  assert.equal(dates.scope, "current");
  assert.equal(dates.item_count, current.page.total);
  assert.ok(dates.date_count >= 4);
});

test("weekend range is an inclusive projection and facets match its list total", async () => {
  const dir = await createVisibilityFixture();
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });
  const window = { dateStart: "2026-07-24", dateEnd: "2026-07-26" };

  const current = await store.getCurrent({ ...window, limit: 100 });
  const cities = await store.getCities(window);
  const dates = await store.getDates(window);

  assert.deepEqual(current.items.map((item) => item.id), [
    "range-beijing",
    "friday-shanghai",
    "saturday-shanghai",
    "sunday-beijing",
  ]);
  assert.equal(current.filters.dateStart, window.dateStart);
  assert.equal(current.filters.dateEnd, window.dateEnd);
  assert.equal(cities.item_count, current.page.total);
  assert.deepEqual(cityCounts(cities), { beijing: 2, shanghai: 2 });
  assert.equal(dates.item_count, current.page.total);
  assert.ok(dates.dates.every((entry) => entry.date >= window.dateStart && entry.date <= window.dateEnd));
});

test("package scope preserves history without leaking it into current facets", async () => {
  const dir = await createVisibilityFixture();
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  const current = await store.getCurrent({ scope: "package", limit: 100 });
  const cities = await store.getCities({ scope: "package" });

  assert.equal(current.page.total, 5);
  assert.equal(current.filters.scope, "package");
  assert.equal(cities.scope, "package");
  assert.equal(cities.item_count, 5);
  assert.deepEqual(cityCounts(cities), { beijing: 2, shanghai: 3 });
});
