const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { startStaticPackageServer } = require("./devtools-static-package.cjs");

test("static package server close is bounded even with a keep-alive client", async (t) => {
  const packageDir = fs.mkdtempSync(path.join(os.tmpdir(), "huaidj-devtools-static-"));
  t.after(() => fs.rmSync(packageDir, { recursive: true, force: true }));
  fs.writeFileSync(path.join(packageDir, "current.json"), "{}\n", "utf8");

  const server = await startStaticPackageServer(packageDir);
  const agent = new http.Agent({ keepAlive: true });
  t.after(() => agent.destroy());
  await new Promise((resolve, reject) => {
    http.get(`${server.baseUrl}/current.json`, { agent }, (response) => {
      response.resume();
      response.once("end", resolve);
    }).once("error", reject);
  });

  const startedAt = Date.now();
  await Promise.race([
    server.close(),
    new Promise((_, reject) => setTimeout(() => reject(new Error("server close hung")), 750)),
  ]);
  assert.ok(Date.now() - startedAt < 750);
});
