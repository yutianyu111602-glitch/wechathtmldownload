const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const externalLinkAction = require(path.join(root, "utils", "externalLinkAction.js"));

test("external link action copies original platform pages without media handling", () => {
  const action = externalLinkAction.buildExternalLinkAction("https://soundcloud.com/local-dj/live-mixtape", "zh", {
    linkType: "mixtape",
  });

  assert.equal(action.ok, true);
  assert.equal(action.mode, "copy_original_link");
  assert.equal(action.platform, "soundcloud");
  assert.equal(action.linkType, "mixtape");
  assert.equal(action.mediaCached, false);
  assert.equal(action.mediaDownloaded, false);
  assert.equal(action.mediaProxied, false);
});

test("external link action rejects direct media files", () => {
  const action = externalLinkAction.buildExternalLinkAction("https://cdn.example.com/mixes/raw-set.mp3", "zh", {
    linkType: "mixtape",
  });

  assert.equal(action.ok, false);
  assert.equal(action.reason, "direct_media_url");
  assert.match(action.message, /平台页面原链接/);
});

test("interview external link validation blocks media links before submit", () => {
  const action = externalLinkAction.validateInterviewExternalLinks(
    {
      instagramUrl: "https://www.instagram.com/local-dj/",
      mixtapeUrl: "https://media.example.com/download/live-set.flac",
      sourceUrl: "https://mp.weixin.qq.com/s/source",
    },
    "zh",
  );

  assert.equal(action.ok, false);
  assert.equal(action.reason, "direct_media_url");
});

test("copy action uses clipboard instead of downloading or proxying audio", () => {
  const calls = [];
  global.wx = {
    setClipboardData(options) {
      calls.push(["setClipboardData", options.data]);
      if (options.success) options.success();
    },
    showToast(options) {
      calls.push(["showToast", options.title]);
    },
  };

  try {
    const action = externalLinkAction.copyOriginalExternalLink("https://www.mixcloud.com/local-dj/session/", "en", {
      linkType: "mixtape",
    });

    assert.equal(action.ok, true);
    assert.equal(action.platform, "mixcloud");
    assert.equal(action.mediaCached, false);
    assert.deepEqual(calls, [
      ["setClipboardData", "https://www.mixcloud.com/local-dj/session/"],
      ["showToast", "Source link copied"],
    ]);
  } finally {
    delete global.wx;
  }
});
