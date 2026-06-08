# OpenClaw L1-L6 Container Dry-Run Controller Release Design

Status: approved-by-controller on 2026-06-02 CST.

## Goal

Create the controller release packet that can authorize the next OpenClaw L1-L6 container runtime dry-run while keeping L7 deploy/upload and all public release actions locked.

## Design

The release packet consumes the already-ready L1-L6 release preflight plus the latest release-guard status. It succeeds only when the preflight decision is ready, failed required checks are zero, L1-L6 is the exact included scope, L7 is the exact excluded scope, direct DeepSeek is declared for no-quota materialization, and release guard is still fail-closed.

The output is a machine-readable controller release contract. It sets `controller_release_created_by_this_packet=true` and `runtime_dry_run_allowed_by_this_packet=true`, but `runtime_dry_run_executed_by_this_packet=false`. It records the six future Docker commands, expected report-local runtime artifacts, runtime policies, acceptance checks, and stop conditions.

OpenClaw skills remain thin control plane: they may call the npm command, read the JSON, and later trigger the listed container commands after this release is consumed. Runtime logic stays in Docker profiles and report-local outputs.

## Boundaries

This design does not invoke Docker, start workers, fetch network resources, call DeepSeek, rebuild public packages, write DBs, sync CloudBase, upload the mini-program, submit review, release, or read credential values. L6 may only produce report-local package materialization evidence in the future runtime dry-run; L7 remains excluded.
