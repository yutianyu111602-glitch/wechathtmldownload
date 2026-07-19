import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  classifyElectronicMusicRelevance as classifyCloudRun,
  electronicRelevanceContractFingerprint as cloudRunFingerprint,
  isElectronicMusicRelevantItem as keepCloudRun,
  nonElectronicExclusionReason as cloudRunReason,
} from "../src/electronicRelevance.mjs";

const require = createRequire(import.meta.url);
const miniRelevance = require("../../../apps/weekly_activity_miniprogram/utils/electronicRelevance.js");
const miniGenreFilter = require("../../../apps/weekly_activity_miniprogram/utils/genreFilter.js");
const corpusPath = fileURLToPath(new URL("../../../tests/fixtures/weekly-electronic-relevance.v1.json", import.meta.url));
const corpus = JSON.parse(await readFile(corpusPath, "utf8"));

test("CloudRun and mini-program expose the same electronic relevance contract", () => {
  assert.equal(
    cloudRunFingerprint(),
    miniRelevance.electronicRelevanceContractFingerprint(),
  );
});

for (const fixture of corpus.cases) {
  test(`electronic relevance corpus: ${fixture.id}`, () => {
    const { item, expected } = fixture;
    assert.equal(classifyCloudRun(item), expected.classification);
    assert.equal(miniRelevance.classifyElectronicMusicRelevance(item), expected.classification);
    assert.equal(miniGenreFilter.itemGenreOf(item), expected.classification);
    assert.equal(keepCloudRun(item), expected.keep);
    assert.equal(miniRelevance.isElectronicMusicRelevantItem(item), expected.keep);
    assert.equal(miniGenreFilter.filterItemsByElectronic([item]).length === 1, expected.keep);
    assert.equal(cloudRunReason(item), expected.reason);
    assert.equal(miniRelevance.nonElectronicExclusionReason(item), expected.reason);
  });
}
