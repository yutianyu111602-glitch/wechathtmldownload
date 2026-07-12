import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const testDir = path.join(repoRoot, "apps", "weekly_activity_miniprogram", "tests");
const files = readdirSync(testDir)
  .filter((name) => name.endsWith(".test.cjs"))
  .sort()
  .map((name) => path.join(testDir, name));

if (!files.length) throw new Error(`No mini-program tests found in ${testDir}`);

const result = spawnSync(process.execPath, ["--test", "--test-concurrency=1", ...files], {
  cwd: repoRoot,
  stdio: "inherit",
  windowsHide: true,
});

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
