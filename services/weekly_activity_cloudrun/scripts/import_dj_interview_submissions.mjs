#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
import { importDjInterviewSubmissions } from "../src/interviewIntake.mjs";
import { writeDjInterviewReviewPacket } from "../src/interviewReviewPacket.mjs";
import { writeDjInterviewReviewWorkbench } from "../src/interviewReviewWorkbench.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const defaultOutDir = path.resolve(moduleDir, "../../../tools/stage7_rewrite/reports/dj_interview_review_packet_current");

function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return "";
  return process.argv[index + 1] || "";
}

function intArg(name, fallback) {
  const parsed = Number.parseInt(argValue(name), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function hasArg(name) {
  return process.argv.includes(name);
}

if (hasArg("--help") || hasArg("-h")) {
  console.log([
    "Usage: node services/weekly_activity_cloudrun/scripts/import_dj_interview_submissions.mjs --input <file-or-dir> [options]",
    "",
    "Input formats: .md/.markdown with front matter, .json, .jsonl.",
    "",
    "Options:",
    "  --interview-dir <dir>  DJ interview sidecar directory; defaults to DJ_INTERVIEW_SUBMISSIONS_DIR or service data dir.",
    "  --dry-run              Parse and validate only; no sidecar write.",
    "  --write-packet         After import, write redacted review packet.",
    "  --write-workbench      After import, write redacted review packet and HTML workbench.",
    "  --out-dir <dir>        Packet/workbench output directory; defaults to tools/stage7_rewrite/reports/dj_interview_review_packet_current.",
    "  --limit <n>            Packet/workbench review row limit, default 200.",
    "",
    "Consent is required: consentInternal/internalConsent or consent.internalProcessing must be true.",
    "Output is redacted and does not print raw contact, raw interview text, or media URLs.",
  ].join("\n"));
  process.exit(0);
}

const inputPath = argValue("--input");
if (!inputPath) {
  console.error("Missing required --input <file-or-dir>.");
  process.exit(2);
}

const interviewDir = argValue("--interview-dir") || process.env.DJ_INTERVIEW_SUBMISSIONS_DIR || "";
const outDir = path.resolve(argValue("--out-dir") || defaultOutDir);
const limit = intArg("--limit", 200);
const storeOptions = interviewDir ? { interviewDir } : {};
const store = createDjInterviewStore(storeOptions);
const result = await importDjInterviewSubmissions({
  inputPath,
  store,
  dryRun: hasArg("--dry-run"),
});

let packetResult = null;
let workbenchResult = null;
if (result.ok && !result.dryRun && (hasArg("--write-packet") || hasArg("--write-workbench"))) {
  packetResult = await writeDjInterviewReviewPacket({ store, outDir, limit });
}
if (result.ok && !result.dryRun && hasArg("--write-workbench")) {
  workbenchResult = await writeDjInterviewReviewWorkbench({ store, outDir, limit });
}

console.log(JSON.stringify({
  ok: result.ok,
  schemaVersion: result.schemaVersion,
  dryRun: result.dryRun,
  total: result.total,
  accepted: result.accepted,
  rejected: result.rejected,
  imported: result.imported || 0,
  rejectedItems: result.rejectedItems,
  items: result.items,
  packetPath: packetResult?.jsonPath || "",
  workbenchPath: workbenchResult?.htmlPath || "",
  safety: result.safety,
}, null, 2));

if (!result.ok) process.exit(2);
