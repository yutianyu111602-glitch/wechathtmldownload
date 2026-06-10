#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { storageSlug } from "../src/dataStore.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const defaultDataDir = path.resolve(moduleDir, "../data/current_release");

function parseArgs(argv) {
  const options = {
    dataDir: process.env.WEEKLY_ACTIVITY_API_DIR || defaultDataDir,
    reportDir: "",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--data-dir") options.dataDir = argv[++i];
    else if (arg.startsWith("--data-dir=")) options.dataDir = arg.slice("--data-dir=".length);
    else if (arg === "--report-dir") options.reportDir = argv[++i];
    else if (arg.startsWith("--report-dir=")) options.reportDir = arg.slice("--report-dir=".length);
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return options;
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function writeJson(filePath, payload) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function asArray(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || "").trim()).filter(Boolean);
  const text = String(value || "").trim();
  return text ? [text] : [];
}

function normalizeName(value) {
  return String(value || "").toLowerCase().replace(/[\s_\-–—|｜/\\:：,，.。()（）"'`]+/g, "");
}

const CONCRETE_SOUND_SYSTEM_PATTERN =
  /(funktion|functionone|\bf1\b|void|d&b|d\s*&\s*b|l-acoustics|lacoustics|meyer|kv2|nexo|martinaudio|音响系统|音響系統)/i;
const REJECT_CONTEXT_PATTERN = /(成员|member|culture|文化|靠近音箱|close to speaker|close to the speaker|sound systems and late-night dance floors)/i;

function cleanSoundSystemName(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .replace(/^(?:音响系统|音響系統|sound\s*system|soundsystem)\s*[:：\-–—]?\s*/i, "")
    .trim();
}

function acceptedSoundSystems(enrichment) {
  const evidence = asArray(enrichment.sound_system_evidence);
  const out = [];
  const seen = new Set();
  for (const raw of asArray(enrichment.sound_system)) {
    const cleaned = cleanSoundSystemName(raw);
    const context = `${cleaned}\n${evidence.join("\n")}`;
    if (!CONCRETE_SOUND_SYSTEM_PATTERN.test(normalizeName(cleaned)) && !CONCRETE_SOUND_SYSTEM_PATTERN.test(context)) {
      continue;
    }
    if (REJECT_CONTEXT_PATTERN.test(context)) continue;
    const key = normalizeName(cleaned);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(cleaned);
    if (out.length >= 4) break;
  }
  return out;
}

function mergeSoundFields(item, enrichment, systems) {
  const evidence = asArray(enrichment.sound_system_evidence).slice(0, 4);
  return {
    ...item,
    sound_system: systems,
    sound_system_evidence: evidence,
    sound_system_confidence: Number.isFinite(enrichment.sound_system_confidence)
      ? enrichment.sound_system_confidence
      : 0.9,
    sound_system_source: "deepseek_source_queue",
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const dataDir = path.resolve(options.dataDir);
  const currentPath = path.join(dataDir, "current.json");
  const current = await readJson(currentPath);
  if (!Array.isArray(current.items)) throw new Error(`No current.items array found in ${currentPath}`);

  const report = {
    schemaVersion: "weekly_activity_api.sound_system_apply_report.v1",
    generatedAt: new Date().toISOString(),
    dataDir,
    itemCount: current.items.length,
    enrichmentReadCount: 0,
    updatedItemCount: 0,
    skippedNoEnrichmentCount: 0,
    skippedNoAcceptedSoundSystemCount: 0,
    updated: [],
  };

  const nextItems = [];
  for (const item of current.items) {
    const safeId = storageSlug(item.id);
    let enrichmentPayload = null;
    try {
      enrichmentPayload = await readJson(path.join(dataDir, "llm", "enrichments", `${safeId}.json`));
    } catch {
      report.skippedNoEnrichmentCount += 1;
      nextItems.push(item);
      continue;
    }
    report.enrichmentReadCount += 1;
    const enrichment = enrichmentPayload.enriched?.enrichment || {};
    const systems = acceptedSoundSystems(enrichment);
    if (!systems.length) {
      report.skippedNoAcceptedSoundSystemCount += 1;
      nextItems.push(item);
      continue;
    }
    const updatedItem = mergeSoundFields(item, enrichment, systems);
    nextItems.push(updatedItem);
    report.updatedItemCount += 1;
    report.updated.push({
      id: item.id,
      title: item.title || item.display_title || "",
      sound_system: updatedItem.sound_system,
      evidence: updatedItem.sound_system_evidence,
    });

    const detailPath = path.join(dataDir, "by-id", `${safeId}.json`);
    try {
      const detail = await readJson(detailPath);
      if (detail.item) {
        detail.item = mergeSoundFields(detail.item, enrichment, systems);
        await writeJson(detailPath, detail);
      }
    } catch {
      // Detail fallback can still serve from current.json.
    }
  }

  current.items = nextItems;
  await writeJson(currentPath, current);
  const reportPath = options.reportDir
    ? path.join(path.resolve(options.reportDir), "sound_system_apply_report.json")
    : path.join(dataDir, "llm", "sound_system_apply_report.json");
  await writeJson(reportPath, report);
  console.log(JSON.stringify(report, null, 2));
}

main().catch((err) => {
  console.error(`[sound-system-apply] ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
