#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
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

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log([
    "Usage: node services/weekly_activity_cloudrun/scripts/build_dj_interview_review_workbench.mjs [options]",
    "",
    "Options:",
    "  --interview-dir <dir>  DJ interview sidecar directory; defaults to DJ_INTERVIEW_SUBMISSIONS_DIR or service data dir.",
    "  --out-dir <dir>        Output directory; defaults to tools/stage7_rewrite/reports/dj_interview_review_packet_current.",
    "  --limit <n>            Max review rows, default 200.",
    "",
    "Output is a local read-only HTML workbench. It does not export raw contact, raw interview text, or media.",
  ].join("\n"));
  process.exit(0);
}

const interviewDir = argValue("--interview-dir") || process.env.DJ_INTERVIEW_SUBMISSIONS_DIR || "";
const outDir = path.resolve(argValue("--out-dir") || defaultOutDir);
const limit = intArg("--limit", 200);
const store = createDjInterviewStore(interviewDir ? { interviewDir } : {});
const result = await writeDjInterviewReviewWorkbench({ store, outDir, limit });

console.log(JSON.stringify({
  ok: true,
  exported: result.packet.summary.exported,
  htmlPath: result.htmlPath,
  safety: result.packet.safety,
}, null, 2));
