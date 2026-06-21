const { test } = require("node:test");
const assert = require("node:assert");
const { socialToLinkItems, urlForKey } = require("../utils/djLinks");

test("urlForKey builds canonical URLs from handles + normalizes full URLs", () => {
  assert.equal(urlForKey("instagram", "@96back"), "https://instagram.com/96back");
  assert.equal(urlForKey("soundcloud", "96back"), "https://soundcloud.com/96back");
  assert.equal(urlForKey("mixcloud", "96back"), "https://www.mixcloud.com/96back");
  assert.equal(urlForKey("resident_advisor", "ra.co/dj/96back"), "https://ra.co/dj/96back");
  assert.equal(urlForKey("website", "http://example.com"), "https://example.com");
  assert.equal(urlForKey("instagram", ""), "");
  assert.equal(urlForKey("website", "not a url"), ""); // no domain -> dropped
});

test("socialToLinkItems emits display-allowed high-confidence items with categories; ignores wechat/empty", () => {
  const items = socialToLinkItems({
    instagram: "96back",
    soundcloud: "https://soundcloud.com/96back",
    resident_advisor: "ra.co/dj/96back",
    wechat: "should-be-ignored",
    spotify: "",
  }, { entityName: "96 Back" });
  const byPlatform = Object.fromEntries(items.map((i) => [i.platform, i]));
  assert.equal(byPlatform.instagram.public_category, "instagram");
  assert.equal(byPlatform.soundcloud.public_category, "mixtape_music");
  assert.equal(byPlatform.resident_advisor.public_category, "public_profile");
  assert.ok(!("wechat" in byPlatform), "wechat excluded");
  assert.ok(!("spotify" in byPlatform), "empty value dropped");
  items.forEach((i) => {
    assert.equal(i.miniapp_display_allowed_candidate, true);
    assert.equal(i.confidence_band, "high");
    assert.equal(i.entity_name, "96 Back");
  });
});
