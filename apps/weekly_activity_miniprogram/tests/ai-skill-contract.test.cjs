const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(appRoot, "../..");
const skillRoot = path.join(appRoot, "ai_packages/weekly/weekly-events-skill");

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function compactMcpLength(file) {
  const json = readJson(file);
  const clone = JSON.parse(JSON.stringify(json));
  for (const api of clone.apis || []) delete api.outputSchema;
  return JSON.stringify(clone).length;
}

test("WeChat AI developer-mode files stay within official size limits", () => {
  const agents = fs.statSync(path.join(appRoot, "ai_agent/AGENTS.md")).size;
  const pageMeta = fs.statSync(path.join(appRoot, "ai_agent/page-meta.json")).size;
  const skillMd = fs.statSync(path.join(skillRoot, "SKILL.md")).size;
  const mcpCompact = compactMcpLength(path.join(skillRoot, "mcp.json"));

  assert.ok(agents < 10000, `AGENTS.md exceeds official 10000 byte limit: ${agents}`);
  assert.ok(pageMeta < 8000, `page-meta.json exceeds official 8000 byte limit: ${pageMeta}`);
  assert.ok(skillMd < 16000, `SKILL.md exceeds official 16000 byte limit: ${skillMd}`);
  assert.ok(mcpCompact < 24000, `mcp.json compact length exceeds official 24000 byte limit: ${mcpCompact}`);
});

test("official app.json keeps WeChat AI developer mode disabled for upload", () => {
  const appJson = readJson(path.join(appRoot, "app.json"));
  assert.equal(appJson.lazyCodeLoading, "requiredComponents");
  assert.equal(Object.prototype.hasOwnProperty.call(appJson, "agent"), false);
  assert.ok(!((appJson.subPackages || []).some((pkg) => String(pkg.root || "").startsWith("ai_packages"))));
});

test("app.ai-mode.json keeps the optional read-only weekly_events skill isolated", () => {
  const appAiModeJson = readJson(path.join(appRoot, "app.ai-mode.json"));
  assert.deepEqual(appAiModeJson.agent, {
    instruction: "ai_agent/AGENTS.md",
    pageMetadata: "ai_agent/page-meta.json",
    skills: [
      {
        name: "weekly_events",
        description: "查询国内电子音乐俱乐部近期活动，可按城市、日期、DJ、俱乐部、场地和风格筛选。不处理购票、支付、订座或个人信息提交。",
        path: "ai_packages/weekly/weekly-events-skill",
      },
    ],
  });
  assert.ok((appAiModeJson.subPackages || []).some((pkg) => (
    pkg.root === "ai_packages/weekly" &&
    pkg.independent === true &&
    Array.isArray(pkg.pages)
  )));
});

test("mcp.json declares only the read-only searchEvents API", () => {
  const mcp = readJson(path.join(skillRoot, "mcp.json"));
  assert.equal(mcp.apis.length, 1);
  assert.equal(mcp.apis[0].name, "searchEvents");
  assert.equal(mcp.apis[0].inputSchema.type, "object");
  assert.equal(mcp.apis[0].outputSchema.type, "object");
  assert.match(mcp.apis[0].description, /不处理购票/);
});

test("searchEvents public API defaults to the same current-only scope as the home feed", () => {
  const source = fs.readFileSync(path.join(skillRoot, "apis/searchEvents.js"), "utf8");
  assert.match(source, /"scope=current"/);
  assert.match(source, /"lookbackDays=0"/);
  assert.doesNotMatch(source, /lookbackDays=45/);
});

test("searchEvents returns current release activities without source URLs", async () => {
  const searchEvents = require("../ai_packages/weekly/weekly-events-skill/apis/searchEvents");
  const current = readJson(path.join(repoRoot, "services/weekly_activity_cloudrun/data/current_release/current.json"));
  const manifest = readJson(path.join(repoRoot, "services/weekly_activity_cloudrun/data/current_release/manifest.json"));
  const result = await searchEvents({
    city: "上海",
    timeHint: "next_15_days",
    limit: 20,
  }, {
    items: current.items,
    now: new Date(`${manifest.window_start}T20:00:00+08:00`),
  });

  assert.equal(result.isError, false);
  assert.ok(result.structuredContent.total >= 1, `expected at least one Shanghai event, got ${result.structuredContent.total}`);
  assert.ok(result.structuredContent.events.some((event) => /上海|Shanghai|REACTOR|ILLUM|Cedar|wigwam/i.test(`${event.city} ${event.venue} ${event.title}`)));
  assert.ok(result.content[0].text.includes("已找到"));
  for (const event of result.structuredContent.events) {
    assert.equal(event.city, "上海");
    assert.match(event.detailPath, /^\/pages\/detail\/detail\?id=/);
    assert.equal(Object.prototype.hasOwnProperty.call(event, "sourceUrl"), false);
  }
});

test("searchEvents handles no-result queries without fabricating events", async () => {
  const searchEvents = require("../ai_packages/weekly/weekly-events-skill/apis/searchEvents");
  const current = readJson(path.join(repoRoot, "services/weekly_activity_cloudrun/data/current_release/current.json"));
  const result = await searchEvents({
    city: "上海",
    dateFrom: "2026-06-13",
    dateTo: "2026-06-13",
    keyword: "definitely-not-a-real-dj-name",
  }, {
    items: current.items,
    now: new Date("2026-06-13T20:00:00+08:00"),
  });

  assert.equal(result.isError, false);
  assert.equal(result.structuredContent.total, 0);
  assert.deepEqual(result.structuredContent.events, []);
  assert.match(result.content[0].text, /没有匹配到可确认活动/);
});
