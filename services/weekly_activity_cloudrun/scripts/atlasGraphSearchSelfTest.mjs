import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Stage7AtlasSqliteStore } from "../src/stage7AtlasSqliteStore.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(moduleDir, "../../..");
const defaultDbPath = path.join(
  repoRoot,
  "tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite",
);
const defaultOutRoot = path.join(repoRoot, "reports");
const DEFAULT_MANUAL_SEEDS = ["MaFoL", "OIL"];
const AUTO_SEED_ENTITY_TYPES = new Set([
  "artist",
  "brand",
  "club",
  "collective",
  "crew",
  "dj",
  "group",
  "label",
  "organization",
  "person",
  "project",
  "venue",
]);

function text(value) {
  return String(value ?? "").trim();
}

function normalizeName(value) {
  return text(value).toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, "");
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

function intOption(value, fallback, min = 1, max = 1000) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function floatOption(value, fallback, min = 0, max = 1) {
  const parsed = Number.parseFloat(String(value ?? ""));
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function splitSeeds(value) {
  const raw = text(value);
  if (!raw) return DEFAULT_MANUAL_SEEDS;
  return raw.split(",").map(text).filter(Boolean);
}

function sourceArticleCounts(db, sourceArticleUid) {
  const uid = text(sourceArticleUid);
  if (!uid) return { relatedEntities: 0, relatedEvents: 0 };
  return {
    relatedEntities: Number(db.prepare("SELECT COUNT(*) AS c FROM entities WHERE source_article_uid = ?").get(uid)?.c || 0),
    relatedEvents: Number(db.prepare("SELECT COUNT(*) AS c FROM events WHERE source_article_uid = ?").get(uid)?.c || 0),
  };
}

function servingProfileCounts(db, subjectId) {
  const id = text(subjectId);
  if (!id) return { relatedEntities: 0, relatedEvents: 0, confidence: null };
  const row = db
    .prepare(
      "SELECT event_count, collaborator_count, organization_count, confidence FROM dj_profile WHERE dj_id = ? LIMIT 1",
    )
    .get(id);
  return {
    relatedEntities: Number(row?.collaborator_count || 0) + Number(row?.organization_count || 0),
    relatedEvents: Number(row?.event_count || 0),
    confidence: row?.confidence ?? null,
  };
}

function candidateLooksSpecific(name) {
  const raw = text(name);
  if (raw.length < 2 || raw.length > 64) return false;
  if (/https?:\/\//i.test(raw)) return false;
  if (/^\d+$/.test(raw)) return false;
  if (/^[a-z]$/i.test(raw)) return false;
  return true;
}

function candidateLooksGraphEntity(row) {
  const type = text(row?.type).toLowerCase();
  return AUTO_SEED_ENTITY_TYPES.has(type) && candidateLooksSpecific(row?.name);
}

function selectManualSeedRows(db, store, seedNames) {
  const rows = [];
  for (const name of seedNames) {
    const matches = db
      .prepare("SELECT * FROM entities WHERE LOWER(name) = LOWER(?) ORDER BY confidence DESC, row_pk LIMIT 20")
      .all(name);
    const row = matches.find((candidate) => store.isPublicRowVisible(db, candidate, "entities")) || matches[0] || null;
    const counts = row ? sourceArticleCounts(db, row.source_article_uid) : { relatedEntities: 0, relatedEvents: 0 };
    rows.push({
      name,
      expectedName: row?.name || name,
      type: row?.type || "",
      sourceArticleUid: row?.source_article_uid || "",
      confidence: row?.confidence ?? null,
      relatedEntities: counts.relatedEntities,
      relatedEvents: counts.relatedEvents,
      selectedBy: "manual",
      visibleInDb: Boolean(row && store.isPublicRowVisible(db, row, "entities")),
    });
  }
  return rows;
}

function servingSubjectMatchesQuery(row, query) {
  const key = normalizeName(query);
  if (!key) return false;
  if (normalizeName(row?.display_name) === key) return true;
  const aliasesKey = normalizeName(row?.aliases_text);
  return Boolean(aliasesKey && aliasesKey.includes(key));
}

function selectServingManualSeedRows(db, store, seedNames) {
  const rows = [];
  for (const name of seedNames) {
    const matches = store.servingSearchDocuments(db, { q: name, limit: 20, subjectTypes: ["dj"] });
    const row = matches.find((candidate) => servingSubjectMatchesQuery(candidate, name)) || matches[0] || null;
    const counts = row ? servingProfileCounts(db, row.subject_id) : { relatedEntities: 0, relatedEvents: 0, confidence: null };
    rows.push({
      name,
      expectedName: row?.display_name || name,
      type: row?.subject_type || "dj",
      sourceArticleUid: "",
      confidence: counts.confidence,
      relatedEntities: counts.relatedEntities,
      relatedEvents: counts.relatedEvents,
      selectedBy: "manual_serving_dj",
      visibleInDb: Boolean(row),
      servingReadModel: true,
    });
  }
  return rows;
}

function selectAutoSeedRows(db, store, { autoLimit, minConfidence, minRelated }) {
  const limit = autoLimit;
  const scanLimit = Math.max(limit * 30, 200);
  const rows = db
    .prepare(
      `
      SELECT e.*,
        (SELECT COUNT(*) FROM entities e2 WHERE e2.source_article_uid = e.source_article_uid) AS related_entities,
        (SELECT COUNT(*) FROM events ev WHERE ev.source_article_uid = e.source_article_uid) AS related_events
      FROM entities e
      WHERE e.name <> ''
        AND e.confidence >= ?
        AND e.source_article_uid <> ''
      ORDER BY (related_entities + related_events) DESC, e.confidence DESC, e.row_pk
      LIMIT ?
      `,
    )
    .all(minConfidence, scanLimit);
  const selected = [];
  const seen = new Set();
  for (const row of rows) {
    const name = text(row.name);
    const key = normalizeName(name);
    const relatedEntities = Number(row.related_entities || 0);
    const relatedEvents = Number(row.related_events || 0);
    if (!key || seen.has(key) || !candidateLooksGraphEntity(row)) continue;
    if (relatedEntities + relatedEvents < minRelated) continue;
    if (!store.isPublicRowVisible(db, row, "entities")) continue;
    seen.add(key);
    selected.push({
      name,
      expectedName: name,
      type: row.type || "",
      sourceArticleUid: row.source_article_uid || "",
      confidence: row.confidence ?? null,
      relatedEntities,
      relatedEvents,
      selectedBy: "auto_high_conf_related",
      visibleInDb: true,
    });
    if (selected.length >= limit) break;
  }
  return selected;
}

function selectServingAutoSeedRows(db, { autoLimit, minRelated }) {
  const limit = autoLimit;
  const scanLimit = Math.max(limit * 12, 120);
  const rows = db
    .prepare(
      `
      SELECT sd.subject_id, sd.subject_type, sd.display_name, sd.city_text, sd.rank_score,
             p.event_count, p.collaborator_count, p.organization_count, p.confidence
      FROM search_document sd
      LEFT JOIN dj_profile p ON p.dj_id = sd.subject_id
      WHERE sd.subject_type = 'dj'
        AND sd.display_name <> ''
      ORDER BY COALESCE(p.event_count, sd.rank_score, 0) DESC, sd.rank_score DESC, sd.doc_rowid
      LIMIT ?
      `,
    )
    .all(scanLimit);
  const selected = [];
  const seen = new Set();
  for (const row of rows) {
    const name = text(row.display_name);
    const key = normalizeName(name);
    const relatedEntities = Number(row.collaborator_count || 0) + Number(row.organization_count || 0);
    const relatedEvents = Number(row.event_count || 0);
    if (!key || seen.has(key) || !candidateLooksSpecific(name)) continue;
    if (relatedEntities + relatedEvents < minRelated) continue;
    seen.add(key);
    selected.push({
      name,
      expectedName: name,
      type: row.subject_type || "dj",
      sourceArticleUid: "",
      confidence: row.confidence ?? null,
      relatedEntities,
      relatedEvents,
      selectedBy: "auto_serving_dj_high_event_count",
      visibleInDb: true,
      servingReadModel: true,
    });
    if (selected.length >= limit) break;
  }
  return selected;
}

function mergeSeeds(manualRows, autoRows, maxSeeds) {
  const merged = [];
  const seen = new Set();
  for (const seed of [...manualRows, ...autoRows]) {
    const key = normalizeName(seed.expectedName || seed.name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    merged.push(seed);
    if (merged.length >= maxSeeds) break;
  }
  return merged;
}

function bestExactNode(nodes, seed) {
  const expected = normalizeName(seed.expectedName || seed.name);
  const query = normalizeName(seed.name);
  return (
    nodes.find((node) => node.kind === "entities" && normalizeName(node.label) === expected) ||
    nodes.find((node) => node.kind === "entities" && normalizeName(node.label) === query) ||
    null
  );
}

async function timed(label, fn) {
  const started = performance.now();
  const value = await fn();
  return { label, value, ms: Math.round(performance.now() - started) };
}

async function evaluateSeed(store, seed, options) {
  const seedResult = await timed("seed", () =>
    store.getGraphSeed({ q: seed.name, limit: options.graphLimit }),
  );
  const graph = seedResult.value;
  const exactNode = bestExactNode(graph.nodes || [], seed);
  let detail = null;
  let detailMs = 0;
  let subgraph = null;
  let subgraphMs = 0;
  let profile = null;
  let profileMs = 0;
  if (exactNode) {
    const detailResult = await timed("detail", () =>
      store.getDetail("entities", exactNode.primaryId, { relatedLimit: options.relatedLimit }),
    );
    detail = detailResult.value;
    detailMs = detailResult.ms;
    if (typeof store.getGraphEntityProfile === "function") {
      const profileResult = await timed("profile", () =>
        store.getGraphEntityProfile({ q: seed.name, limit: options.profileLimit, sourceLimit: options.profileSourceLimit }),
      );
      profile = profileResult.value;
      profileMs = profileResult.ms;
    }
    const subgraphResult = await timed("subgraph", () =>
      store.getGraphSubgraph({ nodeId: exactNode.id, depth: 1, limit: options.subgraphLimit }),
    );
    subgraph = subgraphResult.value;
    subgraphMs = subgraphResult.ms;
  }

  const relatedEntityCount = detail?.related?.entities?.length || 0;
  const relatedEventCount = detail?.related?.events?.length || 0;
  const returnedNodes = graph?.limits?.returnedNodes || graph?.nodes?.length || 0;
  const returnedEdges = graph?.limits?.returnedEdges || graph?.edges?.length || 0;
  const subgraphNodes = subgraph?.limits?.returnedNodes || subgraph?.nodes?.length || 0;
  const subgraphEdges = subgraph?.limits?.returnedEdges || subgraph?.edges?.length || 0;
  const profileSourceCount = profile?.summary?.loadedSourceArticles || 0;
  const profileEventCount = profile?.summary?.eventCount || 0;
  const profileRelationshipCount = (profile?.summary?.collaboratorCount || 0) + (profile?.summary?.organizationCount || 0);
  const exactRank = exactNode ? (graph.nodes || []).findIndex((node) => node.id === exactNode.id) : -1;
  const detailRelatedOk = seed.servingReadModel
    ? relatedEntityCount + relatedEventCount > 0 || profileEventCount > 0 || profileRelationshipCount > 0
    : relatedEntityCount + relatedEventCount > 0;
  const checks = {
    visibleInDb: seed.visibleInDb,
    exactNodeFound: Boolean(exactNode),
    exactNodeInTop3: exactRank >= 0 && exactRank < 3,
    detailFound: Boolean(detail),
    detailHasRelated: detailRelatedOk,
    graphHasNodes: returnedNodes >= options.minGraphNodes,
    graphHasEdges: returnedEdges >= options.minGraphEdges,
    subgraphHasNodes: subgraphNodes >= options.minSubgraphNodes,
    subgraphHasEdges: subgraphEdges >= options.minSubgraphEdges,
    profileFound: Boolean(profile?.found),
    profileHasSources: profileSourceCount > 0,
    profileHasHistory: profileEventCount > 0,
    profileRelationshipsMeasured: profileRelationshipCount >= 0,
  };
  const pass = Object.values(checks).every(Boolean);
  return {
    query: seed.name,
    expectedName: seed.expectedName,
    selectedBy: seed.selectedBy,
    type: seed.type,
    sourceArticleUid: seed.sourceArticleUid,
    confidence: seed.confidence,
    databaseRelated: {
      entities: seed.relatedEntities,
      events: seed.relatedEvents,
    },
    matchedNode: exactNode
      ? {
          id: exactNode.id,
          label: exactNode.label,
          kind: exactNode.kind,
          subtype: exactNode.subtype,
          primaryId: exactNode.primaryId,
          rank: exactRank,
        }
      : null,
    apiRelated: {
      entities: relatedEntityCount,
      events: relatedEventCount,
    },
    profile: {
      sourceArticles: profileSourceCount,
      events: profileEventCount,
      relationships: profileRelationshipCount,
      truncated: Boolean(profile?.summary?.sourceWindowTruncated),
    },
    graph: {
      nodes: returnedNodes,
      edges: returnedEdges,
      subgraphNodes,
      subgraphEdges,
    },
    timingsMs: {
      seed: seedResult.ms,
      detail: detailMs,
      subgraph: subgraphMs,
      profile: profileMs,
    },
    checks,
    pass,
  };
}

function summarize(results, options) {
  const passCount = results.filter((row) => row.pass).length;
  const exactTop3Count = results.filter((row) => row.checks.exactNodeInTop3).length;
  const relatedCount = results.filter((row) => row.checks.detailHasRelated).length;
  const profileCount = results.filter((row) => row.checks.profileHasSources && row.checks.profileHasHistory).length;
  const seedLatencies = results.map((row) => row.timingsMs.seed).sort((a, b) => a - b);
  const profileLatencies = results.map((row) => row.timingsMs.profile).sort((a, b) => a - b);
  const p95Index = Math.max(0, Math.ceil(seedLatencies.length * 0.95) - 1);
  const profileP95Index = Math.max(0, Math.ceil(profileLatencies.length * 0.95) - 1);
  return {
    seedCount: results.length,
    passCount,
    failCount: results.length - passCount,
    exactTop3Count,
    relatedCount,
    profileCount,
    passRate: results.length ? Number((passCount / results.length).toFixed(4)) : 0,
    seedLatencyMs: {
      max: seedLatencies.at(-1) || 0,
      p95: seedLatencies[p95Index] || 0,
      budgetP95: options.seedLatencyBudgetMs,
      withinBudget: (seedLatencies[p95Index] || 0) <= options.seedLatencyBudgetMs,
    },
    profileLatencyMs: {
      max: profileLatencies.at(-1) || 0,
      p95: profileLatencies[profileP95Index] || 0,
      budgetP95: options.profileLatencyBudgetMs,
      withinBudget: (profileLatencies[profileP95Index] || 0) <= options.profileLatencyBudgetMs,
    },
  };
}

function recommendations(results, summary) {
  const items = [];
  const noExact = results.filter((row) => !row.checks.exactNodeFound);
  const noRelated = results.filter((row) => row.checks.exactNodeFound && !row.checks.detailHasRelated);
  const noEdges = results.filter((row) => !row.checks.graphHasEdges || !row.checks.subgraphHasEdges);
  const noProfile = results.filter((row) => !row.checks.profileFound || !row.checks.profileHasSources || !row.checks.profileHasHistory);
  if (noExact.length) {
    items.push({
      code: "SEARCH_EXACT_MISS",
      message: "Exact entity names missed by graph seed search; add alias/exact-name fallback after FTS.",
      queries: noExact.map((row) => row.query),
    });
  }
  if (noRelated.length) {
    items.push({
      code: "DETAIL_RELATED_EMPTY",
      message: "Detail API returned no related rows despite high-confidence DB source context; inspect public noise filters and source-scoped IDs.",
      queries: noRelated.map((row) => row.query),
    });
  }
  if (noEdges.length) {
    items.push({
      code: "GRAPH_EDGE_EMPTY",
      message: "Graph or subgraph relation window is too thin; inspect article-neighborhood expansion and per-kind limits.",
      queries: noEdges.map((row) => row.query),
    });
  }
  if (noProfile.length) {
    items.push({
      code: "ENTITY_PROFILE_THIN",
      message: "Entity profile rollup did not return source/history context; inspect exact-name grouping and source article expansion.",
      queries: noProfile.map((row) => row.query),
    });
  }
  if (!summary.seedLatencyMs.withinBudget) {
    items.push({
      code: "SEARCH_LATENCY_BUDGET",
      message: `Seed API p95 exceeded ${summary.seedLatencyMs.budgetP95}ms; profile FTS and related-neighborhood queries.`,
      p95: summary.seedLatencyMs.p95,
    });
  }
  if (!summary.profileLatencyMs.withinBudget) {
    items.push({
      code: "PROFILE_LATENCY_BUDGET",
      message: `Profile API p95 exceeded ${summary.profileLatencyMs.budgetP95}ms; build or refresh the entity-profile sidecar index before public scale.`,
      p95: summary.profileLatencyMs.p95,
    });
  }
  return items;
}

function timestampForPath(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\..+$/, "Z");
}

async function writeReport(report, outRoot) {
  const stamp = timestampForPath();
  const outDir = path.join(outRoot, `atlas_graph_search_selftest_${stamp}`);
  await mkdir(outDir, { recursive: true });
  const jsonPath = path.join(outDir, "atlas_graph_search_selftest.json");
  const mdPath = path.join(outDir, "atlas_graph_search_selftest.md");
  await writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  await writeFile(mdPath, markdownReport(report), "utf8");
  return { outDir, jsonPath, mdPath };
}

function markdownReport(report) {
  const lines = [
    "# Atlas Graph Search Self-Test",
    "",
    `Generated: ${report.generatedAt}`,
    "",
    "## Summary",
    "",
    `- decision: \`${report.decision}\``,
    `- seeds: \`${report.summary.seedCount}\``,
    `- pass: \`${report.summary.passCount}\``,
    `- fail: \`${report.summary.failCount}\``,
    `- exact top3: \`${report.summary.exactTop3Count}\``,
    `- related detail: \`${report.summary.relatedCount}\``,
    `- profile history: \`${report.summary.profileCount}\``,
    `- seed p95: \`${report.summary.seedLatencyMs.p95}ms\``,
    `- profile p95: \`${report.summary.profileLatencyMs.p95}ms\``,
    "",
    "## Results",
    "",
    "| query | expected | pass | matched | rank | related | profile | graph | seed ms | profile ms |",
    "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
  ];
  for (const row of report.results) {
    lines.push(
      `| ${row.query.replace(/\|/g, "\\|")} | ${row.expectedName.replace(/\|/g, "\\|")} | ${row.pass ? "PASS" : "FAIL"} | ${
        (row.matchedNode?.label || "").replace(/\|/g, "\\|")
      } | ${row.matchedNode?.rank ?? -1} | ${row.apiRelated.entities + row.apiRelated.events} | ${
        row.profile.sourceArticles
      }/${row.profile.events}/${row.profile.relationships} | ${row.graph.nodes}/${row.graph.edges} | ${row.timingsMs.seed} | ${row.timingsMs.profile} |`,
    );
  }
  if (report.recommendations.length) {
    lines.push("", "## Recommendations", "");
    for (const item of report.recommendations) {
      lines.push(`- \`${item.code}\`: ${item.message}`);
    }
  }
  lines.push("", "## Safety", "", "- No model call, vector write, graph write, mem0 write, or SQLite mutation is executed by this self-test.");
  return `${lines.join("\n")}\n`;
}

export async function runAtlasGraphSearchSelfTest(options = {}) {
  const dbPath = path.resolve(options.dbPath || defaultDbPath);
  const env = {
    ...process.env,
    STAGE7_ATLAS_SQLITE_DB: dbPath,
    ATLAS_SQLITE_READONLY: "1",
  };
  const store = new Stage7AtlasSqliteStore({ env, stage7SqliteDbPath: dbPath });
  const db = await store.db();
  const config = {
    manualSeeds: options.manualSeeds || splitSeeds(options.seeds),
    autoLimit: intOption(options.autoLimit, 12, 0, 100),
    maxSeeds: intOption(options.maxSeeds, 16, 1, 100),
    minConfidence: floatOption(options.minConfidence, 0.9, 0, 1),
    minRelated: intOption(options.minRelated, 2, 1, 100),
    graphLimit: intOption(options.graphLimit, 100, 10, 300),
    subgraphLimit: intOption(options.subgraphLimit, 80, 10, 300),
    relatedLimit: intOption(options.relatedLimit, 20, 1, 50),
    minGraphNodes: intOption(options.minGraphNodes, 3, 1, 300),
    minGraphEdges: intOption(options.minGraphEdges, 2, 0, 800),
    minSubgraphNodes: intOption(options.minSubgraphNodes, 3, 1, 300),
    minSubgraphEdges: intOption(options.minSubgraphEdges, 2, 0, 800),
    seedLatencyBudgetMs: intOption(options.seedLatencyBudgetMs, 250, 1, 10_000),
    profileLimit: intOption(options.profileLimit, 40, 10, 120),
    profileSourceLimit: intOption(options.profileSourceLimit, 2_000, 100, 20_000),
    profileLatencyBudgetMs: intOption(options.profileLatencyBudgetMs, 1200, 10, 30_000),
  };
  const servingReadModel = store.isServingReadModel(db);
  const manualRows = servingReadModel
    ? selectServingManualSeedRows(db, store, config.manualSeeds)
    : selectManualSeedRows(db, store, config.manualSeeds);
  const autoRows = config.autoLimit > 0
    ? (servingReadModel ? selectServingAutoSeedRows(db, config) : selectAutoSeedRows(db, store, config))
    : [];
  const seeds = mergeSeeds(manualRows, autoRows, config.maxSeeds);
  const results = [];
  for (const seed of seeds) {
    results.push(await evaluateSeed(store, seed, config));
  }
  const summary = summarize(results, config);
  const report = {
    schemaVersion: "atlas_graph_search_selftest.v1",
    generatedAt: new Date().toISOString(),
    decision: summary.failCount === 0 && summary.seedLatencyMs.withinBudget && summary.profileLatencyMs.withinBudget ? "PASS" : "WARN",
    dbIdentity: store.publicDbIdentity(),
    dbPath: options.exposeDbPath ? dbPath : "",
    config: {
      ...config,
      manualSeeds: config.manualSeeds,
    },
    summary,
    recommendations: recommendations(results, summary),
    results,
    safety: {
      modelCallExecuted: false,
      llmCallExecuted: false,
      qdrantWriteExecuted: false,
      neo4jWriteExecuted: false,
      mem0WriteExecuted: false,
      sqliteWriteExecuted: false,
      readOnlySqlite: true,
    },
  };
  if (options.writeReport !== false) {
    report.artifacts = await writeReport(report, path.resolve(options.outRoot || defaultOutRoot));
  }
  if (typeof store.dbHandle?.close === "function") store.dbHandle.close();
  return report;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const options = parseArgs();
  runAtlasGraphSearchSelfTest(options)
    .then((report) => {
      const line = {
        decision: report.decision,
        summary: report.summary,
        artifacts: report.artifacts || null,
        recommendations: report.recommendations,
      };
      console.log(JSON.stringify(line, null, 2));
      if (options.failOnWarn && report.decision !== "PASS") process.exitCode = 1;
    })
    .catch((error) => {
      console.error(error?.stack || error);
      process.exitCode = 1;
    });
}
