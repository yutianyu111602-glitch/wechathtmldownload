#!/usr/bin/env node
import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { storageSlug, WeeklyActivityDataStore } from "../src/dataStore.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const defaultDataDir = path.resolve(moduleDir, "../data/current_release");

function parseArgs(argv) {
  const options = {
    dataDir: defaultDataDir,
    force: false,
    allReleaseItems: false,
    lookbackDays: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--data-dir") options.dataDir = argv[++i];
    else if (arg.startsWith("--data-dir=")) options.dataDir = arg.slice("--data-dir=".length);
    else if (arg === "--force") options.force = true;
    else if (arg === "--all-release-items") options.allReleaseItems = true;
    else if (arg === "--lookback-days") options.lookbackDays = Number.parseInt(argv[++i], 10);
    else if (arg.startsWith("--lookback-days=")) options.lookbackDays = Number.parseInt(arg.slice("--lookback-days=".length), 10);
    else throw new Error(`Unknown argument: ${arg}`);
  }
  options.lookbackDays = Number.isFinite(options.lookbackDays) && options.lookbackDays > 0 ? Math.min(options.lookbackDays, 45) : null;
  if (options.allReleaseItems && options.lookbackDays !== null) {
    throw new Error("--all-release-items and --lookback-days are mutually exclusive.");
  }
  return options;
}

function stableHash(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function first(value, fallback = "") {
  if (Array.isArray(value)) return value.find((item) => String(item || "").trim()) || fallback;
  return value || fallback;
}

function asArray(value) {
  if (Array.isArray(value)) return value.filter((item) => String(item || "").trim());
  return String(value || "").trim() ? [String(value).trim()] : [];
}

function itemDigest(item) {
  return stableHash({
    id: item.id,
    title: item.title || item.display_title || "",
    city: item.city || item.city_key || first(item.city_keys, ""),
    venue: item.venue_name || item.venue || "",
    date: item.event_date_start || item.event_date_iso_guess || first(item.event_date_iso_guesses, ""),
    time: item.event_time_text || item.running_hours_text || "",
    lineup: item.lineup || item.lineup_artists || item.artist_lineup || [],
    sound_system: item.sound_system || item.sound_systems || item.sound_system_text || item.audio_system || "",
    description: item.description || item.description_zh || item.description_original_lines || "",
    quality_status: item.quality_status || "",
  });
}

async function writeJson(filePath, payload) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

async function loadAllReleaseItems(dataDir) {
  const current = JSON.parse(await readFile(path.join(dataDir, "current.json"), "utf8"));
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

function itemTitle(item) {
  return item.title_display || item.display_title || item.title || item.name || item.id || "";
}

function itemDate(item) {
  return item.event_date_start || item.event_date_iso_guess || first(item.event_date_iso_guesses, "");
}

function itemEndDate(item) {
  return item.event_date_end || itemDate(item);
}

function dateKey(value) {
  const match = String(value || "").match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function chinaDateKey(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function compareByStartDateAsc(a, b) {
  const dateCompare = dateKey(itemDate(a)).localeCompare(dateKey(itemDate(b)));
  if (dateCompare !== 0) return dateCompare;
  return itemTitle(a).localeCompare(itemTitle(b), "zh-Hans-CN");
}

function compareByStartDateDesc(a, b) {
  return compareByStartDateAsc(b, a);
}

function itemCity(item) {
  return first(item.city, item.city_name || item.city_key || first(item.city_keys, ""));
}

function itemVenue(item) {
  return item.venue_name || first(item.venue, "") || item.promoter || item.account || "";
}

function itemAddress(item) {
  return item.address_full || item.address || item.address_candidate || "";
}

function itemStyles(item) {
  return [
    ...asArray(item.music_styles),
    ...asArray(item.style_tags),
    ...asArray(item.genres),
  ];
}

function itemLineup(item) {
  return [
    ...asArray(item.lineup_artists),
    ...asArray(item.lineup),
    ...asArray(item.artist_lineup),
  ];
}

function itemSoundSystem(item) {
  return [
    ...asArray(item.sound_system),
    ...asArray(item.sound_systems),
    ...asArray(item.sound_system_text),
    ...asArray(item.audio_system),
  ].slice(0, 4);
}

function itemSoundSystemEvidence(item) {
  return [
    ...asArray(item.sound_system_evidence),
    ...asArray(item.audio_system_evidence),
  ].slice(0, 4);
}

function itemDescriptionLines(item) {
  const lines = [
    ...asArray(item.description_original_lines),
    ...asArray(item.description),
    ...asArray(item.description_zh),
    ...asArray(item.evidence_text),
  ];
  return lines.slice(0, 6);
}

function sourceGroundedEnrichment(item) {
  const reviewFlags = [
    ...asArray(item.review_flags),
    ...asArray(item.quality_warnings),
  ];
  if (!item.event_time_text && !item.running_hours_text) reviewFlags.push("missing_time");
  // address sourced from venue database — no longer a review concern
  return {
    schema_version: "weekly_event_extract.v1",
    is_event: true,
    title_display: itemTitle(item),
    event_date_start: itemDate(item) || null,
    event_date_end: itemEndDate(item) || null,
    event_time_text: item.event_time_text || item.running_hours_text || null,
    city_name: itemCity(item),
    venue_name: itemVenue(item),
    address_candidate: itemAddress(item) || null,
    lineup_artists: itemLineup(item),
    music_styles: itemStyles(item),
    sound_system: itemSoundSystem(item),
    sound_system_evidence: itemSoundSystemEvidence(item),
    sound_system_confidence: itemSoundSystem(item).length > 0 ? 0.95 : null,
    dj_bio_lines: asArray(item.dj_bio_lines).slice(0, 4),
    description_original_lines: itemDescriptionLines(item),
    ticketing_text: asArray(item.ticketing_text).slice(0, 5),
    dedupe_signals: [itemTitle(item), itemDate(item), itemCity(item), itemVenue(item)].filter(Boolean),
    review_flags: [...new Set(reviewFlags)],
    notes: [
      "source-grounded deterministic materialization; no model call executed",
      "fields are copied from the release package to prevent stale LLM output reuse",
    ],
  };
}

function buildSummary(items, generatedAt) {
  const cityBreakdown = {};
  const styleDistribution = {};
  const artists = new Map();
  for (const item of items) {
    const city = item.city_key || itemCity(item) || "unknown";
    cityBreakdown[city] = (cityBreakdown[city] || 0) + 1;
    for (const style of itemStyles(item)) {
      const key = String(style).trim().toLowerCase();
      if (key) styleDistribution[key] = (styleDistribution[key] || 0) + 1;
    }
    for (const artist of itemLineup(item)) {
      const key = String(artist).trim();
      if (key) artists.set(key, (artists.get(key) || 0) + 1);
    }
  }
  const today = chinaDateKey(generatedAt);
  const currentOrUpcoming = today
    ? items.filter((item) => {
        const end = dateKey(itemEndDate(item));
        return end && end >= today;
      })
    : [];
  const highlightSource = (currentOrUpcoming.length ? currentOrUpcoming.sort(compareByStartDateAsc) : [...items].sort(compareByStartDateDesc)).slice(0, 4);
  const highlightEvents = highlightSource.map((item) => ({
    title: itemTitle(item),
    reason_zh: `源字段显示 ${itemCity(item) || "未知城市"} / ${itemVenue(item) || "未知场地"} / ${itemDate(item) || "未知日期"}；未调用模型。`,
    reason_en: `Source fields show ${itemCity(item) || "unknown city"} / ${itemVenue(item) || "unknown venue"} / ${itemDate(item) || "unknown date"}; no model call was made.`,
  }));
  return {
    schemaVersion: "weekly_activity_api.materialized_summary.v1",
    generatedAt,
    provider: "source-grounded",
    model: "deterministic-release-fields",
    thinking: "disabled",
    itemCount: items.length,
    summary: {
      highlight_events: highlightEvents,
      city_breakdown: cityBreakdown,
      trending_artists: [...artists.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([name]) => name),
      style_distribution: styleDistribution,
      editor_note_zh: "本摘要由当前发布包结构化字段生成，未调用 DeepSeek 或其他付费模型；用于保证生产 API 与 release 一致。",
      editor_note_en: "This summary was generated from structured release fields only. No DeepSeek or paid model call was executed.",
    },
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const dataDir = path.resolve(options.dataDir);
  const store = new WeeklyActivityDataStore({ baseDir: dataDir });
  const items = options.allReleaseItems
    ? await loadAllReleaseItems(dataDir)
    : await loadAllCurrentItems(store, { lookbackDays: options.lookbackDays });
  if (!items.length) throw new Error(`no READY items found in ${dataDir}`);

  const llmDir = path.join(dataDir, "llm");
  if (options.force) {
    await rm(llmDir, { recursive: true, force: true });
  }
  const enrichDir = path.join(llmDir, "enrichments");
  await mkdir(enrichDir, { recursive: true });

  const generatedAt = new Date().toISOString();
  const index = {
    schemaVersion: "weekly_activity_api.materialized_enrichment_index.v1",
    generatedAt,
    provider: "source-grounded",
    model: "deterministic-release-fields",
    thinking: "disabled",
    itemCount: items.length,
    allReleaseItems: options.allReleaseItems,
    lookbackDays: options.lookbackDays,
    enrichments: [],
  };

  for (const item of items) {
    const safeId = storageSlug(item.id);
    const relativePath = `llm/enrichments/${safeId}.json`;
    const payload = {
      schemaVersion: "weekly_activity_api.materialized_enrichment.v1",
      generatedAt,
      id: item.id,
      sourceItemHash: itemDigest(item),
      enriched: {
        provider: "source-grounded",
        model: "deterministic-release-fields",
        usage: {
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
        },
        enrichment: sourceGroundedEnrichment(item),
      },
    };
    await writeJson(path.join(dataDir, relativePath), payload);
    index.enrichments.push({ id: item.id, sourceItemHash: payload.sourceItemHash, path: relativePath });
  }

  index.enrichments.sort((a, b) => a.id.localeCompare(b.id));
  await writeJson(path.join(llmDir, "weekly_summary.json"), buildSummary(items, generatedAt));
  await writeJson(path.join(llmDir, "enrichment_index.json"), index);
  const report = {
    schemaVersion: "weekly_activity_api.source_grounded_materialize_report.v1",
    generatedAt,
    provider: "source-grounded",
    model: "deterministic-release-fields",
    itemCount: items.length,
    allReleaseItems: options.allReleaseItems,
    lookbackDays: options.lookbackDays,
    summaryWritten: true,
    enrichWritten: items.length,
    llmCallExecuted: false,
    paidApiUsed: false,
  };
  await writeJson(path.join(llmDir, "materialize_report.json"), report);
  console.log(JSON.stringify(report, null, 2));
}

main().catch((err) => {
  console.error(`[source-grounded-materialize] ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
