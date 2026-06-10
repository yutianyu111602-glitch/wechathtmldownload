#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
import { writeDjInterviewReviewPacket } from "../src/interviewReviewPacket.mjs";

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
    "Usage: node services/weekly_activity_cloudrun/scripts/build_dj_interview_review_packet.mjs [options]",
    "",
    "Options:",
    "  --interview-dir <dir>  DJ interview sidecar directory; defaults to DJ_INTERVIEW_SUBMISSIONS_DIR or service data dir.",
    "  --out-dir <dir>        Output directory; defaults to tools/stage7_rewrite/reports/dj_interview_review_packet_current.",
    "  --limit <n>            Max review rows, default 200.",
    "",
    "Output is redacted and does not export raw contact, raw interview text, or media.",
  ].join("\n"));
  process.exit(0);
}

const interviewDir = argValue("--interview-dir") || process.env.DJ_INTERVIEW_SUBMISSIONS_DIR || "";
const outDir = path.resolve(argValue("--out-dir") || defaultOutDir);
const limit = intArg("--limit", 200);
const storeOptions = interviewDir ? { interviewDir } : {};
const store = createDjInterviewStore(storeOptions);
const result = await writeDjInterviewReviewPacket({ store, outDir, limit });

console.log(JSON.stringify({
  ok: true,
  schemaVersion: result.packet.schemaVersion,
  exported: result.packet.summary.exported,
  jsonPath: result.jsonPath,
  markdownPath: result.markdownPath,
  safety: result.packet.safety,
}, null, 2));
