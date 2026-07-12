// utils/atlasLoading.js
// Deterministic loading-animation data for the ATLAS starmap page.
// Exports: buildLdDots() → [{i,x,y,d,c}], LOADING_MSGS[].
// Pure, ES5. No wx, no timer logic (timer lifecycle lives in the page).

var LOADING_MSGS = ["加载节点", "读取关系", "生成图谱", "即将就绪"];

// Build 12 dots: 1 centre (lime) + 5 inner ring (blue) + 6 outer ring (violet).
// All positions are % of the 240×240 rpx field. Delays in seconds.
// Uses stable trig — no Math.random, so output is identical on every call.
function buildLdDots() {
  var dots = [];
  var pi2 = 6.28318530718;
  var i, a;

  // Centre
  dots.push({ i: 0, x: 50, y: 50, d: 0, c: "#A7FF26" });

  // Inner ring r=22%, 5 dots starting at 0°
  for (i = 0; i < 5; i++) {
    a = i * pi2 / 5;
    dots.push({
      i: dots.length,
      x: Math.round((50 + 22 * Math.cos(a)) * 10) / 10,
      y: Math.round((50 + 22 * Math.sin(a)) * 10) / 10,
      d: Number((0.15 + i * 0.10).toFixed(2)),
      c: "#7fd4ff",
    });
  }

  // Outer ring r=38%, 6 dots offset 30° to interleave with inner ring
  for (i = 0; i < 6; i++) {
    a = i * pi2 / 6 + pi2 / 12;
    dots.push({
      i: dots.length,
      x: Math.round((50 + 38 * Math.cos(a)) * 10) / 10,
      y: Math.round((50 + 38 * Math.sin(a)) * 10) / 10,
      d: Number((0.65 + i * 0.10).toFixed(2)),
      c: "#b794f6",
    });
  }

  return dots; // 12 total
}

module.exports = {
  buildLdDots: buildLdDots,
  LOADING_MSGS: LOADING_MSGS,
};
