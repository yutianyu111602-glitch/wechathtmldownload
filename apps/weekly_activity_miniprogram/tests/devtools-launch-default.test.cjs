const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const scripts = [
  "tests/devtools-column-longform-rendered.cjs",
  "tests/devtools-extreme.cjs",
  "tests/devtools-haptics.cjs",
  "tests/devtools-loading-fallback.cjs",
];

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

test("rendered DevTools scripts default to launch mode instead of fixed websocket connect", () => {
  const failures = [];

  for (const scriptPath of scripts) {
    const source = read(scriptPath);
    if (source.includes("const DEFAULT_WS")) {
      failures.push(`${scriptPath}: must not define DEFAULT_WS`);
    }
    if (/MINIPROGRAM_AUTOMATOR_WS\s*\|\|\s*DEFAULT_WS/.test(source)) {
      failures.push(`${scriptPath}: must not fall back from MINIPROGRAM_AUTOMATOR_WS to a fixed endpoint`);
    }
    if (!source.includes("const launchMode") || !source.includes("!explicitConnectMode")) {
      failures.push(`${scriptPath}: must default to launch mode when no explicit WS endpoint is provided`);
    }
    if (source.includes("MINIPROGRAM_AUTOMATOR_WS=ws://127.0.0.1:9430")) {
      failures.push(`${scriptPath}: hint must not recommend fixed 9430 websocket connect`);
    }
  }

  assert.deepEqual(failures, []);
});
