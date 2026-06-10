#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createDeepSeekClient } from "../src/deepSeekClient.mjs";
import { WeeklyActivityDataStore, storageSlug } from "../src/dataStore.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const defaultDataDir = path.resolve(moduleDir, "../data/current_release");

function parseArgs(argv) {
  const options = {
    dataDir: process.env.WEEKLY_ACTIVITY_API_DIR || defaultDataDir,
    enrichLimit: Number.parseInt(process.env.LLM_ENRICH_LIMIT || "0", 10),
    concurrency: Number.parseInt(process.env.LLM_ENRICH_CONCURRENCY || "2", 10),
    summaryOnly: false,
    force: false,
    dryRun: false,
    allReleaseItems: false,
    lookbackDays: null,
    sourceQueuePath: process.env.WEEKLY_ACTIVITY_SOURCE_QUEUE_PATH || "",
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--data-dir") options.dataDir = argv[++i];
    else if (arg.startsWith("--data-dir=")) options.dataDir = arg.slice("--data-dir=".length);
    else if (arg === "--enrich-limit") options.enrichLimit = Number.parseInt(argv[++i], 10);
    else if (arg.startsWith("--enrich-limit=")) options.enrichLimit = Number.parseInt(arg.slice("--enrich-limit=".length), 10);
    else if (arg === "--concurrency") options.concurrency = Number.parseInt(argv[++i], 10);
    else if (arg.startsWith("--concurrency=")) options.concurrency = Number.parseInt(arg.slice("--concurrency=".length), 10);
    else if (arg === "--summary-only") options.summaryOnly = true;
    else if (arg === "--force") options.force = true;
    else if (arg === "--dry-run") options.dryRun = true;
    else if (arg === "--all-release-items") options.allReleaseItems = true;
    else if (arg === "--lookback-days") options.lookbackDays = Number.parseInt(argv[++i], 10);
    else if (arg.startsWith("--lookback-days=")) options.lookbackDays = Number.parseInt(arg.slice("--lookback-days=".length), 10);
    else if (arg === "--source-queue") options.sourceQueuePath = argv[++i] || "";
    else if (arg.startsWith("--source-queue=")) options.sourceQueuePath = arg.slice("--source-queue=".length);
    else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  options.enrichLimit = Number.isFinite(options.enrichLimit) && options.enrichLimit > 0 ? options.enrichLimit : 0;
  options.concurrency = Number.isFinite(options.concurrency) && options.concurrency > 0 ? Math.min(options.concurrency, 4) : 2;
  options.lookbackDays = Number.isFinite(options.lookbackDays) && options.lookbackDays > 0 ? Math.min(options.lookbackDays, 45) : null;
  if (options.allReleaseItems && options.lookbackDays !== null) {
    throw new Error("--all-release-items and --lookback-days are mutually exclusive.");
  }
  return options;
}

function stableHash(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function itemDigest(item) {
  return stableHash({
    id: item.id,
    title: item.title || item.display_title || "",
    city: item.city || item.city_key || "",
    venue: item.venue_name || item.venue || "",
    date: item.event_date_iso_guess || item.event_date_start || "",
    time: item.event_time_text || "",
    price: item.price || [],
    price_text: item.price_text || "",
    ticketing_text: item.ticketing_text || "",
    sound_system: item.sound_system || item.sound_systems || item.sound_system_text || item.audio_system || "",
    sound_system_evidence: item.sound_system_evidence || item.audio_system_evidence || [],
    source_article_title: item.source_article_title || "",
    source_article_summary_digest: item.source_article_summary_digest || "",
    source_article_digest: item.source_article_digest || "",
    source_sound_system_snippets: item.source_sound_system_snippets || [],
    lineup: item.lineup || item.artist_lineup || [],
    description: item.description || item.description_zh || "",
    description_original_lines: item.description_original_lines || [],
    source_action_hash: item.source_action?.url_hash || "",
    quality_status: item.quality_status || "",
  });
}

async function readJsonIfExists(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

async function writeJson(filePath, payload) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function truncateText(value, maxLength) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function sourceUrlHash(sourceUrl) {
  return createHash("sha256").update(String(sourceUrl || "")).digest("hex").slice(0, 16);
}

const SOUND_SYSTEM_SNIPPET_PATTERN =
  /(funktion|function[-\s]?one|\bF1\b|void|d&b|d\s*&\s*b|l-acoustics|l acoustics|meyer|kv2|nexo|martin audio|oil soundsystem|sound\s*system|soundsystem|音响系统|音響系統)/gi;

function extractSoundSystemSnippets(value) {
  const text = String(value || "");
  const snippets = [];
  const seen = new Set();
  for (const match of text.matchAll(SOUND_SYSTEM_SNIPPET_PATTERN)) {
    const start = Math.max(0, match.index - 90);
    const end = Math.min(text.length, match.index + 210);
    const snippet = truncateText(text.slice(start, end), 360);
    const key = snippet.toLowerCase();
    if (!snippet || seen.has(key)) continue;
    seen.add(key);
    snippets.push(snippet);
    if (snippets.length >= 4) break;
  }
  return snippets;
}

async function loadManifestSourceQueuePath(dataDir) {
  const manifest = await readJsonIfExists(path.join(dataDir, "manifest.json"));
  return manifest?.source_queue_path || "";
}

async function loadSourceQueueIndex(sourceQueuePath) {
  if (!sourceQueuePath) return { sourceQueuePath: "", rows: 0, matchedRows: 0, byHash: new Map() };
  const raw = await readFile(sourceQueuePath, "utf8");
  const byHash = new Map();
  let rows = 0;
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    rows += 1;
    let row;
    try {
      row = JSON.parse(trimmed);
    } catch {
      continue;
    }
    const hash = sourceUrlHash(row.source_url);
    if (!hash || !row.source_url) continue;
    const existing = byHash.get(hash);
    if (existing && (existing.body_text_chars || 0) >= (row.body_text_chars || 0)) continue;
    byHash.set(hash, {
      title: row.title || "",
      summary_digest: truncateText(row.summary_digest || "", 1000),
      digest: truncateText(row.digest || "", 3200),
      sound_system_snippets: extractSoundSystemSnippets(row.digest || ""),
      post_date: row.post_date || "",
      body_text_chars: row.body_text_chars || 0,
      body_text_source: row.body_text_source || "",
    });
  }
  return { sourceQueuePath, rows, matchedRows: byHash.size, byHash };
}

function augmentItemsWithSourceQueue(items, sourceQueueIndex) {
  if (!sourceQueueIndex?.byHash?.size) return { items, sourceQueueMatchedItems: 0 };
  let sourceQueueMatchedItems = 0;
  const augmented = items.map((item) => {
    const urlHash = item.source_action?.url_hash || item.source_article?.url_hash || "";
    const sourceRow = sourceQueueIndex.byHash.get(urlHash);
    if (!sourceRow) return item;
    sourceQueueMatchedItems += 1;
    return {
      ...item,
      source_article_title: sourceRow.title,
      source_article_summary_digest: sourceRow.summary_digest,
      source_article_digest: sourceRow.digest,
      source_sound_system_snippets: sourceRow.sound_system_snippets,
      source_article_post_date: sourceRow.post_date,
      source_body_text_chars: sourceRow.body_text_chars,
      source_body_text_source: sourceRow.body_text_source,
    };
  });
  return { items: augmented, sourceQueueMatchedItems };
}

async function mapWithConcurrency(items, concurrency, worker) {
  let cursor = 0;
  const results = new Array(items.length);
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

async function withRetry(label, fn, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt < attempts) {
        console.error(`[llm-materialize] retry ${attempt}/${attempts} for ${label}: ${err.message || err}`);
      }
    }
  }
  throw lastError;
}

async function loadAllReleaseItems(dataDir) {
  const current = await readJsonIfExists(path.join(dataDir, "current.json"));
  if (!Array.isArray(current?.items)) {
    throw new Error(`No current.items array found in ${path.join(dataDir, "current.json")}`);
  }
  return current.items;
}

async function loadAllCurrentItems(store, { lookbackDays } = {}) {
  const items = [];
  let cursor = "0";
  for (;;) {
    const page = await store.getCurrent({ limit: 100, cursor, lookbackDays });
    items.push(...page.items);
    const nextCursor = page.page?.nextCursor;
    if (!nextCursor) break;
    cursor = nextCursor;
  }
  return items;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const store = new WeeklyActivityDataStore({ baseDir: options.dataDir });
  const client = createDeepSeekClient(process.env);
  const status = client.publicStatus();
  if (!status.configured) {
    throw new Error("DEEPSEEK_API_KEY is not configured.");
  }

  const baseItems = options.allReleaseItems
    ? await loadAllReleaseItems(options.dataDir)
    : await loadAllCurrentItems(store, { lookbackDays: options.lookbackDays });
  const sourceQueuePath = options.sourceQueuePath || await loadManifestSourceQueuePath(options.dataDir);
  const sourceQueueIndex = await loadSourceQueueIndex(sourceQueuePath);
  const { items, sourceQueueMatchedItems } = augmentItemsWithSourceQueue(baseItems, sourceQueueIndex);
  const llmDir = path.join(options.dataDir, "llm");
  const enrichDir = path.join(llmDir, "enrichments");
  const generatedAt = new Date().toISOString();
  const run = {
    schemaVersion: "weekly_activity_api.llm_materialize_report.v1",
    generatedAt,
    provider: status.provider,
    model: status.model,
    thinking: status.thinking,
    timeoutMs: status.timeoutMs,
    itemCount: items.length,
    allReleaseItems: options.allReleaseItems,
    lookbackDays: options.lookbackDays,
    sourceQueuePath: sourceQueueIndex.sourceQueuePath || null,
    sourceQueueRows: sourceQueueIndex.rows,
    sourceQueueIndexSize: sourceQueueIndex.matchedRows,
    sourceQueueMatchedItems,
    summaryWritten: false,
    enrichRequested: options.summaryOnly ? 0 : options.enrichLimit || items.length,
    enrichWritten: 0,
    enrichSkipped: 0,
    enrichFailed: 0,
    enrichErrors: [],
    dryRun: options.dryRun,
  };

  if (options.dryRun) {
    console.log(JSON.stringify(run, null, 2));
    return;
  }

  const summary = await withRetry("weekly-summary", () => client.generateWeeklySummary(items));
  const summaryPayload = {
    schemaVersion: "weekly_activity_api.materialized_summary.v1",
    generatedAt,
    provider: status.provider,
    model: status.model,
    thinking: status.thinking,
    itemCount: items.length,
    summary,
  };
  await writeJson(path.join(llmDir, "weekly_summary.json"), summaryPayload);
  run.summaryWritten = true;

  if (!options.summaryOnly) {
    await rm(enrichDir, { recursive: true, force: true });
    const index = {
      schemaVersion: "weekly_activity_api.materialized_enrichment_index.v1",
      generatedAt,
      provider: status.provider,
      model: status.model,
      thinking: status.thinking,
      itemCount: items.length,
      enrichments: [],
    };
    const targetItems = options.enrichLimit > 0 ? items.slice(0, options.enrichLimit) : items;
    await mapWithConcurrency(targetItems, options.concurrency, async (item) => {
      const digest = itemDigest(item);
      const safeId = storageSlug(item.id);
      const relativePath = `llm/enrichments/${safeId}.json`;
      const outputPath = path.join(options.dataDir, relativePath);
      const existing = await readJsonIfExists(outputPath);
      if (!options.force && existing?.sourceItemHash === digest) {
        run.enrichSkipped += 1;
        index.enrichments.push({ id: item.id, sourceItemHash: digest, path: relativePath });
        return;
      }

      let enriched;
      try {
        enriched = await withRetry(`enrich:${item.id}`, () => client.enrichEvent(item));
      } catch (err) {
        run.enrichFailed += 1;
        run.enrichErrors.push({
          id: item.id,
          title: item.title || item.display_title || "",
          error: err instanceof Error ? err.message : String(err),
        });
        return;
      }
      await writeJson(outputPath, {
        schemaVersion: "weekly_activity_api.materialized_enrichment.v1",
        generatedAt,
        id: item.id,
        sourceItemHash: digest,
        enriched,
      });
      run.enrichWritten += 1;
      index.enrichments.push({ id: item.id, sourceItemHash: digest, path: relativePath });
    });
    index.enrichments.sort((a, b) => a.id.localeCompare(b.id));
    await writeJson(path.join(llmDir, "enrichment_index.json"), index);
  }

  await writeJson(path.join(llmDir, "materialize_report.json"), run);
  console.log(JSON.stringify(run, null, 2));
}

main().catch((err) => {
  console.error(`[llm-materialize] ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
