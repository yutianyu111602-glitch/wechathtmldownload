<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Long Run Control Plane — Index

**Created:** 2026-04-27
**Phase:** pre-US-000 governance skeleton
**Status:** SKELETON (ready for review)

## What This Solves

The WeChat Pipeline Super Long Run needs governance before execution. This control plane defines:

- Who does what (model profiles, roles)
- What to monitor (GA protocol)
- How to escalate (RED/AMBER/GREEN)
- What evidence to keep (checkpoint, handoff, report)
- What NOT to do (safety policy, scan guards)

Without this, long runs drift into untracked failures, silent context exhaustion, and unrecoverable state.

## Documents

| # | File | Purpose |
|---|------|---------|
| 00 | INDEX.md | This file — entry point |
| 01 | PRD.md | Control plane product definition |
| 02 | RUNBOOK.md | Daily operations manual |
| 03 | GA_MONITOR_PROTOCOL.md | GA read-only monitoring rules |
| 04 | MODEL_PROFILE_POLICY.md | Profile boundaries and use cases |
| 05 | LOCAL_MODEL_REGISTRY.md | Local GGUF model inventory |
| 06 | EVIDENCE_PACK_SPEC.md | Required evidence per task |
| 07 | HANDOFF_SPEC.md | Handoff format and rules |
| 08 | RALPH_SUPERPOWER_BRAINSTORM_PLAN.md | Re-enabling Ralph after timeouts |
| 09 | US000_TOOLING_CAPABILITY_AUDIT_PLAN.md | Audit scope for US-000 |
| 10 | RISK_REGISTER.md | Known risks and mitigations |
| 11 | ACCEPTANCE_CHECKLIST.md | Skeleton creation verification |

## Current State

```
Phase: pre-US-000 (governance skeleton)
US-000: NOT STARTED
US-001: NOT STARTED
US-002: NOT STARTED
Production Tasks: 0
Dry-run: NOT STARTED
```

## Model Profiles (Active)

| Profile | Model | Role |
|---------|-------|------|
| deepseek-builder | v4-pro | PRD, plans, skeleton (current) |
| deepseek-v4-pro | v4-pro | RED escalation only |
| deepseek-v4-flash | v4-flash | Watch, monitoring |

## Next

1. Review all 11 skeleton files
2. Execute US-000 (Tooling Capability Audit)
3. Then US-001 (Baseline Freeze)
