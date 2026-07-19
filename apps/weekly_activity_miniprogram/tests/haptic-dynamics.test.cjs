const assert = require("node:assert/strict");
const test = require("node:test");

global.wx = {
  vibrateShort() {},
};

const {
  HAPTIC,
  createScrollHapticState,
  intervalForSpeed,
  nextScrollHaptic,
  vibrateLight,
} = require("../utils/haptics");

test("scroll haptics speed up but stay restrained", () => {
  assert.equal(intervalForSpeed(0, HAPTIC.feed.minInterval, HAPTIC.feed.maxInterval), 280);
  assert.equal(intervalForSpeed(2.4, HAPTIC.feed.minInterval, HAPTIC.feed.maxInterval), 145);

  const slow = createScrollHapticState(0, 0);
  assert.equal(nextScrollHaptic(slow, 80, 120, HAPTIC.feed).shouldPulse, false);
  assert.equal(nextScrollHaptic(slow, 150, 300, HAPTIC.feed).shouldPulse, true);

  const fast = createScrollHapticState(0, 0);
  assert.equal(nextScrollHaptic(fast, 72, 150, HAPTIC.feed).shouldPulse, true);
  const followUp = nextScrollHaptic(fast, 135, 240, HAPTIC.feed);
  assert.equal(followUp.shouldPulse, false);
});

test("poster haptics match feed scroll feel", () => {
  assert.deepEqual(HAPTIC.poster, HAPTIC.feed);
  assert.equal(intervalForSpeed(0, HAPTIC.poster.minInterval, HAPTIC.poster.maxInterval), 280);
  assert.equal(intervalForSpeed(2.4, HAPTIC.poster.minInterval, HAPTIC.poster.maxInterval), 145);

  const feed = createScrollHapticState(0, 0);
  const poster = createScrollHapticState(0, 0);
  const feedFirst = nextScrollHaptic(feed, 72, 150, HAPTIC.feed);
  const posterFirst = nextScrollHaptic(poster, 72, 150, HAPTIC.poster);
  assert.deepEqual(
    {
      shouldPulse: posterFirst.shouldPulse,
      intervalMs: posterFirst.intervalMs,
      distancePx: posterFirst.distancePx,
    },
    {
      shouldPulse: feedFirst.shouldPulse,
      intervalMs: feedFirst.intervalMs,
      distancePx: feedFirst.distancePx,
    },
  );
});

test("feed haptics follow back-and-forth scroll travel instead of net displacement", () => {
  const feed = createScrollHapticState(0, 0);
  assert.equal(nextScrollHaptic(feed, 70, 100, HAPTIC.feed).shouldPulse, false);
  assert.equal(nextScrollHaptic(feed, 0, 270, HAPTIC.feed).shouldPulse, true);
});

test("haptic probe is opt-in for devtools cli", () => {
  const app = { globalData: { __hapticCli: { calls: [] } } };
  global.getApp = () => app;
  assert.equal(vibrateLight(), true);
  assert.equal(app.globalData.__hapticCli.calls.length, 1);
  assert.equal(app.globalData.__hapticCli.calls[0].type, "medium");
  delete global.getApp;
});
