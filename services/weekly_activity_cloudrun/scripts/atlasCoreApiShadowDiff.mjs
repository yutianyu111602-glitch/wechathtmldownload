import { createHash } from "node:crypto";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { createServer } from "../src/server.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(moduleDir, "../../..");
const defaultOldServingDb = path.join(
  repoRoot,
  "reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite",
);
const defaultCoreServingDb = path.join(
  repoRoot,
  "tools/stage7_rewrite/reports/atlas_core_candidate_20260605_activity_evidence/atlas_serving.sqlite",
);
const defaultOutDir = path.join(
  repoRoot,
  "tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_activity_evidence",
);
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

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256Text(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = createHash("sha256");
    const stream = createReadStream(filePath);
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

function listen(server, host, port) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      const address = server.address();
      resolve(`http://${address.address}:${address.port}`);
    });
  });
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

function publicPayloadHasLeak(payload) {
  const serialized = JSON.stringify(payload);
  return /[A-Z]:\\|file:\/\/|\.sqlite|entity_merge_groups_report_only\.jsonl|venue_sound_system_evidence\.jsonl|"source_url"|"raw_json"/i.test(serialized);
}

async function requestAny(baseUrl, pathName) {
  const started = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);
  try {
    const response = await fetch(`${baseUrl}${pathName}`, {
      signal: controller.signal,
      headers: { accept: "application/json, text/html;q=0.8, */*;q=0.1" },
    });
    const contentType = response.headers.get("content-type") || "";
    const body = await response.text();
    let json = null;
    if (contentType.includes("application/json") || body.trim().startsWith("{") || body.trim().startsWith("[")) {
      try {
        json = JSON.parse(body);
      } catch {
        json = null;
      }
    }
    return {
      path: pathName,
      status: response.status,
      ok: response.ok,
      contentType,
      elapsedMs: Math.round(performance.now() - started),
      bodyLength: body.length,
      bodySha256: sha256Text(body),
      json,
      textSample: json ? "" : body.slice(0, 200),
    };
  } finally {
    clearTimeout(timeout);
  }
}

function tableExists(db, table) {
  return Boolean(db.prepare("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name = ?").get(table));
}

function selectCandidateSamples(dbPath) {
  const db = new Database(dbPath, { readonly: true, fileMustExist: true });
  try {
    let activity = null;
    if (tableExists(db, "activity_event_detail") && tableExists(db, "activity_evidence_ref")) {
      activity = db.prepare(`
        SELECT d.event_id, d.title, e.source_ref_id
        FROM activity_event_detail d
        JOIN activity_evidence_ref e ON e.event_id = d.event_id
        WHERE COALESCE(e.source_ref_id, '') <> ''
        ORDER BY d.event_id
        LIMIT 1
      `).get();
    }
    if (!activity && tableExists(db, "performance_event")) {
      activity = db.prepare(`
        SELECT event_id, event_title AS title, source_ref_id
        FROM performance_event
        WHERE COALESCE(source_ref_id, '') <> ''
        ORDER BY event_id
        LIMIT 1
      `).get();
    }

    // P0: collect 3 distinct source ref IDs for expanded evidence lookup
    const sourceRefRows = db.prepare(`
      SELECT DISTINCT source_ref_id FROM performance_event
      WHERE COALESCE(source_ref_id, '') <> ''
      ORDER BY event_id
      LIMIT 3
    `).all();

    return {
      eventId: text(activity?.event_id),
      eventTitle: text(activity?.title),
      sourceRefId: text(sourceRefRows[0]?.source_ref_id),
      sourceRefId2: text(sourceRefRows[1]?.source_ref_id),
      sourceRefId3: text(sourceRefRows[2]?.source_ref_id),
    };
  } finally {
    db.close();
  }
}

function itemId(row = {}) {
  const item = row.item || row;
  return text(item.eid || item.id || item.subject_id || item.primaryId || item.event_id || item.evid || row.id);
}

function itemTitle(row = {}) {
  const item = row.item || row;
  return text(row.title || item.title || item.name || item.display_name || item.label || item.event_title);
}

function itemType(row = {}) {
  const item = row.item || row;
  return text(item.type || item.subject_type || item.kind || row.type);
}

function selectedCounts(counts = {}) {
  const keys = [
    "subjects",
    "profiles",
    "events",
    "performance_events",
    "dj_profiles",
    "sources",
    "activity_event_detail",
    "activity_evidence_ref",
  ];
  return Object.fromEntries(keys.filter((key) => counts[key] !== undefined).map((key) => [key, Number(counts[key] || 0)]));
}

function summarizeJson(json) {
  const summary = {
    topKeys: Object.keys(json || {}).sort(),
    schemaVersion: text(json?.schemaVersion),
    channel: text(json?.channel || json?.release?.channel),
    mode: text(json?.localDb?.mode || json?.retrieval?.mode),
    found: typeof json?.found === "boolean" ? json.found : null,
    notFound: typeof json?.notFound === "boolean" ? json.notFound : null,
    resultCount: Number(json?.resultCount ?? (Array.isArray(json?.results) ? json.results.length : NaN)),
    counts: selectedCounts(json?.counts || json?.meta?.counts || {}),
  };
  if (!Number.isFinite(summary.resultCount)) delete summary.resultCount;
  if (Array.isArray(json?.results)) {
    summary.topResults = json.results.slice(0, 5).map((row) => ({
      id: itemId(row),
      title: itemTitle(row),
      type: itemType(row),
    }));
  }
  if (Array.isArray(json?.nodes)) {
    summary.nodeCount = json.nodes.length;
    summary.topNodes = json.nodes.slice(0, 5).map((row) => ({
      id: text(row.primaryId || row.id),
      title: text(row.label || row.name || row.title),
      type: text(row.subtype || row.type),
    }));
  }
  if (Array.isArray(json?.edges)) summary.edgeCount = json.edges.length;
  if (json?.canonical || json?.header) {
    const entity = json.canonical || json.header;
    summary.entity = {
      id: text(entity.primaryId || entity.id),
      title: text(entity.title || entity.name),
      type: text(entity.type || entity.subjectType),
    };
  }
  if (json?.summary) {
    summary.profileSummary = {
      eventCount: Number(json.summary.eventCount || 0),
      collaboratorCount: Number(json.summary.collaboratorCount || 0),
      venueCount: Number(json.summary.venueCount || 0),
      sourceArticleCount: Number(json.summary.sourceArticleCount || 0),
    };
  }
  if (Array.isArray(json?.activityEvidence)) summary.activityEvidenceCount = json.activityEvidence.length;
  if (Array.isArray(json?.sections)) {
    summary.sections = json.sections.map((section) => ({
      id: text(section.id),
      itemCount: Array.isArray(section.items) ? section.items.length : 0,
      available: section.summary?.available ?? null,
    }));
  }
  if (json?.sourceRefId) {
    summary.evidence = {
      sourceRefId: text(json.sourceRefId),
      sourceKind: text(json.sourceKind),
      publicUrlAllowed: Boolean(json.policy?.publicUrlAllowed),
      sourceHashExposed: Boolean(json.policy?.sourceHashExposed),
    };
  }
  return summary;
}

function summarizeResponse(response) {
  const base = {
    status: response.status,
    ok: response.ok,
    contentType: response.contentType.split(";")[0],
    bodyLength: response.bodyLength,
  };
  if (response.json) {
    return {
      ...base,
      kind: "json",
      json: summarizeJson(response.json),
      summaryHash: sha256Text(stableJson(summarizeJson(response.json))),
    };
  }
  return {
    ...base,
    kind: "text",
    hasAtlasMarker: /Atlas|HUAIDJ/i.test(response.textSample),
    bodySha256: response.bodySha256,
    summaryHash: sha256Text(stableJson({
      status: response.status,
      contentType: response.contentType.split(";")[0],
      bodyLength: response.bodyLength,
      hasAtlasMarker: /Atlas|HUAIDJ/i.test(response.textSample),
    })),
  };
}

function compareSummaries(oldSummary, coreSummary) {
  const findings = [];
  if (oldSummary.status < 400 && coreSummary.status >= 400) findings.push("core_status_regressed");
  if (oldSummary.kind !== coreSummary.kind) findings.push("response_kind_changed");
  if (oldSummary.kind === "json" && coreSummary.kind === "json") {
    const oldKeys = new Set(oldSummary.json.topKeys || []);
    const coreKeys = new Set(coreSummary.json.topKeys || []);
    const missingTopKeys = [...oldKeys].filter((key) => !coreKeys.has(key));
    if (missingTopKeys.length) findings.push(`missing_top_keys:${missingTopKeys.join(",")}`);
    if (oldSummary.json.found === true && coreSummary.json.found === false) findings.push("found_regressed_to_false");
    if (oldSummary.json.notFound === false && coreSummary.json.notFound === true) findings.push("not_found_regressed_to_true");
    for (const key of ["resultCount", "nodeCount", "edgeCount", "activityEvidenceCount"]) {
      if (Number.isFinite(oldSummary.json[key]) && Number.isFinite(coreSummary.json[key]) && coreSummary.json[key] < oldSummary.json[key]) {
        findings.push(`${key}_below_old:${oldSummary.json[key]}->${coreSummary.json[key]}`);
      }
    }
    for (const key of ["eventCount", "collaboratorCount", "venueCount", "sourceArticleCount"]) {
      const oldValue = oldSummary.json.profileSummary?.[key];
      const coreValue = coreSummary.json.profileSummary?.[key];
      if (Number.isFinite(oldValue) && Number.isFinite(coreValue) && coreValue < oldValue) {
        findings.push(`profile_${key}_below_old:${oldValue}->${coreValue}`);
      }
    }
  }
  if (oldSummary.kind === "text" && coreSummary.kind === "text" && oldSummary.bodyLength > 0 && coreSummary.bodyLength < Math.min(oldSummary.bodyLength, 512)) {
    findings.push(`html_body_too_small:${oldSummary.bodyLength}->${coreSummary.bodyLength}`);
  }
  return {
    match: findings.length === 0,
    findings,
    summaryHashEqual: oldSummary.summaryHash === coreSummary.summaryHash,
  };
}

function makeEnv(dbVar, dbPath) {
  return {
    NODE_ENV: "test",
    WEEKLY_ACTIVITY_API_DIR: path.join(repoRoot, "release/weekly_activity_api"),
    ATLAS_USE_SERVING_READ_MODEL: "1",
    ATLAS_SQLITE_READONLY: "1",
    ATLAS_REQUIRE_SESSION: "0",
    ATLAS_PUBLIC_REQUIRE_SESSION: "0",
    ATLAS_EXPOSE_INTERNAL_DB_PATH: "0",
    ATLAS_ENTITY_MERGE_GROUPS_PATH: existsSync(defaultEntityMergeGroups) ? defaultEntityMergeGroups : "",
    ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH: existsSync(defaultSoundSystemEvidence) ? defaultSoundSystemEvidence : "",
    DEEPSEEK_API_KEY: "",
    DEEPSEEK_ENRICH_ENABLED: "false",
    [dbVar]: dbPath,
  };
}

function pathsToCompare(samples) {
  const paths = [
    // --- health / meta (2 paths) ---
    { id: "healthz", path: "/healthz" },
    { id: "manifest", path: "/api/v1/stage7/manifest" },

    // --- overview (1 path) ---
    { id: "overview", path: "/api/v1/stage7/overview?sampleLimit=10" },

    // --- DJ entity search — original 5 ---
    { id: "search_mafol", path: "/api/v1/stage7/search?q=MaFoL&kind=entities&limit=10" },
    { id: "search_darou", path: "/api/v1/stage7/search?q=DaRou&kind=entities&limit=10" },
    { id: "search_oil", path: "/api/v1/stage7/search?q=OIL&kind=entities&limit=10" },
    { id: "search_loopy", path: "/api/v1/stage7/search?q=Loopy&kind=entities&limit=10" },
    { id: "search_dj", path: "/api/v1/stage7/search?q=DJ&kind=entities&limit=10" },

    // --- DJ entity search — expanded: high source-count (P0) ---
    { id: "search_maxxi", path: "/api/v1/stage7/search?q=MAXXI&kind=entities&limit=10" },
    { id: "search_yangbing", path: "/api/v1/stage7/search?q=Yang%20Bing&kind=entities&limit=10" },
    { id: "search_mikocycle", path: "/api/v1/stage7/search?q=MikoCycle&kind=entities&limit=10" },
    { id: "search_pancakelee", path: "/api/v1/stage7/search?q=PANCAKE%20LEE&kind=entities&limit=10" },
    { id: "search_djozone", path: "/api/v1/stage7/search?q=DJ%20Ozone&kind=entities&limit=10" },
    { id: "search_maxshen", path: "/api/v1/stage7/search?q=Max%20Shen&kind=entities&limit=10" },
    { id: "search_knopha", path: "/api/v1/stage7/search?q=Knopha&kind=entities&limit=10" },

    // --- DJ entity search — Chinese names (P0) ---
    { id: "search_xiaolaba", path: `/api/v1/stage7/search?q=${encodeURIComponent("小喇叭")}&kind=entities&limit=10` },
    { id: "search_lvzhiliang", path: `/api/v1/stage7/search?q=${encodeURIComponent("吕志良")}&kind=entities&limit=10` },
    { id: "search_yutou", path: `/api/v1/stage7/search?q=${encodeURIComponent("鱼头泡饼")}&kind=entities&limit=10` },

    // --- DJ entity search — special chars / mixed case (P0) ---
    { id: "search_sandm", path: "/api/v1/stage7/search?q=S%26M&kind=entities&limit=10" },
    { id: "search_empresscc", path: "/api/v1/stage7/search?q=Empress%20CC!&kind=entities&limit=10" },

    // --- City event search — expanded (P0) ---
    { id: "search_shenzhen_events", path: `/api/v1/stage7/search?q=${encodeURIComponent("深圳")}&kind=events&limit=8` },
    { id: "search_shanghai_events", path: `/api/v1/stage7/search?q=${encodeURIComponent("上海")}&kind=events&limit=8` },
    { id: "search_chengdu_events", path: `/api/v1/stage7/search?q=${encodeURIComponent("成都")}&kind=events&limit=8` },
    { id: "search_beijing_events", path: `/api/v1/stage7/search?q=${encodeURIComponent("北京")}&kind=events&limit=8` },
    { id: "search_kunming_events", path: `/api/v1/stage7/search?q=${encodeURIComponent("昆明")}&kind=events&limit=8` },

    // --- Venue entity search (P0) ---
    { id: "search_tag", path: "/api/v1/stage7/search?q=TAG&kind=entities&limit=10" },
    { id: "search_dada", path: "/api/v1/stage7/search?q=Dada&kind=entities&limit=10" },
    { id: "search_system", path: "/api/v1/stage7/search?q=SYSTEM&kind=entities&limit=10" },

    // --- Mobile profile — expanded (P0) ---
    { id: "mobile_loopy", path: "/api/v1/stage7/graph/mobile-profile?q=Loopy&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5" },
    { id: "mobile_oil", path: `/api/v1/stage7/graph/mobile-profile?q=${encodeURIComponent("OIL油")}&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5` },
    { id: "mobile_maxxi", path: "/api/v1/stage7/graph/mobile-profile?q=MAXXI&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5" },
    { id: "mobile_yangbing", path: "/api/v1/stage7/graph/mobile-profile?q=Yang%20Bing&eventLimit=5&collaboratorLimit=5&venueLimit=5&articleLimit=5" },

    // --- Full profile — expanded (P0) ---
    { id: "profile_mafol", path: "/api/v1/stage7/graph/profile?q=MaFoL&limit=40&sourceLimit=2000&eventLimit=10&collaboratorLimit=10&venueLimit=10" },
    { id: "profile_darou", path: "/api/v1/stage7/graph/profile?q=DaRou&limit=40&sourceLimit=2000&eventLimit=10&collaboratorLimit=10&venueLimit=10" },
    { id: "profile_oil", path: `/api/v1/stage7/graph/profile?q=${encodeURIComponent("OIL油")}&limit=40&sourceLimit=2000&eventLimit=10&collaboratorLimit=10&venueLimit=10` },
    { id: "profile_pancakelee", path: "/api/v1/stage7/graph/profile?q=PANCAKE%20LEE&limit=40&sourceLimit=2000&eventLimit=10&collaboratorLimit=10&venueLimit=10" },

    // --- Graph seed — expanded (P0) ---
    { id: "graph_seed_mafol", path: "/api/v1/stage7/graph/seed?q=MaFoL&limit=100" },
    { id: "graph_seed_loopy", path: "/api/v1/stage7/graph/seed?q=Loopy&limit=100" },
    { id: "graph_seed_oil", path: `/api/v1/stage7/graph/seed?q=${encodeURIComponent("OIL油")}&limit=100` },
    { id: "graph_seed_pancakelee", path: "/api/v1/stage7/graph/seed?q=PANCAKE%20LEE&limit=100" },

    // --- Atlas web pages (2 paths) ---
    { id: "atlas_page", path: "/atlas" },
    { id: "atlas_graph_page", path: "/atlas/graph" },
  ];

  // --- Dynamic: activity event detail (if sample available) ---
  if (samples.eventId) {
    paths.push({ id: "activity_event_detail", path: `/api/v1/stage7/events/${encodeURIComponent(samples.eventId)}?relatedLimit=20` });
  }

  // --- Dynamic: source evidence lookup (P0: 3 samples from DB) ---
  if (samples.sourceRefId) {
    paths.push({ id: "source_evidence_lookup_1", path: `/api/v1/atlas/evidence/${encodeURIComponent(samples.sourceRefId)}` });
  }
  if (samples.sourceRefId2) {
    paths.push({ id: "source_evidence_lookup_2", path: `/api/v1/atlas/evidence/${encodeURIComponent(samples.sourceRefId2)}` });
  }
  if (samples.sourceRefId3) {
    paths.push({ id: "source_evidence_lookup_3", path: `/api/v1/atlas/evidence/${encodeURIComponent(samples.sourceRefId3)}` });
  }

  return paths;
}

async function collectSide(label, dbVar, dbPath, requestPaths, host, port) {
  const server = createServer({ env: makeEnv(dbVar, dbPath) });
  const baseUrl = await listen(server, host, port);
  try {
    const responses = [];
    for (const item of requestPaths) {
      let response;
      try {
        response = await requestAny(baseUrl, item.path);
      } catch (err) {
        response = {
          path: item.path,
          status: 0,
          ok: false,
          contentType: '',
          elapsedMs: 0,
          bodyLength: 0,
          bodySha256: '',
          json: null,
          textSample: '',
          error: err.message?.substring(0, 200) || String(err).substring(0, 200),
        };
      }
      responses.push({
        id: item.id,
        path: item.path,
        label,
        response,
        summary: summarizeResponse(response),
        leakFinding: publicPayloadHasLeak(response.json || response.textSample),
      });
    }
    return { baseUrl, responses };
  } finally {
    await closeServer(server);
  }
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# Atlas Core API Shadow Diff");
  lines.push("");
  lines.push(`Generated: \`${report.generated_at}\``);
  lines.push(`Decision: \`${report.decision}\``);
  lines.push(`Old serving: \`${report.inputs.old_serving}\``);
  lines.push(`Core serving: \`${report.inputs.core_serving}\``);
  lines.push("");
  lines.push("## Summary");
  lines.push("");
  lines.push(`- compared paths: \`${report.summary.path_count}\``);
  lines.push(`- regression findings: \`${report.summary.regression_finding_count}\``);
  lines.push(`- leak findings: \`${report.summary.leak_finding_count}\``);
  lines.push(`- source hashes unchanged: \`${report.source_hashes_unchanged}\``);
  lines.push("");
  lines.push("## Paths");
  lines.push("");
  lines.push("| id | old status | core status | findings | hash equal |");
  lines.push("| --- | ---: | ---: | --- | --- |");
  for (const row of report.rows) {
    lines.push(`| \`${row.id}\` | ${row.old.status} | ${row.core.status} | ${row.compare.findings.length ? row.compare.findings.map((item) => `\`${item}\``).join("<br>") : "`none`"} | \`${row.compare.summaryHashEqual}\` |`);
  }
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs();
  const oldServing = resolveRepoPath(options.oldServingDb, defaultOldServingDb);
  const coreServing = resolveRepoPath(options.coreServingDb, defaultCoreServingDb);
  const outDir = resolveRepoPath(options.outDir, defaultOutDir);
  const host = text(options.host) || "127.0.0.1";
  const port = Number.parseInt(text(options.port) || "0", 10) || 0;

  for (const dbPath of [oldServing, coreServing]) {
    if (!existsSync(dbPath)) throw new Error(`SQLite DB not found: ${dbPath}`);
  }

  await mkdir(outDir, { recursive: true });
  const before = {
    old_serving: await sha256File(oldServing),
    core_serving: await sha256File(coreServing),
  };
  const samples = selectCandidateSamples(coreServing);
  const requestPaths = pathsToCompare(samples);
  let oldSide;
  let coreSide;
  let error = "";
  try {
    oldSide = await collectSide("old", "ATLAS_SERVING_SQLITE_DB", oldServing, requestPaths, host, port);
    coreSide = await collectSide("core", "ATLAS_CORE_SQLITE_DB", coreServing, requestPaths, host, port);
  } catch (exc) {
    error = String(exc?.stack || exc?.message || exc);
  }
  const after = {
    old_serving: await sha256File(oldServing),
    core_serving: await sha256File(coreServing),
  };
  const sourceHashesUnchanged = before.old_serving === after.old_serving && before.core_serving === after.core_serving;

  const rows = [];
  if (!error) {
    const oldById = new Map(oldSide.responses.map((row) => [row.id, row]));
    const coreById = new Map(coreSide.responses.map((row) => [row.id, row]));
    for (const item of requestPaths) {
      const oldRow = oldById.get(item.id);
      const coreRow = coreById.get(item.id);
      rows.push({
        id: item.id,
        path: item.path,
        old: oldRow.summary,
        core: coreRow.summary,
        compare: compareSummaries(oldRow.summary, coreRow.summary),
        leakFindings: [
          ...(oldRow.leakFinding ? ["old_public_payload_leak_pattern"] : []),
          ...(coreRow.leakFinding ? ["core_public_payload_leak_pattern"] : []),
        ],
      });
    }
  }

  const regressionFindingCount = rows.reduce((count, row) => count + row.compare.findings.length, 0);
  const leakFindingCount = rows.reduce((count, row) => count + row.leakFindings.length, 0);
  const blockers = [
    ...(error ? ["api_shadow_diff_execution_failed"] : []),
    ...(!sourceHashesUnchanged ? ["source_hash_changed"] : []),
    ...(regressionFindingCount ? ["api_response_regression_findings"] : []),
    ...(leakFindingCount ? ["public_payload_leak_findings"] : []),
  ];
  const report = {
    schema_version: "atlas_core_api_shadow_diff.v1",
    decision: blockers.length ? "atlas_core_api_shadow_diff_blocked_report_only" : "atlas_core_api_shadow_diff_ready_report_only",
    generated_at: nowIso(),
    blockers,
    error,
    inputs: {
      old_serving: repoRelative(oldServing),
      core_serving: repoRelative(coreServing),
      old_env_var: "ATLAS_SERVING_SQLITE_DB",
      core_env_var: "ATLAS_CORE_SQLITE_DB",
      report_only: true,
    },
    samples,
    source_hashes_before: before,
    source_hashes_after: after,
    source_hashes_unchanged: sourceHashesUnchanged,
    safety: {
      old_serving_write_executed: false,
      core_serving_write_executed: false,
      production_write_executed: false,
      report_only: true,
      readonly_env_enforced: true,
    },
    summary: {
      path_count: requestPaths.length,
      regression_finding_count: regressionFindingCount,
      leak_finding_count: leakFindingCount,
      exact_summary_hash_match_count: rows.filter((row) => row.compare.summaryHashEqual).length,
    },
    rows,
    outputs: {
      report: repoRelative(path.join(outDir, "atlas_core_api_shadow_diff_report.json")),
      rows: repoRelative(path.join(outDir, "atlas_core_api_shadow_diff_rows.jsonl")),
      summary_md: repoRelative(path.join(outDir, "atlas_core_api_shadow_diff_summary.md")),
    },
  };

  await writeFile(path.join(outDir, "atlas_core_api_shadow_diff_report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
  await writeFile(path.join(outDir, "atlas_core_api_shadow_diff_rows.jsonl"), `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf8");
  await writeFile(path.join(outDir, "atlas_core_api_shadow_diff_summary.md"), renderMarkdown(report), "utf8");
  console.log(JSON.stringify({
    decision: report.decision,
    blockers: report.blockers,
    summary: report.summary,
    source_hashes_unchanged: report.source_hashes_unchanged,
    outputs: report.outputs,
  }));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
