const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const patchScriptPath = path.join(__dirname, "../scripts/patch_miniprogram_automator_devtools_cli.cjs");

test("automator patch resolves a hoisted miniprogram-automator installation", () => {
  const source = fs.readFileSync(patchScriptPath, "utf8");
  assert.match(source, /require\.resolve\(["']miniprogram-automator\/package\.json["']/);
  assert.doesNotMatch(source, /path\.join\(root,\s*["']node_modules["'],\s*["']miniprogram-automator["']/);
  assert.match(source, /launcher:minified-dynamic-free-port/);
  assert.match(source, /launcher:minified-windows-bat-shell/);
  assert.match(source, /launcherReady/);
});
