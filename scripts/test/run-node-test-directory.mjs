import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const [relativeDir, suffix] = process.argv.slice(2);

if (!relativeDir || !suffix) {
  throw new Error("Usage: run-node-test-directory.mjs <relative-dir> <test-suffix>");
}

const testDir = path.resolve(repoRoot, relativeDir);
const files = readdirSync(testDir)
  .filter((name) => name.endsWith(suffix))
  .sort()
  .map((name) => path.join(testDir, name));

if (!files.length) throw new Error(`No ${suffix} tests found in ${testDir}`);

const result = spawnSync(process.execPath, ["--test", "--test-concurrency=1", ...files], {
  cwd: repoRoot,
  stdio: "inherit",
  windowsHide: true,
});

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
