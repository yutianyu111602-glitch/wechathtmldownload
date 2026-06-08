# OpenClaw Docker Profiles Contract Design

Status: approved-by-controller on 2026-06-02 CST.

## Goal

Move the OpenClaw weekly weapons lane from a report-only Docker gap into a statically verifiable Docker profile contract, without starting Docker or executing workers.

## Design

The control plane stays thin. OpenClaw/skill calls repo commands such as `weekly:openclaw:docker-profiles:contract-verify`; it does not contain crawler, OCR, DeepSeek, merge, deploy, or upload logic.

The repo owns a Docker Compose contract with seven profiles:

- L1 `openclaw-source-exporter`
- L2 `openclaw-source-queue-cache`
- L3 `openclaw-ocr`
- L4 `openclaw-llm-extraction`
- L5 `openclaw-map-verify`
- L6 `openclaw-package-merge`
- L7 `openclaw-deploy-upload-wrapper`

All profiles default to `network_mode: "none"`, secret injection metadata only, DB writes disabled, CloudBase/upload disabled, and report-local output. The container entrypoint is a report stub that emits a common health/report shape and all execution flags as false. A separate validator checks the Compose contract statically and writes JSON plus scorecard evidence.

## Boundaries

This design proves profile coverage and health/report schema only. It does not build images, start containers, fetch sources, call DeepSeek, rebuild packages, write DBs, sync CloudBase, upload the mini-program, submit review, or release. Any L1-L6 container dry-run requires a separate controller release.
