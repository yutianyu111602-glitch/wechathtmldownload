# ADR-004: CloudRun + CloudBase Dual Hosting

**Date**: 2026-06-10
**Status**: Accepted

## Context

The weekly activity service needs to be accessible from both the WeChat mini-program
and web browsers. We need to choose a hosting architecture.

## Decision

Use **Tencent CloudRun** for the API server and **Tencent CloudBase** for storage
and WeChat Cloud Development functions.

- CloudRun: hosts the Node.js HTTP server (`server.mjs`), serves API and HTML pages
- CloudBase: stores poster images (`cloud://` file IDs), provides `wx.cloud.callFunction`
  for the mini-program's primary data path

## Rationale

1. **CloudRun for API**: Full Node.js runtime, supports all server features (Atlas SQLite,
   session management, DeepSeek client, HTML rendering). No cold-start penalty
   for complex routes.
2. **CloudBase for storage**: WeChat native `cloud://` file IDs are directly renderable
   in mini-program `<image>` tags. No CDN URL needed. Upload via CloudBase SDK.
3. **CloudBase for primary data**: `wx.cloud.callFunction` is the fastest data path
   within the WeChat ecosystem — no CORS, no HTTP overhead, built-in auth.
4. **Separation of concerns**: Storage (CloudBase) vs compute (CloudRun) allows
   independent scaling and deployment.

## Data Flow

```
Mini-program
  ├─ wx.cloud.callFunction → CloudBase → CloudRun API → JSON files
  ├─ HTTP request → CloudRun API → JSON files
  └─ Offline snapshot (built-in)
  
Web browser
  └─ HTTPS → CloudRun API → JSON files / Atlas SQLite
```

## Consequences

- **Positive**: Best WeChat integration, native file ID support, independent scaling
- **Negative**: Two Tencent services to manage, CloudBase envId is semi-public
  (in `cloudbaserc.json`), deployment requires both services to be updated
- **Risk**: CloudRun cold start on first request after deploy (mitigated by
  keeping container warm via periodic health checks)
