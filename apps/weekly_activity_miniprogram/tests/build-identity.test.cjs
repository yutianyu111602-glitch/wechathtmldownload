const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const appRoot = path.resolve(__dirname, "..");

test("about page reads the single mini-program build identity module", () => {
  const identityPath = path.join(appRoot, "config/buildIdentity.js");
  delete require.cache[require.resolve(identityPath)];
  const identity = require(identityPath);
  const aboutJs = fs.readFileSync(path.join(appRoot, "pages/about/about.js"), "utf8");

  assert.equal(identity.version, "2026.07.19.001");
  assert.equal(identity.buildDate, "2026-07-19");
  assert.match(aboutJs, /require\("\.\.\/\.\.\/config\/buildIdentity"\)/);
  assert.doesNotMatch(aboutJs, /const VERSION\s*=/);
  assert.doesNotMatch(aboutJs, /const BUILD_DATE\s*=/);
  assert.match(aboutJs, /version:\s*BUILD_IDENTITY\.version/);
  assert.match(aboutJs, /buildDate:\s*BUILD_IDENTITY\.buildDate/);
});

test("release helper writes the exact final upload identity into an isolated project", () => {
  const projectDir = fs.mkdtempSync(path.join(os.tmpdir(), "mini-build-identity-"));
  fs.writeFileSync(path.join(projectDir, "app.json"), "{}\n", "utf8");
  const writer = path.join(appRoot, "scripts/write_build_identity.cjs");
  const result = spawnSync(process.execPath, [
    writer,
    "--project-dir", projectDir,
    "--version", "2026.07.19.009",
    "--build-date", "2026-07-19",
  ], { encoding: "utf8" });

  assert.equal(result.status, 0, result.stderr || result.stdout);
  const generatedPath = path.join(projectDir, "config/buildIdentity.js");
  delete require.cache[require.resolve(generatedPath)];
  const generated = require(generatedPath);
  assert.deepEqual(generated, {
    version: "2026.07.19.009",
    buildDate: "2026-07-19",
  });
});

test("clean staging and DevTools upload bind the runtime identity to the upload version", () => {
  const stagingScript = fs.readFileSync(path.join(appRoot, "scripts/New-CleanCiStaging.ps1"), "utf8");
  const uploadScript = fs.readFileSync(path.join(appRoot, "scripts/upload_devtools_cli_windows.ps1"), "utf8");
  const bindingModule = fs.readFileSync(path.join(appRoot, "scripts/MiniProgramReleaseBinding.psm1"), "utf8");

  assert.match(bindingModule, /\$script:HuaidjRuntimeEntries\s*=\s*@\([\s\S]*"config"/);
  assert.match(stagingScript, /Get-HuaidjMiniProgramRuntimeEntries/);
  assert.match(stagingScript, /Assert-HuaidjRuntimeStagingMatchesSource/);
  assert.match(uploadScript, /write_build_identity\.cjs/);
  assert.match(uploadScript, /--project-dir",\s*\$UploadProjectDir/);
  assert.match(uploadScript, /--version",\s*\$Version/);
  assert.match(uploadScript, /BuildIdentitySha256/);
  assert.match(uploadScript, /build-identity\.json/);
  assert.match(uploadScript, /SuiteSummaryPath/);
  assert.match(uploadScript, /StaticPackageDir/);
  assert.match(uploadScript, /Assert-HuaidjDevToolsSuiteEvidence/);
  assert.match(uploadScript, /Assert-UploadReleaseBindingsCurrent/);
  assert.match(uploadScript, /finalStagingFingerprint/);
  assert.match(bindingModule, /only permitted buildIdentity|ExpectedBuildVersion/i);
  assert.match(uploadScript, /-Version is required/);
  assert.match(uploadScript, /\^\\d\{4\}\\\.\\d\{2\}\\\.\\d\{2\}\\\.\\d\{3\}\$/);
  assert.match(uploadScript, /finally\s*\{[\s\S]*\$env:USERPROFILE\s*=\s*\$priorUserProfile/);
});
