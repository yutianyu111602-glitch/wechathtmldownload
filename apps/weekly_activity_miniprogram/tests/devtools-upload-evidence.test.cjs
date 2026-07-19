const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const appRoot = path.resolve(__dirname, "..");
const uploadScript = path.join(appRoot, "scripts/upload_devtools_cli_windows.ps1");
const bindingModule = path.join(appRoot, "scripts/MiniProgramReleaseBinding.psm1");
const scenarioRows = [
  ["current", "devtools-current-package-rendered.cjs"],
  ["loading", "devtools-loading-fallback.cjs"],
  ["haptics", "devtools-haptics.cjs"],
  ["extreme", "devtools-extreme.cjs"],
  ["atlas", "devtools-atlas-neighborhood-rendered.cjs"],
  ["artist", "devtools-artist-max-richness-rendered.cjs"],
  ["city", "devtools-city-guide-rendered.cjs"],
  ["sound", "devtools-sound-rendered.cjs"],
];

function writeFile(target, content = "fixture\n") {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, "utf8");
}

function sha256(target) {
  return crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex");
}

function runPowerShell(args, options = {}) {
  return spawnSync("pwsh.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", ...args], {
    encoding: "utf8",
    timeout: 120_000,
    ...options,
  });
}

function bindingFor(fixture) {
  const helper = path.join(fixture.root, "get-bindings.ps1");
  writeFile(helper, [
    "param([string]$ModulePath,[string]$ProjectDir,[string]$PackageDir)",
    "Import-Module $ModulePath -Force",
    "$project = Get-HuaidjDevToolsProjectBinding -Root $ProjectDir",
    "$package = Get-HuaidjStaticPackageBinding -Root $PackageDir",
    "[pscustomobject]@{ project = $project; package = $package } | ConvertTo-Json -Compress -Depth 8",
  ].join("\n"));
  const result = runPowerShell([
    "-File", helper,
    "-ModulePath", bindingModule,
    "-ProjectDir", fixture.projectDir,
    "-PackageDir", fixture.packageDir,
  ]);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
}

function createFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "huaidj-upload-evidence-"));
  const fixture = {
    root,
    projectDir: path.join(root, "project"),
    packageDir: path.join(root, "current-release"),
    boundPackageDir: path.join(root, "bound-package"),
    profileDir: path.join(root, "profile"),
    stagingRoot: path.join(root, "staging"),
    infoOutput: path.join(root, "reports", "upload-info.json"),
    marker: path.join(root, "fake-upload-called.txt"),
    cli: path.join(root, "fake-devtools-cli.ps1"),
    summaryPath: path.join(root, "suite", "suite-summary.json"),
  };

  writeFile(path.join(fixture.projectDir, "app.js"), "App({});\n");
  writeFile(path.join(fixture.projectDir, "app.json"), "{}\n");
  writeFile(path.join(fixture.projectDir, "app.wxss"), "page {}\n");
  writeFile(path.join(fixture.projectDir, "project.config.json"), JSON.stringify({
    appid: "wx-fixture",
    cloudfunctionRoot: "cloudfunctions/",
  }));
  writeFile(path.join(fixture.projectDir, "sitemap.json"), "{}\n");
  for (const directory of ["assets", "data", "pages", "services"]) {
    writeFile(path.join(fixture.projectDir, directory, "fixture.txt"));
  }
  writeFile(path.join(fixture.projectDir, "config", "buildIdentity.js"), [
    '"use strict";',
    "",
    'module.exports = Object.freeze({ version: "candidate", buildDate: "2026-07-19" });',
    "",
  ].join("\n"));
  writeFile(path.join(fixture.projectDir, "utils", "offlineSnapshot.js"), "module.exports = [];\n");

  writeFile(path.join(fixture.packageDir, "manifest.json"), '{"generation":"fixture"}\n');
  writeFile(path.join(fixture.packageDir, "current.json"), '{"items":[]}\n');
  writeFile(path.join(fixture.packageDir, "cities.json"), '{"cities":[]}\n');
  fs.cpSync(fixture.packageDir, fixture.boundPackageDir, { recursive: true });

  fs.mkdirSync(path.join(fixture.profileDir, "AppData", "Local"), { recursive: true });
  fs.mkdirSync(path.join(fixture.profileDir, "AppData", "Roaming"), { recursive: true });
  writeFile(fixture.cli, [
    "param(",
    "  [Parameter(Position=0)][string]$Action,",
    "  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Remaining",
    ")",
    "$projectIndex = [Array]::IndexOf($Remaining, '--project')",
    "$project = if ($projectIndex -ge 0) { $Remaining[$projectIndex + 1] } else { '' }",
    "if ($Action -eq 'islogin') {",
    "  if ($env:HUAIDJ_FAKE_CLI_MODE -eq 'mutate_on_login') {",
    "    [IO.File]::AppendAllText((Join-Path $project 'app.js'), '// tampered by fake login')",
    "  }",
    "  Write-Output '{\"login\":true}'",
    "  exit 0",
    "}",
    "if ($Action -eq 'upload') {",
    "  $infoIndex = [Array]::IndexOf($Remaining, '--info-output')",
    "  if ($infoIndex -lt 0) { exit 3 }",
    "  $info = $Remaining[$infoIndex + 1]",
    "  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $info) | Out-Null",
    "  [IO.File]::WriteAllText($info, '{\"ok\":true,\"fake\":true}')",
    "  [IO.File]::WriteAllText($env:HUAIDJ_FAKE_UPLOAD_MARKER, $project)",
    "  exit 0",
    "}",
    "exit 4",
  ].join("\n"));

  const binding = bindingFor(fixture);
  const ids = scenarioRows.map(([id]) => id);
  const results = scenarioRows.map(([id, script]) => {
    const packetPath = path.join(fixture.root, "suite", id, "packet.json");
    const consoleLog = path.join(fixture.root, "suite", id, "console.log");
    writeFile(packetPath, `${JSON.stringify({
      schema_version: "weekly_miniprogram_devtools_rendered_single_attempt.v1",
      selected_script: script,
      execute_requested: true,
      executed: true,
      execution: { returncode: 0, timed_out: false },
      boundary: {
        upload_executed: false,
        review_submitted: false,
        cloudrun_deployed: false,
        coordinate_write: false,
        db_graph_vector_write: false,
        provider_or_llm_call: false,
      },
    }, null, 2)}\n`);
    writeFile(consoleLog, "rendered scenario passed\n");
    return {
      id,
      script,
      exitCode: 0,
      decision: "weekly_miniprogram_devtools_rendered_single_attempt_executed",
      packetPath,
      consoleLog,
      packageFingerprint: binding.package.fingerprint,
      devToolsProjectFingerprint: binding.project.fingerprint,
    };
  });
  const summary = {
    schemaVersion: "huaidj_miniprogram_devtools_release_suite.v2",
    generatedAt: new Date().toISOString(),
    projectDir: fixture.projectDir,
    staticPackageSourceDir: fixture.packageDir,
    boundStaticPackageDir: fixture.boundPackageDir,
    devToolsProfileRoot: fixture.profileDir,
    projectFingerprintAlgorithm: binding.project.algorithm,
    packageFingerprintAlgorithm: binding.package.algorithm,
    packageFingerprint: binding.package.fingerprint,
    packageFileCount: binding.package.fileCount,
    packageTotalBytes: binding.package.totalBytes,
    manifestSha256: sha256(path.join(fixture.packageDir, "manifest.json")),
    currentSha256: sha256(path.join(fixture.packageDir, "current.json")),
    devToolsProjectFingerprint: binding.project.fingerprint,
    devToolsProjectFileCount: binding.project.fileCount,
    devToolsProjectTotalBytes: binding.project.totalBytes,
    expectedScenarioIds: ids,
    executedScenarioIds: ids,
    missingScenarioIds: [],
    unexpectedScenarioIds: [],
    duplicateExecutedScenarioIds: [],
    ok: true,
    results,
    error: "",
    safety: {
      uploadExecuted: false,
      reviewSubmitted: false,
      cloudRunDeployed: false,
      databaseWritten: false,
    },
  };
  writeFile(fixture.summaryPath, `${JSON.stringify(summary, null, 2)}\n`);
  fixture.summary = summary;
  return fixture;
}

function uploadArgs(fixture, extra = []) {
  return [
    "-File", uploadScript,
    "-ProjectDir", fixture.projectDir,
    "-DevToolsCli", fixture.cli,
    "-DevToolsProfileRoot", fixture.profileDir,
    "-Version", "2026.07.19.099",
    "-Desc", "local fake upload contract test",
    "-StagingRoot", fixture.stagingRoot,
    "-InfoOutput", fixture.infoOutput,
    "-SuiteSummaryPath", fixture.summaryPath,
    "-StaticPackageDir", fixture.packageDir,
    ...extra,
  ];
}

function fixtureEnvironment(fixture, mode = "") {
  return {
    ...process.env,
    HUAIDJ_FAKE_CLI_MODE: mode,
    HUAIDJ_FAKE_UPLOAD_MARKER: fixture.marker,
  };
}

test("real upload is fail-closed when the DevTools suite summary is missing", () => {
  const fixture = createFixture();
  const args = uploadArgs(fixture, ["-ConfirmUpload"]);
  const summaryIndex = args.indexOf("-SuiteSummaryPath");
  args.splice(summaryIndex, 2);
  const result = runPowerShell(args, { env: fixtureEnvironment(fixture) });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr + result.stdout, /SuiteSummaryPath.*required|forbidden without current eight-scenario/i);
  assert.equal(fs.existsSync(fixture.marker), false);
});

test("upload rejects incomplete or duplicated eight-scenario evidence", () => {
  const fixture = createFixture();
  fixture.summary.results.pop();
  fixture.summary.executedScenarioIds.pop();
  writeFile(fixture.summaryPath, `${JSON.stringify(fixture.summary)}\n`);
  const result = runPowerShell(uploadArgs(fixture, ["-WhatIf"]), { env: fixtureEnvironment(fixture) });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr + result.stdout, /scenario evidence is incomplete|result rows are incomplete/i);
});

test("upload rejects mini-program source drift after the rendered suite", () => {
  const fixture = createFixture();
  fs.appendFileSync(path.join(fixture.projectDir, "app.js"), "// drift\n");
  const result = runPowerShell(uploadArgs(fixture, ["-WhatIf"]), { env: fixtureEnvironment(fixture) });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr + result.stdout, /source drifted/i);
});

test("upload rejects static activity package drift after the rendered suite", () => {
  const fixture = createFixture();
  fs.appendFileSync(path.join(fixture.packageDir, "current.json"), " \n");
  const result = runPowerShell(uploadArgs(fixture, ["-WhatIf"]), { env: fixtureEnvironment(fixture) });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr + result.stdout, /package drifted/i);
});

test("upload detects clean staging tampering during login and never calls upload", () => {
  const fixture = createFixture();
  const result = runPowerShell(uploadArgs(fixture, ["-ConfirmUpload"]), {
    env: fixtureEnvironment(fixture, "mutate_on_login"),
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr + result.stdout, /Final upload staging changed|runtime file/i);
  assert.equal(fs.existsSync(fixture.marker), false);
});

test("WhatIf validates current suite/source/package evidence without upload", () => {
  const fixture = createFixture();
  const result = runPowerShell(uploadArgs(fixture, ["-WhatIf"]), { env: fixtureEnvironment(fixture) });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout, /DevTools CLI upload skipped/);
  assert.equal(fs.existsSync(fixture.marker), false);
});

test("fake CLI upload uses exact clean staging and records final byte fingerprint", () => {
  const fixture = createFixture();
  const result = runPowerShell(uploadArgs(fixture, ["-ConfirmUpload"]), { env: fixtureEnvironment(fixture) });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.equal(fs.existsSync(fixture.marker), true);
  const uploadedProjectDir = fs.readFileSync(fixture.marker, "utf8");
  assert.notEqual(path.resolve(uploadedProjectDir), path.resolve(fixture.projectDir));
  const evidencePath = fixture.infoOutput.replace(/\.json$/i, ".build-identity.json");
  const evidence = JSON.parse(fs.readFileSync(evidencePath, "utf8"));
  assert.equal(evidence.schemaVersion, "huaidj_miniprogram_upload_evidence.v2");
  assert.equal(evidence.suiteSchemaVersion, "huaidj_miniprogram_devtools_release_suite.v2");
  assert.match(evidence.testedSourceFingerprint, /^[a-f0-9]{64}$/);
  assert.match(evidence.testedPackageFingerprint, /^[a-f0-9]{64}$/);
  assert.match(evidence.finalStagingFingerprint, /^[a-f0-9]{64}$/);
  assert.equal(evidence.onlyPermittedSourceDifference, "config/buildIdentity.js");
  assert.deepEqual(evidence.runtimeEntries, [
    "app.js", "app.json", "app.wxss", "project.config.json", "sitemap.json",
    "assets", "config", "data", "pages", "services", "utils",
  ]);
  assert.equal(evidence.safety.reviewSubmitted, false);
  const identity = fs.readFileSync(path.join(uploadedProjectDir, "config/buildIdentity.js"), "utf8");
  assert.match(identity, /"version": "2026\.07\.19\.099"/);
});
