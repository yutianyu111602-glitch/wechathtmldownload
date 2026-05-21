const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { areLikelyDuplicateItems } = require("../utils/format");

const specPath = path.resolve(
  __dirname,
  "../../../tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json",
);
const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));

function test(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    console.error(`not ok - ${name}`);
    throw error;
  }
}

test("weekly_dedup_spec.v1 parity with L2 expectations", () => {
  assert.equal(spec.schema_version, "weekly_dedup_spec.v1");
  let frontendExtraMerge = 0;

  for (const item of spec.cases) {
    const actual = areLikelyDuplicateItems(item.left, item.right);
    if (actual && !item.expected_duplicate) frontendExtraMerge += 1;
    assert.equal(actual, item.expected_duplicate, `${item.id}: ${item.reason}`);
  }

  assert.equal(frontendExtraMerge, 0, "frontend_extra_merge must stay 0");
});

