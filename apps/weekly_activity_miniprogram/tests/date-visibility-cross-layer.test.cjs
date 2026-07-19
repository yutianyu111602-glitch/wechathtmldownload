const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(appRoot, "../..");
const modulePaths = [
  path.join(appRoot, "utils/dateVisibility.js"),
  path.join(appRoot, "cloudfunctions/weeklyDataSync/dateVisibility.js"),
  path.join(repoRoot, "services/weekly_activity_cloudrun/src/dateVisibility.cjs"),
];
const contracts = modulePaths.map((modulePath) => require(modulePath));

test("packaging-boundary copies of the date visibility SSOT stay byte-identical", () => {
  const sources = modulePaths.map((modulePath) => fs.readFileSync(modulePath, "utf8"));
  assert.equal(new Set(sources).size, 1);
});

test("all date visibility runtimes share explicit, sparse, range and undated semantics", () => {
  for (const contract of contracts) {
    const explicit = {
      event_date_start: "2026-07-24",
      event_date_end: "2026-07-26",
      event_date_iso_guess: "2026-07-24",
      event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
    };
    const sparse = {
      event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
    };
    const explicitStartWithGuessNoise = {
      event_date_start: "2026-07-24",
      event_date_iso_guess: "2026-07-31",
      event_date_iso_guesses: ["2026-07-25", "2026-07-30"],
    };
    const calendarPreview = {
      event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
      quality_flags: ["calendar_preview"],
    };

    assert.deepEqual(contract.itemDateKeys(explicit), ["2026-07-24", "2026-07-25", "2026-07-26"]);
    assert.equal(contract.itemMatchesDateKey(explicit, "2026-07-31"), false);
    assert.deepEqual(contract.itemDateKeys(sparse), ["2026-07-24", "2026-07-31"]);
    assert.equal(contract.itemMatchesDateKey(sparse, "2026-07-27"), false);
    assert.equal(contract.itemMatchesDateWindow(sparse, "2026-07-27", "2026-07-27"), false);
    assert.deepEqual(contract.itemDateKeys(explicitStartWithGuessNoise), ["2026-07-24"]);
    assert.equal(contract.itemMatchesDateKey(explicitStartWithGuessNoise, "2026-07-31"), false);
    assert.equal(contract.itemMatchesDateKey(calendarPreview, "2026-07-27"), true);
    assert.equal(contract.itemIsCurrentOrFuture({}, "2026-07-19"), false);
  }
});
