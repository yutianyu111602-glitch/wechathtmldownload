<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Control Plane PRD

**Created:** 2026-04-27
**Status:** SKELETON

## 1. Product Goal

A governance layer for long-running WeChat Pipeline tasks that provides observability, handoff, pause/resume, and escalation without allowing models unrestricted autonomy.

## 2. Core Users

| User | Role | Interaction |
|------|------|-------------|
| Me (human) | Owner, approver | Review reports, approve escalations |
| OpenCode | Executor (builder profile) | Runs audited tasks, creates docs |
| OpenClaw | Frozen | Not active |
| GA Monitor | Read-only watcher | Observes, classifies, escalates |

## 3. Goals

- Stable long task execution with checkpoints
- Observable: every task leaves evidence
- Escalatable: RED conditions trigger Pro analysis
- Handoff-ready: any agent can resume from checkpoint
- Pauseable/resumable: no lost state on interrupt
- Upgradable: profiles can evolve without breaking docs

## 4. Non-Goals

- NOT a production business system
- NOT a general-purpose agent platform
- NOT enabling models to operate without human gating
- NOT replacing manual pipeline commands

## 5. Profile Boundaries

| Profile | Use | Forbidden |
|---------|-----|-----------|
| deepseek-builder | Docs, plans, skeleton | Production execution |
| deepseek-v4-pro | RED root cause analysis | File writes, batch execute, production |
| deepseek-v4-flash | Watch, log summary | Decisions, config changes |

## 6. Success Criteria

- All skeleton docs complete
- US-000 audit executed and passed
- US-001 baseline captured
- GA monitor protocol operational
- 0 unauthorized production runs before US-002 gate
