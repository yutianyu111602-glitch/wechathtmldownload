import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { chromium } from "playwright";
import { createServer } from "../src/server.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(moduleDir, "../../..");
const defaultCandidateDb = path.join(
  repoRoot,
  "reports/atlas_serving_activity_current_fullcomplete_strict_20260525-1442/atlas_serving.sqlite",
);
const defaultOutDir = path.join(repoRoot, "reports/atlas_serving_activity_current_fullcomplete_strict_20260525-1442/api_smoke");
const defaultEntityMergeGroups = path.join(
  repoRoot,
  "reports/atlas_entity_merge_plan_ocr_full_fourthpass_current/entity_merge_groups_report_only.jsonl",
);
const defaultSoundSystemEvidence = path.join(
  repoRoot,
  "reports/atlas_venue_sound_system_evidence_current/venue_sound_system_evidence.jsonl",
);

function text(value) {
  return String(value ?? "").trim();
}

function parseArgs(argv = process.argv.slice(2)) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
    const [rawKey, inlineValue] = arg.slice(2).split("=", 2);
    const key = rawKey.replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    if (inlineValue !== undefined) {
      options[key] = inlineValue;
    } else if (i + 1 < argv.length && !argv[i + 1].startsWith("--")) {
      options[key] = argv[i + 1];
      i += 1;
    } else {
      options[key] = true;
    }
  }
  return options;
}

function resolveRepoPath(value, fallback) {
  const raw = text(value) || fallback;
  return path.isAbsolute(raw) ? raw : path.resolve(repoRoot, raw);
}

function repoRelative(value) {
  return path.relative(repoRoot, value) || ".";
}

function nowIso() {
  return new Date().toISOString();
}

function statusOk(status) {
  return status >= 200 && status < 300;
}

function normalizeName(value) {
  return text(value).toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, "");
}

function resultName(row) {
  return text(row?.title || row?.item?.name || row?.item?.title || row?.item?.eid || row?.item?.evid);
}

function resultHasName(results, name) {
  const expected = normalizeName(name);
  return Array.isArray(results) && results.some((row) => normalizeName(resultName(row)).includes(expected));
}

function resultHasType(results, type, name = "") {
  const expectedType = normalizeName(type);
  const expectedName = normalizeName(name);
  return Array.isArray(results) && results.some((row) => {
    const actualType = normalizeName(row?.item?.type || row?.subject_type || row?.type);
    if (actualType !== expectedType) return false;
    return expectedName ? normalizeName(resultName(row)).includes(expectedName) : true;
  });
}

function resultHasEventCity(results, city) {
  const expectedCity = text(city);
  return Array.isArray(results) && results.some((row) => {
    const item = row?.item || {};
    const actualType = normalizeName(item.type || row?.subject_type || row?.type || row?.kind);
    return (actualType === "event" || actualType === "events") && text(item.city) === expectedCity;
  });
}

function publicPayloadHasLeak(value) {
  const serialized = JSON.stringify(value);
  return /[A-Z]:\\|file:\/\/|\.sqlite|entity_merge_groups_report_only\.jsonl|venue_sound_system_evidence\.jsonl|"source_url"|"raw_json"/i.test(serialized);
}

function relationshipCopyIsAllowed(value) {
  const serialized = JSON.stringify(value);
  return !serialized.includes("同台次数") && /关系分|关系得分|DJ 关系/.test(serialized);
}

function citySearchSummary(results, city) {
  const rows = Array.isArray(results) ? results : [];
  return {
    city,
    result_count: rows.length,
    event_city_match_rows: rows.filter((row) => {
      const item = row?.item || {};
      const actualType = normalizeName(item.type || row?.subject_type || row?.type || row?.kind);
      return (actualType === "event" || actualType === "events") && text(item.city) === city;
    }).length,
    sample_event_ids: rows
      .map((row) => text(row?.item?.evid || row?.item?.event_id || row?.item?.id))
      .filter(Boolean)
      .slice(0, 5),
  };
}

function safeJson(value) {
  return JSON.stringify(value, null, 2);
}

async function writeJson(filePath, payload) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${safeJson(payload)}\n`, "utf8");
}

async function writeText(filePath, body) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, body, "utf8");
}

function selectActivityEventSample(candidateDb) {
  const db = new Database(candidateDb, { readonly: true, fileMustExist: true });
  try {
    const withEvidence = db.prepare(`
      SELECT d.event_id, d.title, COUNT(e.evidence_ref_id) AS evidence_count
      FROM activity_event_detail d
      JOIN activity_evidence_ref e ON e.event_id = d.event_id
      GROUP BY d.event_id, d.title
      ORDER BY evidence_count DESC, d.event_id
      LIMIT 1
    `).get();
    if (withEvidence?.event_id) return withEvidence;
    const fallback = db.prepare(`
      SELECT event_id, title, 0 AS evidence_count
      FROM activity_event_detail
      ORDER BY event_id
      LIMIT 1
    `).get();
    return fallback || { event_id: "", title: "", evidence_count: 0 };
  } finally {
    db.close();
  }
}

async function requestJson(baseUrl, pathName) {
  const started = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetch(`${baseUrl}${pathName}`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const raw = await response.text();
    let json = null;
    try {
      json = raw ? JSON.parse(raw) : null;
    } catch {
      json = { parse_error: true, raw: raw.slice(0, 500) };
    }
    return {
      path: pathName,
      status: response.status,
      ok: statusOk(response.status) && !json?.parse_error,
      elapsed_ms: Number((performance.now() - started).toFixed(2)),
      json,
    };
  } catch (error) {
    return {
      path: pathName,
      status: 0,
      ok: false,
      elapsed_ms: Number((performance.now() - started).toFixed(2)),
      error: error?.message || String(error),
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function listen(server, host, port) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  return `http://${host}:${address.port}`;
}

async function close(server) {
  await new Promise((resolve) => server.close(resolve));
}

function buildApiMarkdown(payload) {
  const lines = [
    "# Atlas Serving Candidate Local API Smoke",
    "",
    `- generated_at: \`${payload.generated_at}\``,
    `- candidate_db: \`${payload.candidate_db}\``,
    `- base_url: \`${payload.base_url}\``,
    `- ok: \`${payload.ok}\``,
    "",
    "## Checks",
    "",
  ];
  for (const [key, value] of Object.entries(payload.checks)) {
    lines.push(`- ${key}: \`${value}\``);
  }
  lines.push("", "## Sample Activity Event", "");
  lines.push(`- event_id: \`${payload.activity_event_sample.event_id}\``);
  lines.push(`- title: \`${payload.activity_event_sample.title}\``);
  lines.push(`- evidence_count: \`${payload.activity_event_sample.evidence_count}\``);
  lines.push("", "## Boundary", "");
  lines.push("- production/cloudrun/neo4j/qdrant writes: `false`");
  lines.push("- llm/model/external-network calls: `false`");
  lines.push("");
  return lines.join("\n");
}

function buildBrowserMarkdown(payload) {
  const lines = [
    "# Atlas Serving Candidate Browser Smoke",
    "",
    `- generated_at: \`${payload.generated_at}\``,
    `- candidate_db: \`${payload.candidate_db}\``,
    `- local_url: \`${payload.local_url}\``,
    `- ok: \`${payload.ok}\``,
    `- title: \`${payload.title}\``,
    "",
    "## Checks",
    "",
  ];
  for (const [key, value] of Object.entries(payload.checks)) {
    lines.push(`- ${key}: \`${value}\``);
  }
  lines.push("", "## Rendered Counts", "");
  lines.push(`- Articles: \`${payload.rendered_counts.articles}\``);
  lines.push(`- Entities: \`${payload.rendered_counts.entities}\``);
  lines.push(`- Events: \`${payload.rendered_counts.events}\``);
  lines.push(`- Activity evidence refs: \`${payload.rendered_counts.activity_evidence_ref}\``);
  lines.push("", "## Evidence", "");
  lines.push(`- Screenshot: \`${payload.screenshot_path}\``);
  lines.push("", "## Boundary", "");
  lines.push("- production/cloudrun/neo4j/qdrant writes: `false`");
  lines.push("- llm/model/external-network calls: `false`");
  lines.push("");
  return lines.join("\n");
}

function checkCountsRendered(bodyText, counts) {
  const formatter = new Intl.NumberFormat("en-US");
  return ["articles", "entities", "events"].every((key) => {
    const raw = Number(counts?.[key] || 0);
    return raw > 0 && bodyText.includes(formatter.format(raw));
  });
}

async function runBrowserSmoke(baseUrl, candidateDbRel, outDir, manifestJson) {
  const screenshotPath = path.join(outDir, "atlas_browser_smoke.png");
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  try {
    const response = await page.goto(`${baseUrl}/atlas`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForFunction(() => document.body?.innerText?.includes("Read-only atlas browser"), null, {
      timeout: 30_000,
    });
    await page.screenshot({ path: screenshotPath, fullPage: true });
    const title = await page.title();
    const bodyText = await page.locator("body").innerText();
    const counts = manifestJson?.counts || {};
    const checks = {
      atlas_page_loaded: Boolean(response && statusOk(response.status())),
      title_present: title.includes("\u4e2d\u56fd\u5730\u4e0b\u7535\u5b50\u97f3\u4e50\u56fe\u9274"),
      no_load_failed_text: !/Load failed|Failed to fetch|Unhandled|Error:/i.test(bodyText),
      serving_counts_rendered: checkCountsRendered(bodyText, counts),
      read_only_footer_present: bodyText.includes("Read-only atlas browser"),
    };
    return {
      generated_at: nowIso(),
      candidate_db: candidateDbRel,
      local_url: `${baseUrl}/atlas`,
      ok: Object.values(checks).every(Boolean),
      title,
      checks,
      rendered_counts: {
        articles: Number(counts.articles || 0),
        entities: Number(counts.entities || 0),
        events: Number(counts.events || 0),
        activity_evidence_ref: Number(counts.activity_evidence_ref || 0),
      },
      screenshot_path: repoRelative(screenshotPath),
      console_errors: consoleErrors,
      boundary: {
        production_write_executed: false,
        cloudrun_deploy_executed: false,
        neo4j_write_executed: false,
        qdrant_write_executed: false,
        llm_call_executed: false,
        external_network_call_executed: false,
        local_http_executed: true,
      },
    };
  } finally {
    await browser.close();
  }
}

async function main() {
  const options = parseArgs();
  const candidateDb = resolveRepoPath(options.candidateDb, defaultCandidateDb);
  const outDir = resolveRepoPath(options.outDir, defaultOutDir);
  const entityMergeGroups = resolveRepoPath(options.entityMergeGroups, defaultEntityMergeGroups);
  const soundSystemEvidence = resolveRepoPath(options.soundSystemEvidence, defaultSoundSystemEvidence);
  const host = text(options.host) || "127.0.0.1";
  const port = Number.parseInt(text(options.port) || "0", 10) || 0;
  const candidateDbRel = repoRelative(candidateDb);
  const activitySample = selectActivityEventSample(candidateDb);
  const env = {
    NODE_ENV: "test",
    WEEKLY_ACTIVITY_API_DIR: path.join(repoRoot, "release/weekly_activity_api"),
    ATLAS_SERVING_SQLITE_DB: candidateDb,
    ATLAS_USE_SERVING_READ_MODEL: "1",
    ATLAS_SQLITE_READONLY: "1",
    ATLAS_REQUIRE_SESSION: "0",
    ATLAS_PUBLIC_REQUIRE_SESSION: "0",
    ATLAS_EXPOSE_INTERNAL_DB_PATH: "0",
    ATLAS_ENTITY_MERGE_GROUPS_PATH: existsSync(entityMergeGroups) ? entityMergeGroups : "",
    ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH: existsSync(soundSystemEvidence) ? soundSystemEvidence : "",
    DEEPSEEK_API_KEY: "",
    DEEPSEEK_ENRICH_ENABLED: "false",
  };
  const server = createServer({
    env,
    stage7SqliteDbPath: candidateDb,
  });

  const baseUrl = await listen(server, host, port);
  try {
    const cityEventQueries = ["深圳", "上海", "贵阳", "北京", "杭州"];
    const cityEventPaths = cityEventQueries.map(
      (city) => `/api/v1/stage7/search?q=${encodeURIComponent(city)}&kind=events&limit=8`,
    );
    const paths = [
      "/healthz",
      "/api/v1/stage7/manifest",
      "/api/v1/stage7/overview?sampleLimit=10",
      "/api/v1/stage7/search?q=MaFoL&kind=entities&limit=10",
      "/api/v1/stage7/search?q=DaRou&kind=entities&limit=10",
      "/api/v1/stage7/search?q=OIL&kind=entities&limit=10",
      "/api/v1/stage7/search?q=Loopy&kind=entities&limit=10",
      "/api/v1/stage7/search?q=ALL&kind=entities&limit=10",
      "/api/v1/stage7/graph/mobile-profile?q=Loopy&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5",
      "/api/v1/stage7/graph/mobile-profile?q=OIL%E6%B2%B9&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5",
      "/api/v1/stage7/graph/mobile-profile?q=ALL%E4%BF%B1%E4%B9%90%E9%83%A8&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5",
      "/api/v1/stage7/graph/mobile-profile?id=venue%3Ad87c448044defb77&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5",
      "/api/v1/stage7/search?q=SHCR&kind=entities&limit=10",
      "/api/v1/stage7/graph/profile?q=MaFoL&limit=40&sourceLimit=2000",
      "/api/v1/stage7/graph/profile?q=DaRou&limit=40&sourceLimit=2000",
      "/api/v1/stage7/graph/seed?q=MaFoL&limit=100",
      `/api/v1/stage7/events/${encodeURIComponent(activitySample.event_id)}?relatedLimit=20`,
      ...cityEventPaths,
    ];
    const results = [];
    for (const pathName of paths) {
      results.push(await requestJson(baseUrl, pathName));
    }
    const byPath = new Map(results.map((item) => [item.path, item]));
    const manifest = byPath.get("/api/v1/stage7/manifest")?.json || {};
    const overview = byPath.get("/api/v1/stage7/overview?sampleLimit=10")?.json || {};
    const mafolSearch = byPath.get("/api/v1/stage7/search?q=MaFoL&kind=entities&limit=10")?.json || {};
    const darouSearch = byPath.get("/api/v1/stage7/search?q=DaRou&kind=entities&limit=10")?.json || {};
    const oilSearch = byPath.get("/api/v1/stage7/search?q=OIL&kind=entities&limit=10")?.json || {};
    const loopySearch = byPath.get("/api/v1/stage7/search?q=Loopy&kind=entities&limit=10")?.json || {};
    const allSearch = byPath.get("/api/v1/stage7/search?q=ALL&kind=entities&limit=10")?.json || {};
    const shcrSearch = byPath.get("/api/v1/stage7/search?q=SHCR&kind=entities&limit=10")?.json || {};
    const loopyMobile = byPath.get("/api/v1/stage7/graph/mobile-profile?q=Loopy&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5")?.json || {};
    const oilMobile = byPath.get("/api/v1/stage7/graph/mobile-profile?q=OIL%E6%B2%B9&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5")?.json || {};
    const allMobileQuery = byPath.get("/api/v1/stage7/graph/mobile-profile?q=ALL%E4%BF%B1%E4%B9%90%E9%83%A8&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5")?.json || {};
    const allMobileId = byPath.get("/api/v1/stage7/graph/mobile-profile?id=venue%3Ad87c448044defb77&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5")?.json || {};
    const mafolProfile = byPath.get("/api/v1/stage7/graph/profile?q=MaFoL&limit=40&sourceLimit=2000")?.json || {};
    const darouProfile = byPath.get("/api/v1/stage7/graph/profile?q=DaRou&limit=40&sourceLimit=2000")?.json || {};
    const mafolGraph = byPath.get("/api/v1/stage7/graph/seed?q=MaFoL&limit=100")?.json || {};
    const activityDetail = byPath.get(`/api/v1/stage7/events/${encodeURIComponent(activitySample.event_id)}?relatedLimit=20`)?.json || {};
    const cityEventSearches = Object.fromEntries(
      cityEventQueries.map((city, index) => {
        const route = cityEventPaths[index];
        const result = byPath.get(route)?.json || {};
        return [city, citySearchSummary(result.results, city)];
      }),
    );
    const cityEventChecks = Object.fromEntries(
      cityEventQueries.map((city, index) => {
        const route = cityEventPaths[index];
        const result = byPath.get(route)?.json || {};
        return [`city_event_search_${city}`, resultHasEventCity(result.results, city)];
      }),
    );
    const checks = {
      healthz: Boolean(byPath.get("/healthz")?.json?.ok),
      manifest_serving_read_model:
        manifest.channel === "serving_read_model" &&
        manifest.localDb?.mode === "serving_read_model_sqlite" &&
        Number(manifest.counts?.performance_events || 0) > 0,
      overview_serving_read_model:
        overview.release?.channel === "serving_read_model" &&
        Number(overview.counts?.performance_events || 0) > 0,
      search_mafol: resultHasName(mafolSearch.results, "MaFoL"),
      search_darou: resultHasName(darouSearch.results, "DaRou"),
      venue_search_oil: resultHasType(oilSearch.results, "venue", "OIL"),
      entity_search_loopy: resultHasName(loopySearch.results, "Loopy"),
      entity_search_all_venue: resultHasType(allSearch.results, "venue", "ALL"),
      radio_search_shcr: resultHasType(shcrSearch.results, "radio", "SHCR"),
      mobile_loopy_entity_merge:
        loopyMobile.found === true &&
        loopyMobile.header?.title === "Loopy" &&
        loopyMobile.entityMerge?.available === true,
      mobile_oil_entity_merge_bounded:
        oilMobile.found === true &&
        oilMobile.header?.title === "OIL" &&
        oilMobile.entityMerge?.available === true &&
        oilMobile.retrieval?.entityMergePlan?.aggregationTruncated === true &&
        Number(oilMobile.retrieval?.entityMergePlan?.aggregationMemberCount || 0) <= 96,
      mobile_all_query_to_venue:
        allMobileQuery.found === true &&
        allMobileQuery.header?.title === "ALL" &&
        allMobileQuery.header?.primaryId === "venue:d87c448044defb77",
      mobile_all_id_to_venue:
        allMobileId.found === true &&
        allMobileId.header?.title === "ALL" &&
        allMobileId.header?.primaryId === "venue:d87c448044defb77",
      mobile_all_sound_system:
        Array.isArray(allMobileId.sections) &&
        allMobileId.sections.some((section) => section.id === "sound_system" && section.summary?.available === true),
      public_payload_no_path_or_source_leak: !publicPayloadHasLeak({
        manifest,
        overview,
        mafolSearch,
        darouSearch,
        oilSearch,
        loopySearch,
        allSearch,
        shcrSearch,
        loopyMobile,
        oilMobile,
        allMobileQuery,
        allMobileId,
      }),
      mobile_profile_graph_relationship_copy:
        relationshipCopyIsAllowed({
          loopyMobile,
          oilMobile,
          allMobileQuery,
          allMobileId,
          mafolProfile,
          darouProfile,
          mafolGraph,
        }),
      profile_mafol: Boolean(mafolProfile.found && normalizeName(mafolProfile.canonical?.name).includes("mafol")),
      profile_darou: Boolean(darouProfile.found && normalizeName(darouProfile.canonical?.name).includes("darou")),
      graph_window_mafol: Array.isArray(mafolGraph.nodes) && mafolGraph.nodes.length > 0 && mafolGraph.notFound === false,
      activity_detail_evidence:
        activityDetail.primaryId === activitySample.event_id &&
        Array.isArray(activityDetail.activityEvidence) &&
        activityDetail.activityEvidence.length > 0,
      ...cityEventChecks,
    };
    const apiPayload = {
      generated_at: nowIso(),
      candidate_db: candidateDbRel,
      base_url: baseUrl,
      ok: Object.values(checks).every(Boolean) && results.every((item) => item.ok),
      checks,
      activity_event_sample: {
        event_id: activitySample.event_id,
        title: activitySample.title,
        evidence_count: Number(activityDetail.activityEvidence?.length || activitySample.evidence_count || 0),
      },
      sidecars: {
        entity_merge_groups: existsSync(entityMergeGroups) ? repoRelative(entityMergeGroups) : "",
        venue_sound_system_evidence: existsSync(soundSystemEvidence) ? repoRelative(soundSystemEvidence) : "",
      },
      city_event_searches: cityEventSearches,
      results,
      boundary: {
        production_write_executed: false,
        cloudrun_deploy_executed: false,
        neo4j_write_executed: false,
        qdrant_write_executed: false,
        llm_call_executed: false,
        external_network_call_executed: false,
        local_http_executed: true,
      },
    };
    const browserPayload = await runBrowserSmoke(baseUrl, candidateDbRel, outDir, manifest);
    await writeJson(path.join(outDir, "api_smoke.json"), apiPayload);
    await writeText(path.join(outDir, "api_smoke.md"), buildApiMarkdown(apiPayload));
    await writeJson(path.join(outDir, "browser_smoke.json"), browserPayload);
    await writeText(path.join(outDir, "browser_smoke.md"), buildBrowserMarkdown(browserPayload));
    const summary = {
      ok: apiPayload.ok && browserPayload.ok,
      api_smoke: repoRelative(path.join(outDir, "api_smoke.json")),
      browser_smoke: repoRelative(path.join(outDir, "browser_smoke.json")),
      screenshot: browserPayload.screenshot_path,
      failed_api_checks: Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name),
      failed_browser_checks: Object.entries(browserPayload.checks).filter(([, ok]) => !ok).map(([name]) => name),
    };
    console.log(JSON.stringify(summary, null, 2));
    return summary.ok ? 0 : 2;
  } finally {
    await close(server);
  }
}

main().then((code) => {
  process.exitCode = code;
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
