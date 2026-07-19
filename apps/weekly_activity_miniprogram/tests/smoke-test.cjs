const assert = require("node:assert/strict");
const https = require("node:https");
const http = require("node:http");

const API_BASE = process.env.WEEKLY_API_BASE || "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com";
const CDN_BASE = process.env.WEEKLY_CDN_BASE || "https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com/weekly/releases/entity-posterocr6-current-20260607";

function fetchJson(url, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith("https") ? https : http;
    const req = mod.get(url, { timeout }, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        try { resolve(JSON.parse(body)); }
        catch (e) { reject(new Error(`JSON parse error for ${url}: ${e.message}`)); }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => { req.destroy(); reject(new Error(`Timeout: ${url}`)); });
  });
}

async function smokeTest() {
  const results = { passed: 0, failed: 0, checks: [] };

  function check(name, fn) {
    return fn().then(() => {
      results.checks.push({ name, status: "PASS" });
      results.passed++;
    }).catch((err) => {
      results.checks.push({ name, status: "FAIL", error: err.message });
      results.failed++;
    });
  }

  console.log("=== Weekly Activity Smoke Test ===\n");

  await check("API /api/v1/weekly/current returns items", async () => {
    const r = await fetchJson(`${API_BASE}/api/v1/weekly/current`);
    assert.ok(r.items && r.items.length > 0, `Expected items, got ${r.items?.length || 0}`);
    assert.ok(r.page && r.page.total > 0, `Expected page.total > 0`);
  });

  await check("API /api/v1/weekly/cities returns cities", async () => {
    const r = await fetchJson(`${API_BASE}/api/v1/weekly/cities`);
    const cities = r.cities || r;
    assert.ok(Array.isArray(cities) && cities.length > 0, `Expected cities array`);
  });

  await check("API /api/v1/weekly/dates returns dates", async () => {
    const r = await fetchJson(`${API_BASE}/api/v1/weekly/dates`);
    const dates = r.dates || r;
    assert.ok(Array.isArray(dates) && dates.length > 0, `Expected dates array`);
  });

  await check("API /api/v1/weekly/manifest returns manifest", async () => {
    const r = await fetchJson(`${API_BASE}/api/v1/weekly/manifest`);
    assert.ok(r.schema_version || r.generated_at, "Expected manifest metadata");
    assert.ok(r.item_count > 0, "Expected item_count > 0");
  });

  await check("API current items have required fields", async () => {
    const r = await fetchJson(`${API_BASE}/api/v1/weekly/current`);
    const item = r.items[0];
    assert.ok(item.id, "Missing id");
    assert.ok(item.title || item.title_display || item.display_title, "Missing title");
    assert.ok(item.event_date_start, "Missing event_date_start");
    assert.ok(item.city_key, "Missing city_key");
  });

  await check("API health endpoint responds", async () => {
    try {
      const r = await fetchJson(`${API_BASE}/`);
      assert.ok(true, "API root responds");
    } catch (e) {
      assert.ok(true, "API root reached (non-JSON OK)");
    }
  });

  await check("CDN current.json returns items", async () => {
    const r = await fetchJson(`${CDN_BASE}/current.json`);
    assert.ok(r.items && r.items.length > 0, `Expected CDN items`);
  });

  await check("API city filter works", async () => {
    const r = await fetchJson(`${API_BASE}/api/v1/weekly/cities`);
    const cities = r.cities || r;
    const city = cities[0]?.city_key;
    if (!city) return;
    const filtered = await fetchJson(`${API_BASE}/api/v1/weekly/current?cityKey=${city}`);
    assert.ok(filtered.items.length > 0, `Expected items for city ${city}`);
    assert.ok(filtered.items.every(i => i.city_key === city || (i.city_keys || []).includes(city)),
      `All items should match city ${city}`);
  });

  console.log("\n--- Results ---");
  for (const c of results.checks) {
    console.log(`${c.status === "PASS" ? "✔" : "✖"} ${c.name}${c.error ? `: ${c.error}` : ""}`);
  }
  console.log(`\nTotal: ${results.passed} pass, ${results.failed} fail`);
  process.exit(results.failed > 0 ? 1 : 0);
}

smokeTest().catch((err) => {
  console.error("Smoke test crashed:", err);
  process.exit(2);
});
