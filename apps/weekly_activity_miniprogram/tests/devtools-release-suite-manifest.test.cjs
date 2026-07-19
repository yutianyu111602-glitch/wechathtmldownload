const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appRoot = path.resolve(__dirname, "..");
const suitePath = path.join(appRoot, "scripts/run_devtools_release_suite_windows.ps1");
const wrapperPath = path.resolve(appRoot, "../../tools/stage7_rewrite/scripts/run_miniprogram_devtools_rendered_single_attempt.py");

const expectedScenarios = [
  ["current", "devtools-current-package-rendered.cjs"],
  ["loading", "devtools-loading-fallback.cjs"],
  ["haptics", "devtools-haptics.cjs"],
  ["extreme", "devtools-extreme.cjs"],
  ["atlas", "devtools-atlas-neighborhood-rendered.cjs"],
  ["artist", "devtools-artist-max-richness-rendered.cjs"],
  ["city", "devtools-city-guide-rendered.cjs"],
  ["sound", "devtools-sound-rendered.cjs"],
];

test("rendered release suite declares and executes every release-critical surface", () => {
  const source = fs.readFileSync(suitePath, "utf8");
  const wrapperSource = fs.readFileSync(wrapperPath, "utf8");
  for (const [id, script] of expectedScenarios) {
    assert.match(source, new RegExp(`id\\s*=\\s*["']${id}["']`), `missing scenario id: ${id}`);
    assert.match(source, new RegExp(`script\\s*=\\s*["']${script.replaceAll(".", "\\.")}["']`));
    assert.equal(fs.existsSync(path.join(appRoot, "tests", script)), true, `missing rendered test: ${script}`);
    assert.match(wrapperSource, new RegExp(`["]${script.replaceAll(".", "\\.")}["]`), `wrapper disallows: ${script}`);
  }
  assert.match(source, /expectedScenarioIds/);
  assert.match(source, /executedScenarioIds/);
  assert.match(source, /missingScenarioIds/);
  assert.match(source, /unexpectedScenarioIds/);
  assert.match(source, /missingScenarioIds\.Count\s*-eq\s*0/);
  assert.match(source, /unexpectedScenarioIds\.Count\s*-eq\s*0/);
  assert.match(source, /boundStaticPackageDir/);
  assert.match(source, /packageFingerprint/);
  assert.match(source, /Get-StaticPackageBinding/);
  assert.match(source, /Copy-StaticPackageSnapshot/);
  assert.match(source, /sourceBindingBefore\.fingerprint\s*-ne\s*\$sourceBindingAfter\.fingerprint/);
  assert.match(source, /Get-DevToolsProjectBinding/);
  assert.match(source, /devToolsProjectFingerprint/);
  assert.match(source, /MiniProgramReleaseBinding\.psm1/);
  assert.match(source, /projectFingerprintAlgorithm/);
  assert.match(source, /packageFingerprintAlgorithm/);
  assert.match(source, /huaidj_miniprogram_devtools_release_suite\.v2/);
  assert.match(source, /Assert-HuaidjBindingUnchanged/);
  assert.match(source, /duplicateExecutedScenarioIds/);
  assert.match(source, /WeChat DevTools profile is not logged in/);
  assert.match(source, /function Invoke-NativeCapture/);
  assert.match(source, /NativeCommandError/);
  assert.match(source, /loginResult\.exitCode/);
  assert.match(source, /wrapperResult\.exitCode/);
});

test("raw protocol release scenarios can launch DevTools when the wrapper clears the websocket endpoint", () => {
  for (const script of [
    "devtools-atlas-neighborhood-rendered.cjs",
    "devtools-artist-max-richness-rendered.cjs",
    "devtools-city-guide-rendered.cjs",
    "devtools-sound-rendered.cjs",
  ]) {
    const source = fs
      .readFileSync(path.join(appRoot, "tests", script), "utf8")
      .replace(/\r\n/g, "\n");
    assert.match(source, /devtools-raw-session\.cjs/);
    assert.match(source, /connectRawDevtools/);
    assert.doesNotMatch(source, /MINIPROGRAM_AUTOMATOR_WS\s*\|\|\s*["']ws:/);
    assert.doesNotMatch(source, /MINIPROGRAM_AUTOMATOR_WS (?:is )?required/);
  }
});

test("home rendered scenarios tolerate DevTools restoring the already-selected home tab", () => {
  for (const script of [
    "devtools-current-package-rendered.cjs",
    "devtools-loading-fallback.cjs",
  ]) {
    const source = fs
      .readFileSync(path.join(appRoot, "tests", script), "utf8")
      .replace(/\r\n/g, "\n");
    const openHomeStart = source.indexOf("async function openHome");
    const openHomeEnd = source.indexOf("\n}\n", openHomeStart);
    const openHome = source.slice(openHomeStart, openHomeEnd + 3);
    assert.match(openHome, /miniProgram\.currentPage\(\)/);
    assert.match(openHome, /page\.path === ["']pages\/index\/index["']/);
    assert.match(openHome, /miniProgram\.reLaunch/);
    assert.doesNotMatch(openHome, /wx\.switchTab/);
  }
  const loadingSource = fs.readFileSync(
    path.join(appRoot, "tests", "devtools-loading-fallback.cjs"),
    "utf8",
  );
  assert.match(loadingSource, /run\(\)\.then\(\(\) => \{\s*process\.exit\(0\)/);
});

test("Atlas rendered scenarios consume the external hydrated SSOT instead of writing data into Git", () => {
  for (const script of [
    "devtools-atlas-neighborhood-rendered.cjs",
    "devtools-artist-max-richness-rendered.cjs",
  ]) {
    const source = fs.readFileSync(path.join(appRoot, "tests", script), "utf8");
    assert.match(source, /HUAIDJ_ATLAS_MINIAPP_DATA_DIR/);
    assert.match(source, /path\.join\(atlasDataDir,/);
    assert.doesNotMatch(
      source,
      /path\.resolve\(__dirname,\s*["'][.]{3}\/services\/weekly_activity_cloudrun\/data\/atlas_/,
    );
  }
});

test("Atlas neighborhood scenario waits for a callable App runtime after DevTools launch", () => {
  const source = fs.readFileSync(
    path.join(appRoot, "tests", "devtools-atlas-neighborhood-rendered.cjs"),
    "utf8",
  );
  assert.match(source, /async function waitForAppRuntime/);
  assert.match(source, /wait App runtime callable/);
  assert.match(source, /probeAppRuntime/);
  assert.match(source, /App runtime did not become callable/);
});

test("automator adapter preserves the raw request-response protocol used by rendered scenarios", async () => {
  const { AutomatorProtocolAdapter } = require("./devtools-raw-session.cjs");
  let disconnected = false;
  const adapter = new AutomatorProtocolAdapter({
    connection: {
      async send(method, params) {
        return { method, params };
      },
    },
    disconnect() { disconnected = true; },
  });
  const response = new Promise((resolve) => adapter.once("message", (raw) => resolve(JSON.parse(String(raw)))));
  adapter.send(JSON.stringify({ id: "request-1", method: "Tool.getInfo", params: { probe: true } }));

  assert.deepEqual(await response, {
    id: "request-1",
    result: { method: "Tool.getInfo", params: { probe: true } },
  });
  const closed = new Promise((resolve) => adapter.once("close", resolve));
  adapter.close();
  await closed;
  assert.equal(disconnected, true);
});
