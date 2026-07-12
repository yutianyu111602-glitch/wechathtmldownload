const SCROLL_HAPTIC_PROFILE = {
  minInterval: 145,
  maxInterval: 280,
  slowDistance: 140,
  fastDistance: 64,
};

const HAPTIC = {
  defaultType: "medium",
  refreshInterval: 320,
  tabInterval: 220,
  poster: { ...SCROLL_HAPTIC_PROFILE },
  feed: { ...SCROLL_HAPTIC_PROFILE },
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function intervalForSpeed(speed, minInterval, maxInterval) {
  const safeSpeed = clamp(Number(speed) || 0, 0, 2.4);
  const ratio = safeSpeed / 2.4;
  return Math.round(maxInterval - (maxInterval - minInterval) * ratio);
}

function distanceForSpeed(speed, slowDistance, fastDistance) {
  const safeSpeed = clamp(Number(speed) || 0, 0, 2.4);
  const ratio = safeSpeed / 2.4;
  return Math.round(slowDistance - (slowDistance - fastDistance) * ratio);
}

function recordHapticProbe(type) {
  try {
    if (typeof getApp !== "function") return;
    const app = getApp();
    const probe = app.globalData && app.globalData.__hapticCli;
    if (!probe || !Array.isArray(probe.calls)) return;
    probe.calls.push({ at: Date.now(), type });
  } catch {}
}

function normalizeHapticType(type) {
  return type === "heavy" || type === "medium" || type === "light" ? type : HAPTIC.defaultType;
}

function vibrateLight(type = HAPTIC.defaultType) {
  const safeType = normalizeHapticType(type);
  recordHapticProbe(safeType);
  if (typeof wx === "undefined") return false;
  if (!wx.vibrateShort) return false;
  try {
    wx.vibrateShort({ type: safeType });
    return true;
  } catch {
    try {
      wx.vibrateShort();
      return true;
    } catch {
      return false;
    }
  }
}

function createScrollHapticState(position = 0, now = 0) {
  return {
    lastPosition: Number(position) || 0,
    lastAt: Number(now) || 0,
    lastPulsePosition: Number(position) || 0,
    lastPulseAt: 0,
    travelSincePulse: 0,
  };
}

function nextScrollHaptic(state, position, now, profile) {
  const current = Number(position) || 0;
  const at = Number(now) || 0;
  const previousAt = Number(state.lastAt) || at;
  const dt = Math.max(16, at - previousAt);
  const delta = Math.abs(current - (Number(state.lastPosition) || 0));
  const speed = delta / dt;
  const intervalMs = intervalForSpeed(speed, profile.minInterval, profile.maxInterval);
  const burstInterval = Number(profile.burstInterval) || 0;
  const effectiveIntervalMs = Number(state.lastPulseAt) ? Math.max(intervalMs, burstInterval) : intervalMs;
  const distancePx = distanceForSpeed(speed, profile.slowDistance, profile.fastDistance);
  const travelSincePulse = (Number(state.travelSincePulse) || 0) + delta;
  const elapsedSincePulse = at - (Number(state.lastPulseAt) || 0);
  const shouldPulse = elapsedSincePulse >= effectiveIntervalMs && travelSincePulse >= distancePx;

  state.lastPosition = current;
  state.lastAt = at;
  state.travelSincePulse = travelSincePulse;
  if (shouldPulse) {
    state.lastPulsePosition = current;
    state.lastPulseAt = at;
    state.travelSincePulse = 0;
  }

  return {
    shouldPulse,
    intervalMs: effectiveIntervalMs,
    distancePx,
    speed,
  };
}

module.exports = {
  HAPTIC,
  createScrollHapticState,
  intervalForSpeed,
  nextScrollHaptic,
  vibrateLight,
};
