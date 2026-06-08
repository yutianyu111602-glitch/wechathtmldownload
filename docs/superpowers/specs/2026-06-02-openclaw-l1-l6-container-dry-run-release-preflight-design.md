# OpenClaw L1-L6 Container Dry-Run Release Preflight Design

Status: approved-by-controller on 2026-06-02 CST.

## Goal

Create the next serial gate after static Docker profile validation: a report-only preflight that decides whether an explicit controller release may start a future L1-L6 container dry-run. It must not start Docker or touch deploy/upload.

## Design

The preflight consumes three authoritative inputs:

- the static Docker profile contract validator
- the no-quota direct DeepSeek incremental preflight
- the release guard latest status

It requires all L1-L6 profiles to be declared and excludes L7 deploy/upload from the dry-run scope. It also requires release guard to remain fail-closed before the dry-run, because this packet is not release readiness. The output JSON records the future command sequence and stop conditions for a later explicit controller release, but marks `dry_run_runtime_release_created_by_this_packet=false`.

The control plane remains thin: OpenClaw/skill can run the npm preflight command and read JSON, while runtime work stays inside Docker profiles after a separate release.

## Boundaries

This design does not invoke Docker, start workers, fetch network resources, call DeepSeek, rebuild packages, write DBs, sync CloudBase, upload the mini-program, submit review, release, or read credential values.
