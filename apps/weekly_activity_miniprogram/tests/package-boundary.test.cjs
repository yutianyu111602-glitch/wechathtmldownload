const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const previewLimitBytes = 2 * 1024 * 1024;

function readProjectConfig() {
  return JSON.parse(fs.readFileSync(path.join(root, "project.config.json"), "utf8"));
}

function normalizePath(value) {
  return String(value || "").replace(/\\/g, "/").replace(/^\/+/, "");
}

function basenameOf(relativePath) {
  const normalized = normalizePath(relativePath);
  const index = normalized.lastIndexOf("/");
  return index >= 0 ? normalized.slice(index + 1) : normalized;
}

function isIgnored(relativePath, ignores) {
  const normalized = normalizePath(relativePath);
  const base = basenameOf(normalized);
  return ignores.some((item) => {
    const value = normalizePath(item.value);
    if (!value) return false;
    if (item.type === "folder") return normalized === value || normalized.startsWith(`${value}/`) || base === value;
    if (item.type === "prefix") return normalized.startsWith(value);
    if (item.type === "suffix") return normalized.endsWith(value);
    if (item.type === "file") return normalized === value || base === value;
    return false;
  });
}

function collectPackageFiles(dir, ignores, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    const relativePath = normalizePath(path.relative(root, fullPath));
    if (isIgnored(relativePath, ignores)) continue;
    if (entry.isDirectory()) {
      collectPackageFiles(fullPath, ignores, files);
    } else {
      const stat = fs.statSync(fullPath);
      files.push({ relativePath, bytes: stat.size });
    }
  }
  return files;
}

test("mini-program preview package excludes local artifacts and secrets", () => {
  const config = readProjectConfig();
  const ignores = config.packOptions?.ignore || [];
  const files = collectPackageFiles(root, ignores);
  const totalBytes = files.reduce((sum, item) => sum + item.bytes, 0);
  const included = new Set(files.map((item) => item.relativePath));

  assert.ok(
    ignores.some((item) => item.type === "prefix" && item.value === "test-artifacts"),
    "test-artifacts must be ignored by prefix because rendered proof output can exceed preview limits",
  );
  assert.ok(
    ignores.some((item) => item.type === "prefix" && item.value === ".env"),
    ".env* files must never enter the mini-program preview package",
  );
  assert.ok(
    ignores.some((item) => item.type === "folder" && item.value === "node_modules"),
    "node_modules must stay out of the mini-program package",
  );
  assert.ok(
    ignores.some((item) => item.type === "file" && item.value === "data/atlas_starmap.json"),
    "atlas_starmap.json is a source copy; runtime uses atlas_starmap.js and must not package both",
  );
  assert.ok(
    ignores.some((item) => item.type === "file" && item.value === "data/atlas_starmap_neighbors.json"),
    "atlas_starmap_neighbors.json is a source copy; runtime uses atlas_starmap_neighbors.js and must not package both",
  );
  assert.ok(
    ignores.some((item) => item.type === "prefix" && item.value === ".vscode"),
    ".vscode must stay out of DevTools preview packages",
  );

  for (const relativePath of included) {
    assert.equal(relativePath.startsWith("test-artifacts/"), false, `${relativePath} should not be packaged`);
    assert.equal(relativePath.startsWith("node_modules/"), false, `${relativePath} should not be packaged`);
    assert.equal(relativePath.startsWith(".vscode/"), false, `${relativePath} should not be packaged`);
    assert.equal(relativePath.startsWith(".env"), false, `${relativePath} should not be packaged`);
    assert.notEqual(relativePath, "data/atlas_starmap.json", `${relativePath} should not be packaged`);
    assert.notEqual(relativePath, "data/atlas_starmap_neighbors.json", `${relativePath} should not be packaged`);
  }
  assert.ok(totalBytes < previewLimitBytes, `estimated preview package ${totalBytes} bytes exceeds 2MB`);
});
