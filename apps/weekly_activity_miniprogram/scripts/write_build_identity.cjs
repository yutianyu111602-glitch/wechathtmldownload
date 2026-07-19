#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

function parseArgs(argv) {
  const options = { projectDir: "", version: "", buildDate: "" };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--project-dir") options.projectDir = argv[++index] || "";
    else if (arg === "--version") options.version = argv[++index] || "";
    else if (arg === "--build-date") options.buildDate = argv[++index] || "";
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return options;
}

function writeBuildIdentity(options) {
  const projectDir = path.resolve(String(options.projectDir || ""));
  const version = String(options.version || "").trim();
  const buildDate = String(options.buildDate || "").trim();
  if (!options.projectDir || !fs.existsSync(path.join(projectDir, "app.json"))) {
    throw new Error(`Mini-program app.json not found under project directory: ${projectDir}`);
  }
  if (!/^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$/.test(version)) {
    throw new Error(`Invalid mini-program build version: ${version}`);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(buildDate)) {
    throw new Error(`Invalid build date: ${buildDate}`);
  }

  const configDir = path.resolve(projectDir, "config");
  const target = path.join(configDir, "buildIdentity.js");
  const expectedPrefix = `${projectDir}${path.sep}`.toLowerCase();
  if (!target.toLowerCase().startsWith(expectedPrefix)) {
    throw new Error(`Refusing to write build identity outside project directory: ${target}`);
  }

  const payload = { version, buildDate };
  const moduleSource = [
    '"use strict";',
    "",
    `module.exports = Object.freeze(${JSON.stringify(payload, null, 2)});`,
    "",
  ].join("\n");
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(target, moduleSource, "utf8");
  return { ok: true, buildIdentityPath: target, ...payload };
}

if (require.main === module) {
  try {
    const result = writeBuildIdentity(parseArgs(process.argv.slice(2)));
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    process.stderr.write(`[build-identity] ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}

module.exports = { parseArgs, writeBuildIdentity };
