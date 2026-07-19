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
  await mkdir(path.join(dir, "by-id"), { recursive: true });
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
    generation_id: "sha256:visibility-contract",
    item_count: items.length,
    items,
  });
  await writeJson(path.join(dir, "manifest.json"), {
    schema_version: "weekly_activity_miniprogram_api.v1",
    generated_at: "2026-07-18T19:58:51+08:00",
    generation_id: "sha256:visibility-contract",
    item_count: items.length,
    window_start: "2026-07-18",
    window_end: "2026-07-31",
  });
  for (const item of items) {
    await writeJson(path.join(dir, "by-id", `${item.id}.json`), {
      schema_version: "weekly_activity_miniprogram_detail.v1",
      generated_at: "2026-07-18T19:58:51+08:00",
      generation_id: "sha256:visibility-contract",
      item,
    });
  }
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
  assert.equal(current.generationId, "sha256:visibility-contract");
  assert.equal(cities.generationId, current.generationId);
  assert.equal(dates.generationId, current.generationId);
  assert.equal(cities.scope, "current");
  assert.equal(cities.item_count, current.page.total);
  assert.deepEqual(cityCounts(cities), { beijing: 2, shanghai: 2 });
  assert.equal(dates.scope, "current");
  assert.equal(dates.item_count, current.page.total);
  assert.ok(dates.date_count >= 4);
});

test("manifest, current and facets fail closed when package generation files drift", async () => {
  const dir = await createVisibilityFixture();
  const currentPath = path.join(dir, "current.json");
  const current = JSON.parse(await (await import("node:fs/promises")).readFile(currentPath, "utf8"));
  current.generation_id = "sha256:different-current";
  await writeJson(currentPath, current);
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  await assert.rejects(() => store.getManifest(), /generation/i);
  await assert.rejects(() => store.getCurrent({ limit: 100 }), /generation/i);
  await assert.rejects(() => store.getCities(), /generation/i);
  await assert.rejects(() => store.getDates(), /generation/i);
});

test("detail and batch never trust a by-id file from another generation", async () => {
  const dir = await createVisibilityFixture();
  const detailPath = path.join(dir, "by-id", "friday-shanghai.json");
  const stale = JSON.parse(await (await import("node:fs/promises")).readFile(detailPath, "utf8"));
  stale.generation_id = "sha256:older-detail";
  stale.item.title = "stale by-id title";
  await writeJson(detailPath, stale);
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  const detail = await store.getItem("friday-shanghai", { generationId: "sha256:visibility-contract" });
  assert.equal(detail.title, "friday-shanghai techno club night");
  assert.equal(detail.generationId, "sha256:visibility-contract");

  const batch = await store.getItemsByIds(
    ["friday-shanghai", "saturday-shanghai"],
    { generationId: "sha256:visibility-contract" },
  );
  assert.equal(batch.generationId, "sha256:visibility-contract");
  assert.deepEqual(batch.items.map((item) => item.title), [
    "friday-shanghai techno club night",
    "saturday-shanghai techno club night",
  ]);

  await assert.rejects(
    () => store.getItem("friday-shanghai", { generationId: "sha256:wrong-client-generation" }),
    /requested generation/i,
  );
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

test("the public all-city sentinel is identical to an omitted city filter", async () => {
  const dir = await createVisibilityFixture();
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });
  const window = { dateStart: "2026-07-24", dateEnd: "2026-07-26", limit: 100 };

  const implicitAll = await store.getCurrent(window);
  const explicitAll = await store.getCurrent({ ...window, cityKey: "all" });

  assert.equal(explicitAll.filters.cityKey, "all");
  assert.equal(explicitAll.page.total, implicitAll.page.total);
  assert.deepEqual(explicitAll.items.map((item) => item.id), implicitAll.items.map((item) => item.id));
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

test("multi-city events appear in every matching facet and list projection", async () => {
  const dir = await createVisibilityFixture();
  const currentPath = path.join(dir, "current.json");
  const current = JSON.parse(await (await import("node:fs/promises")).readFile(currentPath, "utf8"));
  current.items.push({
    ...event("henan-tour", "kaifeng", "2026-07-24"),
    city_keys: ["kaifeng", "zhengzhou"],
    cityKeys: ["zhengzhou", "luoyang"],
    city: ["开封", "郑州", "洛阳"],
  });
  current.item_count = current.items.length;
  await writeJson(currentPath, current);
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  const zhengzhou = await store.getCurrent({ cityKey: "zhengzhou", limit: 100 });
  const luoyang = await store.getCurrent({ cityKey: "luoyang", limit: 100 });
  const facets = await store.getCities();
  const counts = cityCounts(facets);

  assert.equal(zhengzhou.page.total, 1);
  assert.equal(luoyang.page.total, 1);
  assert.equal(counts.zhengzhou, 1);
  assert.equal(counts.luoyang, 1);
});

test("dedupe unions every city alias instead of dropping secondary tour stops", async () => {
  const dir = await createVisibilityFixture();
  const currentPath = path.join(dir, "current.json");
  const current = JSON.parse(await (await import("node:fs/promises")).readFile(currentPath, "utf8"));
  current.items.push(
    {
      ...event("tour-copy-a", "shanghai", "2026-07-25"),
      title: "Three City Techno Tour",
      city_keys: ["shanghai", "beijing"],
      city: ["上海", "北京"],
    },
    {
      ...event("tour-copy-b", "shanghai", "2026-07-25"),
      title: "Three City Techno Tour",
      city_keys: ["shanghai", "guangzhou"],
      city: ["上海", "广州"],
    },
  );
  current.item_count = current.items.length;
  await writeJson(currentPath, current);
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  const list = await store.getCurrent({ cityKey: "shanghai", limit: 100 });
  const tour = list.items.find((item) => item.title === "Three City Techno Tour");
  const facets = cityCounts(await store.getCities());

  assert.ok(tour);
  assert.deepEqual([...tour.city_keys].sort(), ["beijing", "guangzhou", "shanghai"]);
  assert.deepEqual([...tour.city].sort(), ["上海", "北京", "广州"].sort());
  assert.equal(facets.beijing >= 1, true);
  assert.equal(facets.guangzhou, 1);
  assert.equal(facets.shanghai >= 1, true);
});

test("date visibility treats parser guesses as discrete and fails closed on undated current rows", async () => {
  const dir = await createVisibilityFixture();
  const currentPath = path.join(dir, "current.json");
  const current = JSON.parse(await (await import("node:fs/promises")).readFile(currentPath, "utf8"));
  current.items.push(
    {
      id: "sparse-parser-dates",
      title: "Sparse parser dates techno",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
      quality_status: "READY",
      venue: ["Test Club"],
    },
    {
      id: "explicit-range-with-parser-noise",
      title: "Explicit range techno",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      event_date_start: "2026-07-24",
      event_date_end: "2026-07-26",
      event_date_iso_guess: "2026-07-24",
      event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
      quality_status: "READY",
      venue: ["Test Club"],
    },
    {
      id: "undated-ready",
      title: "Undated techno",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      quality_status: "READY",
      venue: ["Test Club"],
    },
  );
  current.item_count = current.items.length;
  await writeJson(currentPath, current);
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-07-19" });

  const gapDate = await store.getCurrent({ date: "2026-07-27", limit: 100 });
  const rangeDate = await store.getCurrent({ date: "2026-07-25", limit: 100 });
  const secondSparseDate = await store.getCurrent({ date: "2026-07-31", limit: 100 });
  const currentScope = await store.getCurrent({ scope: "current", limit: 100 });
  const packageScope = await store.getCurrent({ scope: "package", limit: 100 });
  const dates = await store.getDates({ scope: "current" });

  assert.equal(gapDate.items.some((item) => item.id === "sparse-parser-dates"), false);
  assert.equal(rangeDate.items.some((item) => item.id === "explicit-range-with-parser-noise"), true);
  assert.equal(secondSparseDate.items.some((item) => item.id === "sparse-parser-dates"), true);
  assert.equal(secondSparseDate.items.some((item) => item.id === "explicit-range-with-parser-noise"), false);
  assert.equal(currentScope.items.some((item) => item.id === "undated-ready"), false);
  assert.equal(packageScope.items.some((item) => item.id === "undated-ready"), true);
  assert.equal(dates.dates.some((entry) => entry.date === "2026-07-27" && entry.item_count > 1), false);
});
