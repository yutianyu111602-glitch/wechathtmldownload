const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const renderedProbePath = path.join(__dirname, "devtools-atlas-neighborhood-rendered.cjs");

test("Atlas rendered probe restores the DevTools API runtime before closing its local server", () => {
  const source = fs.readFileSync(renderedProbePath, "utf8");
  const snapshotIndex = source.indexOf("snapshotDevtoolsBackend");
  const restoreIndex = source.indexOf("restoreDevtoolsBackend");
  const cleanupCallIndex = source.lastIndexOf("await restoreDevtoolsBackend()");
  const closeSocketIndex = source.lastIndexOf("await closeSocket(ws)");
  const closeServerIndex = source.lastIndexOf("server.close(resolve)");

  assert.ok(snapshotIndex >= 0, "probe must capture the pre-test DevTools API runtime");
  assert.ok(restoreIndex >= 0, "probe must define a DevTools API runtime restore step");
  assert.ok(cleanupCallIndex >= 0, "probe must invoke the restore step during cleanup");
  assert.ok(cleanupCallIndex < closeSocketIndex, "runtime restore must happen before the automator socket closes");
  assert.ok(cleanupCallIndex < closeServerIndex, "runtime restore must happen before the local API server closes");
});
