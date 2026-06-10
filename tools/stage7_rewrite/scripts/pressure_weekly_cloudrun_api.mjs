#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

function numberArg(name, fallback) {
  const value = Number(argValue(name, ""));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return Math.round(sorted[index]);
}

async function requestJson(baseUrl, route, timeoutMs) {
  const controller = new AbortController();
  const started = performance.now();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${baseUrl}${route}`, { signal: controller.signal });
    const text = await res.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { raw: text.slice(0, 200) };
    }
    return {
      ok: res.ok,
      status: res.status,
      ms: performance.now() - started,
      route,
      body,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function collectRoutes(baseUrl, timeoutMs) {
  const current = await requestJson(baseUrl, "/api/v1/weekly/current?limit=100", timeoutMs);
  if (!current.ok) throw new Error(`current probe failed: HTTP ${current.status}`);
  const items = Array.isArray(current.body?.items) ? current.body.items : [];
  const next = current.body?.page?.nextCursor;
  const second = next ? await requestJson(baseUrl, `/api/v1/weekly/current?limit=100&cursor=${encodeURIComponent(next)}`, timeoutMs) : null;
  const secondItems = Array.isArray(second?.body?.items) ? second.body.items : [];
  const allItems = [...items, ...secondItems];
  const sampleIds = allItems.slice(0, 24).map((item) => item.id).filter(Boolean);
  const sourceHashes = allItems.slice(0, 24).map((item) => item.sourceHash || item.source_article?.url_hash).filter(Boolean);
  const batchIds = sampleIds.slice(0, 10).join(",");
  const routes = [
    "/api/v1/weekly/manifest",
    "/api/v1/weekly/current?limit=1",
    "/api/v1/weekly/current?limit=50",
    "/api/v1/weekly/current?limit=100",
    "/api/v1/weekly/current?limit=100&cursor=100",
    "/api/v1/weekly/cities",
    "/api/v1/weekly/dates",
  ];
  if (batchIds) routes.push(`/api/v1/weekly/items/batch?ids=${encodeURIComponent(batchIds)}`);
  for (const id of sampleIds.slice(0, 12)) routes.push(`/api/v1/weekly/items/${encodeURIComponent(id)}`);
  for (const hash of sourceHashes.slice(0, 6)) routes.push(`/api/v1/weekly/source/${encodeURIComponent(hash)}`);
  return { routes, itemCount: allItems.length, pageTotal: current.body?.page?.total ?? null };
}

async function runStage(baseUrl, routes, concurrency, durationMs, timeoutMs) {
  const results = [];
  let index = 0;
  let running = true;
  const started = performance.now();
  const workers = Array.from({ length: concurrency }, async () => {
    while (running) {
      const route = routes[index % routes.length];
      index += 1;
      try {
        results.push(await requestJson(baseUrl, route, timeoutMs));
      } catch (error) {
        results.push({ ok: false, status: 0, ms: timeoutMs, route, error: error instanceof Error ? error.message : String(error) });
      }
      if (performance.now() - started >= durationMs) running = false;
    }
  });
  await Promise.all(workers);
  const latencies = results.map((r) => r.ms).filter(Number.isFinite);
  const failures = results.filter((r) => !r.ok);
  return {
    concurrency,
    durationMs,
    requests: results.length,
    failures: failures.length,
    statusCounts: results.reduce((acc, r) => {
      acc[String(r.status)] = (acc[String(r.status)] || 0) + 1;
      return acc;
    }, {}),
    latencyMs: {
      min: Math.round(Math.min(...latencies)),
      p50: percentile(latencies, 50),
      p90: percentile(latencies, 90),
      p95: percentile(latencies, 95),
      p99: percentile(latencies, 99),
      max: Math.round(Math.max(...latencies)),
    },
    sampleFailures: failures.slice(0, 10).map((r) => ({ route: r.route, status: r.status, error: r.error || r.body?.error || "" })),
  };
}

async function main() {
  const baseUrl = argValue("--base-url", "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com").replace(/\/+$/, "");
  const outDir = path.resolve(argValue("--out-dir", "tools/stage7_rewrite/reports/pressure_weekly_cloudrun_api"));
  const timeoutMs = numberArg("--timeout-ms", 15000);
  const durationMs = numberArg("--stage-ms", 15000);
  const concurrencies = argValue("--concurrency", "2,4,8,12")
    .split(",")
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value) && value > 0);
  await fs.mkdir(outDir, { recursive: true });
  const { routes, itemCount, pageTotal } = await collectRoutes(baseUrl, timeoutMs);
  const stages = [];
  for (const concurrency of concurrencies) {
    stages.push(await runStage(baseUrl, routes, concurrency, durationMs, timeoutMs));
  }
  const totals = stages.reduce(
    (acc, stage) => {
      acc.requests += stage.requests;
      acc.failures += stage.failures;
      return acc;
    },
    { requests: 0, failures: 0 },
  );
  const report = {
    schemaVersion: "weekly_cloudrun_pressure_probe.v1",
    generatedAt: new Date().toISOString(),
    baseUrl,
    routeCount: routes.length,
    itemCount,
    pageTotal,
    concurrencies,
    timeoutMs,
    stages,
    totals,
    ok: totals.failures === 0,
  };
  await fs.writeFile(path.join(outDir, "pressure_weekly_cloudrun_api.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
  await fs.writeFile(
    path.join(outDir, "pressure_weekly_cloudrun_api.md"),
    [
      "# Weekly CloudRun Pressure Probe",
      "",
      `- ok: \`${report.ok}\``,
      `- base_url: \`${baseUrl}\``,
      `- routes: \`${routes.length}\``,
      `- requests: \`${totals.requests}\``,
      `- failures: \`${totals.failures}\``,
      `- item_count_sampled: \`${itemCount}\``,
      `- page_total: \`${pageTotal}\``,
      "",
      ...stages.map((stage) => `- c=${stage.concurrency}: requests=${stage.requests}, failures=${stage.failures}, p95=${stage.latencyMs.p95}ms, max=${stage.latencyMs.max}ms`),
      "",
    ].join("\n"),
    "utf8",
  );
  console.log(JSON.stringify({ ok: report.ok, outDir, totals, stages: stages.map((s) => ({ concurrency: s.concurrency, requests: s.requests, failures: s.failures, p95: s.latencyMs.p95, max: s.latencyMs.max })) }, null, 2));
  process.exit(report.ok ? 0 : 1);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exit(1);
});
