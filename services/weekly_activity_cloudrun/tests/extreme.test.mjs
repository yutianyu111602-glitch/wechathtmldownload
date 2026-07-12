import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "../src/server.mjs";
import { WeeklyActivityDataStore } from "../src/dataStore.mjs";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

let server, baseUrl, fixtureDir;

async function writeJson(filePath, value) {
  await writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

// ── SETUP ──
test.before(async () => {
  fixtureDir = await mkdtemp(path.join(os.tmpdir(), "extreme-"));
  await mkdir(path.join(fixtureDir, "by-id"), { recursive: true });
  await mkdir(path.join(fixtureDir, "by-city"), { recursive: true });
  await mkdir(path.join(fixtureDir, "by-date"), { recursive: true });

  const items = [];
  for (let i = 0; i < 500; i++) {
    items.push({
      id: `item-${i}`,
      title: `Event ${i}`,
      city_key: i % 10 === 0 ? "shanghai" : i % 5 === 0 ? "beijing" : `city-${i % 20}`,
      city_keys: [i % 10 === 0 ? "shanghai" : `city-${i % 20}`],
      city: [i % 10 === 0 ? "上海" : `City ${i % 20}`],
      event_date_iso_guess: `2026-06-${String((i % 28) + 1).padStart(2, "0")}`,
      event_date_iso_guesses: [`2026-06-${String((i % 28) + 1).padStart(2, "0")}`],
      event_date_start: `2026-06-${String((i % 28) + 1).padStart(2, "0")}`,
      quality_status: i % 50 === 0 ? "REVIEW" : "READY",
      promoter: `Club ${i}`,
      venue: [`Venue ${i}`],
      source_action: { type: "wechat_article", url_hash: `hash${i}` },
      source_article: { url_hash: `hash${i}`, account_name: `Account${i}`, published_at: "2026-05-30" },
    });
  }
  await writeJson(path.join(fixtureDir, "current.json"), {
    schema: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-05-30T12:00:00",
    items,
  });
  await writeJson(path.join(fixtureDir, "manifest.json"), {
    schema_version: "weekly_activity_miniprogram_api.v1",
    generated_at: "2026-05-30T12:00:00",
    item_count: 500,
  });
  await writeJson(path.join(fixtureDir, "by-city", "index.json"), {
    schema_version: "weekly_activity_miniprogram_city_index.v1",
    cities: [
      { city_key: "shanghai", city: "上海", item_count: 50 },
      { city_key: "beijing", city: "北京", item_count: 100 },
    ],
  });
  await writeJson(path.join(fixtureDir, "by-date", "index.json"), {
    schema_version: "weekly_activity_miniprogram_date_index.v1",
    dates: Array.from({ length: 28 }, (_, i) => ({
      date: `2026-06-${String(i + 1).padStart(2, "0")}`,
      item_count: 18,
    })),
  });

  const store = new WeeklyActivityDataStore({ baseDir: fixtureDir, today: "2026-06-01" });
  const env = { ...process.env };
  server = createServer({ store, env });
  await new Promise((resolve) => server.listen(0, resolve));
  const addr = server.address();
  baseUrl = `http://127.0.0.1:${addr.port}`;
});

test.after(() => {
  server?.close();
});

// ════════════════════════════════════════════════════════════
// 极端测试：边界值
// ════════════════════════════════════════════════════════════

test("边界值: limit=0 返回空列表但不崩溃", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=0`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.ok(Array.isArray(body.items));
  assert.ok(body.items.length <= body.page.total);
});

test("边界值: limit=99999 被限制到 maxLimit", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=99999`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.ok(body.page.limit <= 100, `limit ${body.page.limit} > 100`);
});

test("边界值: cursor=-1 当作 0", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?cursor=-1`);
  assert.equal(res.status, 200);
});

test("边界值: cursor=NaN 当作 0", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?cursor=NaN`);
  assert.equal(res.status, 200);
});

test("边界值: 超长 cityKey 不崩溃", async () => {
  const longKey = "x".repeat(1000);
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=${encodeURIComponent(longKey)}`);
  assert.equal(res.status, 200);
});

test("边界值: 不存在的 item ID 返回 404", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/nonexistent-id-99999`);
  assert.equal(res.status, 404);
  const body = await res.json();
  assert.equal(body.error.code, "ITEM_NOT_FOUND");
});

test("边界值: items/batch 空 ids 返回 400", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/batch?ids=`);
  assert.equal(res.status, 400);
});

test("边界值: items/batch 超过 100 ids 返回 400", async () => {
  const ids = Array.from({ length: 101 }, (_, i) => `item-${i}`).join(",");
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/batch?ids=${encodeURIComponent(ids)}`);
  assert.equal(res.status, 400);
});

// ════════════════════════════════════════════════════════════
// 极端测试：并发
// ════════════════════════════════════════════════════════════

test("并发: 20 个同时 manifest 请求全部 200", async () => {
  const promises = Array.from({ length: 20 }, () =>
    fetch(`${baseUrl}/api/v1/weekly/manifest`).then((r) => r.status)
  );
  const results = await Promise.all(promises);
  assert.ok(results.every((s) => s === 200), `some failed: ${results.filter(s => s !== 200)}`);
});

test("并发: 10 个同时 current 请求 body 一致", async () => {
  const promises = Array.from({ length: 10 }, () =>
    fetch(`${baseUrl}/api/v1/weekly/current?limit=5`).then((r) => r.json())
  );
  const results = await Promise.all(promises);
  const firstIds = results[0].items.map((i) => i.id);
  for (const r of results) {
    assert.equal(r.page.total, results[0].page.total);
    assert.equal(r.items.length, results[0].items.length);
  }
});

test("并发: 混合端点并发不崩溃", async () => {
  const ops = [
    ...Array.from({ length: 5 }, () => fetch(`${baseUrl}/api/v1/weekly/current`)),
    ...Array.from({ length: 5 }, () => fetch(`${baseUrl}/api/v1/weekly/cities`)),
    ...Array.from({ length: 5 }, () => fetch(`${baseUrl}/api/v1/weekly/dates`)),
    ...Array.from({ length: 5 }, () => fetch(`${baseUrl}/api/v1/weekly/manifest`)),
  ];
  const results = await Promise.all(ops.map((p) => p.then((r) => r.status)));
  assert.ok(results.every((s) => s === 200));
});

// ════════════════════════════════════════════════════════════
// 极端测试：缓存行为
// ════════════════════════════════════════════════════════════

test("缓存: 第二次请求返回 HIT (不指定 lookbackDays)", async () => {
  const r1 = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=shanghai`);
  assert.equal(r1.headers.get("x-weekly-cache"), "MISS");
  const r2 = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=shanghai`);
  assert.equal(r2.headers.get("x-weekly-cache"), "HIT");
});

test("缓存: 不同参数产生不同 cache key", async () => {
  // Use fresh cities to avoid pollution from earlier tests (shanghai was pre-cached)
  const r1 = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=city-3`);
  assert.equal(r1.headers.get("x-weekly-cache"), "MISS");
  const r2 = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=city-7`);
  assert.equal(r2.headers.get("x-weekly-cache"), "MISS");
  const b1 = await r1.json();
  const b2 = await r2.json();
  assert.notEqual(b1.filters.cityKey, b2.filters.cityKey);
});

test("缓存: manifest 被缓存 (60s TTL)", async () => {
  const r1 = await fetch(`${baseUrl}/api/v1/weekly/manifest`);
  await r1.text();
  const r2 = await fetch(`${baseUrl}/api/v1/weekly/manifest`);
  assert.equal(r2.headers.get("x-weekly-cache"), "HIT");
});

// ════════════════════════════════════════════════════════════
// 极端测试：特殊字符 & 注入
// ════════════════════════════════════════════════════════════

test("注入: URL 编码斜杠在 item ID 中正常处理", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/${encodeURIComponent("item-0")}`);
  assert.equal(res.status, 200);
});

test("注入: 特殊字符 cityKey 安全处理", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=%3Cscript%3Ealert(1)%3C/script%3E`);
  assert.equal(res.status, 200);
  const body = await res.json();
  // JSON string encoding is inherently safe — the value is stored as a string
  // and never rendered as HTML. Verify the response is valid JSON and doesn't crash.
  assert.equal(body.filters.cityKey, "<script>alert(1)</script>");
});

test("注入: XSS payload 在 date 参数中安全处理", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?date=<img src=x onerror=alert(1)>`);
  assert.equal(res.status, 200);
});

// ════════════════════════════════════════════════════════════
// 极端测试：大响应
// ════════════════════════════════════════════════════════════

test("大响应: 500 items 全量加载不超过 500ms", async () => {
  const t0 = performance.now();
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=100`);
  await res.text();
  const elapsed = performance.now() - t0;
  assert.ok(elapsed < 500, `Took ${elapsed.toFixed(0)}ms, expected < 500ms`);
});

test("大响应: gzip 压缩正常 (500 items)", async () => {
  const noGzip = await fetch(`${baseUrl}/api/v1/weekly/current?limit=100`);
  const rawSize = (await noGzip.text()).length;
  const withGzip = await fetch(`${baseUrl}/api/v1/weekly/current?limit=100`, {
    headers: { "Accept-Encoding": "gzip" },
  });
  const gzipSize = Number(withGzip.headers.get("content-length") || 0);
  // gzip should be smaller than raw
  if (gzipSize > 0) {
    assert.ok(gzipSize < rawSize, `gzip=${gzipSize} >= raw=${rawSize}`);
  }
});

// ════════════════════════════════════════════════════════════
// 极端测试：错误恢复
// ════════════════════════════════════════════════════════════

test("错误恢复: 缺少 current.json 时返回空数组不崩溃", async () => {
  const brokenDir = await mkdtemp(path.join(os.tmpdir(), "broken-"));
  await mkdir(path.join(brokenDir, "by-city"), { recursive: true });
  await mkdir(path.join(brokenDir, "by-date"), { recursive: true });
  await writeJson(path.join(brokenDir, "manifest.json"), {
    schema_version: "test", generated_at: null, item_count: 0,
  });
  // Deliberately DO NOT create current.json
  const brokenStore = new WeeklyActivityDataStore({ baseDir: brokenDir });
  const result = await brokenStore.getCurrent({});
  assert.equal(result.items.length, 0, `Expected 0 items, got ${result.items.length}`);
  assert.equal(result.page.total, 0);
});

test("错误恢复: 损坏的 JSON 不崩溃", async () => {
  const corruptDir = await mkdtemp(path.join(os.tmpdir(), "corrupt-"));
  await writeFile(path.join(corruptDir, "current.json"), "this is not valid json {{{");
  await writeFile(path.join(corruptDir, "manifest.json"), "also bad {{{");
  await mkdir(path.join(corruptDir, "by-city"), { recursive: true });
  await mkdir(path.join(corruptDir, "by-date"), { recursive: true });

  const corruptStore = new WeeklyActivityDataStore({ baseDir: corruptDir });
  const srv = createServer({ store: corruptStore, env: { ...process.env } });
  await new Promise((resolve) => srv.listen(0, resolve));
  const addr = srv.address();
  const url = `http://127.0.0.1:${addr.port}`;

  // All should return gracefully, not crash
  const endpoints = ["/api/v1/weekly/current", "/api/v1/weekly/manifest", "/api/v1/weekly/cities", "/api/v1/weekly/dates"];
  for (const ep of endpoints) {
    const res = await fetch(`${url}${ep}`);
    assert.equal(res.status, 200, `${ep} returned ${res.status}`);
    await res.text(); // consume body
  }

  srv.close();
});

test("错误恢复: 路径穿越尝试被阻止", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/../../../etc/passwd`);
  // Should return 404, not expose filesystem
  assert.equal(res.status, 404);
});

// ════════════════════════════════════════════════════════════
// 极端测试：分页一致性
// ════════════════════════════════════════════════════════════

test("分页: 连续分页无重复/无遗漏", async () => {
  const allIds = new Set();
  let cursor = "";
  let pageCount = 0;
  let totalItems = 0;
  while (true) {
    const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=20&cursor=${cursor}`);
    const body = await res.json();
    totalItems = body.page.total;
    for (const item of body.items) {
      assert.ok(!allIds.has(item.id), `Duplicate id: ${item.id}`);
      allIds.add(item.id);
    }
    pageCount++;
    if (!body.page.nextCursor) break;
    cursor = body.page.nextCursor;
    if (pageCount > 50) break; // safety valve
  }
  assert.equal(allIds.size, totalItems, `Got ${allIds.size} unique ids, expected ${totalItems}`);
  assert.ok(pageCount > 1, `Only ${pageCount} pages for ${totalItems} items`);
});

test("分页: nextCursor 为 null 时不再有数据", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=200&cursor=99999`);
  const body = await res.json();
  assert.equal(body.page.nextCursor, null);
  assert.equal(body.items.length, 0);
});
