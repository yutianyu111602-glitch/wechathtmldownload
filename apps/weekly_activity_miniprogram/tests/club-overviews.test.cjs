const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const {
  clubNameMatches,
  getClubOverviewsForVenue,
  normalizeClubName,
} = require("../utils/clubOverviews");
const clubOverviewData = require("../data/club_overviews");

test("club overview matching handles公众号名和venue名差异", () => {
  assert.equal(normalizeClubName("loopy Club"), "loopy");
  assert.equal(clubNameMatches("loopy Club", "loopy"), true);
  assert.equal(clubNameMatches("NU Lab", "NU Lab"), true);
  assert.equal(clubNameMatches("loopy Club", "Loop"), false);
});

test("club overview display keeps current specific windows before monthly roundups", () => {
  const items = getClubOverviewsForVenue("loopy", {
    lang: "zh",
    data: {
      by_club: {
        "loopy Club": [
          {
            club: "loopy Club",
            title: "loopy 六月活动一览",
            original_url: "https://mp.weixin.qq.com/s/month",
            cover_url: "https://mmbiz.qpic.cn/month/0?wx_fmt=jpeg",
            window_kind: "month",
            window_label: "6月",
            window_start: "2026-06-01",
            window_end: "2026-06-30",
          },
          {
            club: "loopy Club",
            title: "loopy Club 端午假期活动一览",
            original_url: "https://mp.weixin.qq.com/s/holiday",
            cover_url: "https://mmbiz.qpic.cn/holiday/0?wx_fmt=jpeg",
            window_kind: "holiday",
            window_label: "假期",
            window_start: "2026-06-15",
            window_end: "2026-06-22",
          },
        ],
      },
    },
  });
  assert.equal(items.length, 2);
  assert.equal(items[0].windowKind, "holiday");
  assert.equal(items[0].kindLabel, "假期");
  assert.match(items[0].originalUrl, /^https:\/\/mp\.weixin\.qq\.com\//);
  assert.match(items[0].coverUrl, /^https:\/\/mmbiz\.qpic\.cn\//);
  assert.equal(items[1].windowKind, "month");
});

test("club overview source data is parent aggregate only", () => {
  const items = Object.values(clubOverviewData.by_club || {}).flat();
  assert.ok(items.length > 0, "expected current/future club overview items");

  for (const item of items) {
    assert.equal(item.record_type, "club_overview_parent");
    assert.equal(item.parent_aggregate, true);
    assert.equal(item.include_in_activity_feed, false);
    assert.match(item.original_url, /^https:\/\/mp\.weixin\.qq\.com\//);
    assert.match(item.cover_url, /^https:\/\/mmbiz\.qpic\.cn\//);
    assert.doesNotMatch(item.title, /Weekly Listening|Staff Picks/i);
  }
});

test("venue page uses native mini-program overview UI and direct source opening", () => {
  const script = fs.readFileSync(path.join(root, "pages", "venue", "venue.js"), "utf8");
  const wxml = fs.readFileSync(path.join(root, "pages", "venue", "venue.wxml"), "utf8");
  const wxss = fs.readFileSync(path.join(root, "pages", "venue", "venue.wxss"), "utf8");

  assert.match(script, /getClubOverviewsForVenue\(this\.name/);
  assert.match(script, /openClubOverview/);
  assert.match(script, /openSourceUrl\(url/);
  assert.match(script, /onClubOverviewPosterError/);
  assert.match(wxml, /wx:if="\{\{clubOverviews\.length\}\}"/);
  assert.match(wxml, /<image[\s\S]*class="club-overview-poster"/);
  assert.match(wxml, /binderror="onClubOverviewPosterError"/);
  assert.match(wxml, /club-overview-poster-fallback/);
  assert.match(wxml, /bindtap="openClubOverview"/);
  assert.match(wxss, /\.club-overview-card/);
  assert.match(wxss, /\.club-overview-poster-fallback/);
  assert.doesNotMatch(wxml, /show_widget|iframe|html/i);
});

test("clean CI staging carries club overview data dependency", () => {
  const stagingRoot = fs.mkdtempSync(path.join(os.tmpdir(), "weekly-mini-staging-"));
  const script = path.join(root, "scripts", "New-CleanCiStaging.ps1");
  const result = spawnSync("powershell", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    script,
    "-SourceDir",
    root,
    "-StagingRoot",
    stagingRoot,
    "-StagingName",
    "upload-test",
  ], {
    cwd: root,
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr || result.stdout);
  const stage = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  assert.ok(stage.runtimeEntries.includes("data"));
  assert.ok(fs.existsSync(path.join(stage.stagingDir, "utils", "clubOverviews.js")));
  assert.ok(fs.existsSync(path.join(stage.stagingDir, "data", "club_overviews.js")));
  assert.ok(fs.statSync(path.join(stage.stagingDir, "cloudfunctions")).isDirectory());
});
