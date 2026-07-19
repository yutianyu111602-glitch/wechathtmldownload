const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

test("DJ interview and column pages remain routable after guide tab promotion", () => {
  const appJson = JSON.parse(read("app.json"));
  const appJs = read("app.js");
  const aboutJs = read("pages/about/about.js");
  const aboutWxml = read("pages/about/about.wxml");
  const artistJs = read("pages/artist/artist.js");
  const artistWxml = read("pages/artist/artist.wxml");
  const interviewJs = read("pages/interview/interview.js");
  const interviewWxml = read("pages/interview/interview.wxml");
  const i18n = read("utils/i18n.js");

  assert.ok(appJson.pages.includes("pages/column/column"));
  assert.ok(appJson.pages.includes("pages/interview/interview"));
  assert.ok(appJson.tabBar.list.some((item) => item.text === "今晚" && item.pagePath === "pages/city/city"));
  assert.equal(appJson.tabBar.list.some((item) => item.pagePath === "pages/column/column"), false);
  assert.match(appJs, /ABOUT_TAB_INDEX = 3/);
  assert.match(aboutJs, /ABOUT_TAB_INDEX = 3/);
  assert.match(aboutJs, /openInterview\(\)/);
  assert.match(aboutJs, /wx\.(switchTab|navigateTo)\(\{\s*url: "\/pages\/interview\/interview"/);
  assert.match(aboutWxml, /class="interview-panel" bindtap="openInterview"/);
  assert.match(artistJs, /openInterview\(\)/);
  assert.match(artistWxml, /class="interview-cta" bindtap="openInterview"/);
  assert.match(artistJs, /setStorageSync\("atlasDjInterviewSeed:v1"/);
  assert.match(artistJs, /wx\.switchTab\(\{\s*url: "\/pages\/interview\/interview"/);
  assert.doesNotMatch(artistJs, /navigateTo\(\{\s*url: `\/pages\/interview\/interview/);
  assert.match(interviewJs, /SEED_STORAGE_KEY = "atlasDjInterviewSeed:v1"/);
  assert.match(interviewJs, /removeStorageSync\(SEED_STORAGE_KEY\)/);
  assert.match(interviewJs, /postApi\("\/api\/v1\/atlas\/dj-interviews"/);
  assert.match(interviewJs, /validateInterviewExternalLinks/);
  assert.match(interviewJs, /copyOriginalExternalLink/);
  assert.doesNotMatch(interviewJs, /uploadFile/);
  assert.doesNotMatch(interviewJs, /downloadFile/);
  assert.doesNotMatch(interviewJs, /webViewUrl/);
  assert.match(i18n, /Mixtape \/ SoundCloud \/ Mixcloud/);
  assert.match(i18n, /随便听听原链/);
  assert.match(interviewWxml, /dev-notice/);
  assert.match(interviewWxml, /功能开发中/);
  assert.match(i18n, /电子音乐专栏/);
  assert.match(read("pages/column/column.js"), /ATLAS_PLAN_PREVIEW_ITEM/);
  assert.doesNotMatch(read("pages/column/column.wxml"), /readTimeLabel/);
});
