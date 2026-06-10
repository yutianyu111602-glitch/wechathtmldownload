# ADR-002: Three-Tier API Fallback for Mini-program

**Date**: 2026-06-10
**Status**: Accepted

## Context

The WeChat mini-program runs on mobile devices with unreliable network conditions.
Users in underground venues often have no signal. The app must show event data
even when the network is unavailable.

## Decision

Implement a **three-tier data fallback chain**:

1. **wx.cloud.callFunction** (CloudBase) — primary, uses WeChat Cloud Development
2. **CloudRun HTTP API** — fallback, direct HTTP request to CloudRun service
3. **Offline snapshot** — last resort, hardcoded stale data built into the app

## Rationale

1. **CloudBase first**: Fastest path within WeChat ecosystem, no cross-origin issues,
   built-in authentication via WeChat identity.
2. **CloudRun fallback**: If CloudBase functions are unavailable (cold start, quota),
   the CloudRun HTTP API provides the same data.
3. **Offline snapshot**: When all network is unavailable, the built-in snapshot ensures
   the app never shows a blank screen. Data may be stale but is always visible.

## Key Parameters

| Parameter | Value | Reason |
|-----------|-------|--------|
| `offlineSnapshotFallback` | `true` | Previously `false` caused black screen |
| `fastOfflineSnapshotFallback` | `true` | Skip unnecessary waits |
| `offlineSnapshotFallbackDelayMs` | `2500` | Give network 2.5s before fallback |
| `publicRequestTimeoutMs` | `3000` | Was 1200ms — too short on slow 4G |
| Cache max age | 7 days | Weekly data doesn't change within a week |
| Cache fallback delay | 2200ms | Wait before using stale cache |

## Consequences

- **Positive**: App always shows content, never blank screen
- **Negative**: Offline data can be stale (up to 7 days cache + snapshot age)
- **Trade-off**: User experience (always see something) vs data freshness
