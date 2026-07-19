const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repoRoot = path.resolve(__dirname, "../../..");
const writers = [
  "tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_miniprogram_api.py",
  "tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py",
  "tools/stage7_rewrite/scripts/repair_weekly_api_package_for_source_policy.py",
  "tools/stage7_rewrite/scripts/apply_weekly_manual_place_overrides.py",
  "tools/stage7_rewrite/scripts/apply_weekly_confirmed_venue_locks.py",
];

test("every package index writer labels static facets as package scope", () => {
  for (const relativePath of writers) {
    const source = fs.readFileSync(path.join(repoRoot, relativePath), "utf8");
    assert.match(source, /"scope": "package"/, `${relativePath} must label generated static indexes`);
    assert.match(source, /"item_count":/, `${relativePath} must publish the package item count`);
  }
});

test("release validation rejects an unlabeled or count-mismatched static index", () => {
  const source = fs.readFileSync(
    path.join(repoRoot, "tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py"),
    "utf8",
  );
  assert.match(source, /scope_must_be_package/);
  assert.match(source, /item_count_must_match_current_package/);
});
