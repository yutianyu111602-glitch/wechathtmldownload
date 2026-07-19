import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { createServer } from "../src/server.mjs";

let server;
let baseUrl;
let fixtureDir;

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  const address = serverInstance.address();
  return `http://127.0.0.1:${address.port}`;
}

before(async () => {
  fixtureDir = await mkdtemp(path.join(os.tmpdir(), "atlas-starmap-static-"));
  await mkdir(path.join(fixtureDir, "assets"), { recursive: true });
  await writeFile(
    path.join(fixtureDir, "index.html"),
    '<!doctype html><html><body><div id="root"></div><script type="module" src="/atlas-starmap-assets/assets/app.js"></script></body></html>',
    "utf8",
  );
  await writeFile(path.join(fixtureDir, "assets", "app.js"), "console.log('atlas starmap');\n", "utf8");
  await writeFile(path.join(fixtureDir, "assets", "app.css"), "body{margin:0}\n", "utf8");
  await writeFile(
    path.join(fixtureDir, "atlas_layout.json"),
    JSON.stringify({
      nodes: [{ id: 1, x: 0, y: 0, z: 0, name: "NORA", size: 1, color: "#fff" }],
      edges: [],
      total_nodes: 1,
    }),
    "utf8",
  );
  await writeFile(path.join(fixtureDir, "secret.txt"), "nope", "utf8");

  server = createServer({
    store: {},
    stage7Store: {},
    llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
    soundStore: {},
    interviewStore: {},
    env: {
      ...process.env,
      ATLAS_STARMAP_ASSET_DIR: fixtureDir,
      ATLAS_REQUIRE_SESSION: "false",
    },
  });
  baseUrl = await listen(server);
});

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve));
  if (fixtureDir) await rm(fixtureDir, { recursive: true, force: true });
});

test("serves Atlas starmap HTML from dedicated static root", async () => {
  const res = await fetch(`${baseUrl}/atlas/starmap`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type") || "", /text\/html/);
  const body = await res.text();
  assert.match(body, /\/atlas-starmap-assets\/assets\/app\.js/);
});

test("serves only whitelisted Atlas starmap asset types", async () => {
  const js = await fetch(`${baseUrl}/atlas-starmap-assets/assets/app.js`);
  assert.equal(js.status, 200);
  assert.match(js.headers.get("content-type") || "", /javascript/);

  const css = await fetch(`${baseUrl}/atlas-starmap-assets/assets/app.css`);
  assert.equal(css.status, 200);
  assert.match(css.headers.get("content-type") || "", /text\/css/);

  const json = await fetch(`${baseUrl}/atlas-starmap-assets/atlas_layout.json`);
  assert.equal(json.status, 200);
  assert.match(json.headers.get("content-type") || "", /application\/json/);
  const layout = await json.json();
  assert.equal(layout.total_nodes, 1);

  const blockedExt = await fetch(`${baseUrl}/atlas-starmap-assets/secret.txt`);
  assert.equal(blockedExt.status, 403);
});

test("blocks Atlas starmap asset path traversal", async () => {
  const blocked = await fetch(`${baseUrl}/atlas-starmap-assets/${encodeURIComponent("../secret.txt")}`);
  assert.equal(blocked.status, 403);
});
