const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

test("about page exposes full Atlas starmap as a direct huaidj.club entry", () => {
  const aboutJs = read("pages/about/about.js");
  const aboutWxml = read("pages/about/about.wxml");
  const aboutWxss = read("pages/about/about.wxss");
  const i18n = read("utils/i18n.js");

  assert.match(aboutJs, /const ATLAS_BETA_URL = "https:\/\/huaidj\.club\/atlas\/starmap"/);
  assert.match(aboutJs, /openAtlasBeta\(\)/);
  assert.match(aboutJs, /\/pages\/source\/source\?url=/);
  assert.doesNotMatch(aboutJs, /navigateToMiniProgram/);
  assert.match(aboutWxml, /class="atlas-panel" bindtap="openAtlasBeta"/);
  assert.match(aboutWxml, /atlas-disclaimer/);
  assert.match(aboutWxml, /atlas-link-row/);
  assert.match(aboutWxss, /atlas-panel/);
  assert.match(i18n, /完整星图/);
  assert.match(i18n, /Beta 版仅用于早期体验和信息核对/);
  assert.match(i18n, /huaidj\.club\/atlas\/starmap/);
});

test("source page uses a controlled external fallback for huaidj.club", () => {
  const sourceJs = read("pages/source/source.js");
  const sourceWxml = read("pages/source/source.wxml");

  assert.match(sourceJs, /DIRECT_WEB_HOSTS = new Set\(\["huaidj\.club", "www\.huaidj\.club"\]\)/);
  assert.match(sourceJs, /allowedDirectWebUrl\(query\.url \|\| ""\)/);
  assert.match(sourceJs, /const sourceLinkType = String\(query\.linkType \|\| "external"\)\.trim\(\) \|\| "external"/);
  assert.match(sourceJs, /safeOriginalExternalUrl\(query\.externalUrl \|\| "", lang, sourceLinkType\)/);
  assert.match(sourceJs, /sourceUrl:\s*originalExternalUrl \|\| directUrl/);
  assert.match(sourceJs, /externalUrl:\s*originalExternalUrl \|\| directUrl/);
  assert.match(sourceJs, /sourceLinkType,/);
  assert.match(sourceJs, /webViewUrl:\s*""/);
  assert.match(sourceJs, /if \(directUrl \|\| originalExternalUrl\)/);
  assert.match(sourceJs, /copyExternalUrl\(\)/);
  assert.match(sourceJs, /this\.data\.t\.linkCopied/);
  assert.doesNotMatch(sourceJs, /new URL\(/);
  // 公众号原文不再用 web-view 打开（mp.weixin.qq.com 非本主体域名，web-view 必然白屏）；失败改复制链接
  assert.doesNotMatch(sourceWxml, /<web-view/);
  assert.match(sourceWxml, /externalUrl \? t\.copyLink : t\.open/);
  assert.match(sourceWxml, /t\.externalHint/);
});
