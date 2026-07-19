const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const indexWxss = fs.readFileSync(path.resolve(__dirname, "../pages/index/index.wxss"), "utf8");

function block(selector) {
  const match = indexWxss.match(new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([\\s\\S]*?)\\}`));
  assert.ok(match, `${selector} block should exist`);
  return match[1];
}

test("poster strip has bounded height so long card text cannot push the feed down", () => {
  const strip = block(".poster-strip");
  const card = block(".poster-card");
  const title = block(".poster-title");
  const meta = block(".poster-meta");
  const allHeading = block(".all-heading");

  assert.match(strip, /height:\s*602rpx/);
  assert.match(card, /height:\s*590rpx/);
  assert.match(card, /overflow:\s*hidden/);
  assert.match(card, /box-sizing:\s*border-box/);
  assert.match(title, /max-height:\s*64rpx/);
  assert.match(title, /overflow:\s*hidden/);
  assert.match(meta, /max-height:\s*34rpx/);
  assert.match(meta, /overflow:\s*hidden/);
  assert.match(allHeading, /margin-top:\s*28rpx/);
});
