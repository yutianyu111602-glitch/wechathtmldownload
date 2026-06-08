<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Handoff Specification

**Created:** 2026-04-27
**Status:** SKELETON

## Purpose

Enable any agent (OpenCode, human, GA) to resume work from a checkpoint without ambiguity.

## Required Sections

### 1. Current Goal
One sentence. What were we trying to achieve?

### 2. Completed
Bullet list. What finished successfully with evidence paths.

### 3. In Progress
What was active when paused/stopped. Exact story ID, phase, progress numbers.

### 4. Blocked
What's preventing progress. Include error messages, failure counts.

### 5. Risks
Active risks, new risks discovered, risk mitigations attempted.

### 6. Next Step
Concrete next action with exact command or decision needed.

### 7. Forbidden Actions
What the next agent must NOT do. Be specific with paths, commands, profiles.

### 8. Evidence Paths
File paths for: checkpoint, run log, config diff, reports, error logs.

### 9. Profile State
Which model profile was active. Which profiles are available. Any profile changes made.

### 10. Need Human
YES/NO with reasoning. If YES, what decision is needed?

## Template

```markdown
# Handoff — {date} {time}

## Current Goal
{one sentence}

## Completed
- [ ] {item} → {evidence_path}

## In Progress
- Story: {US-XXX}
- Phase: {name}
- Progress: {n}/{total} ({percent}%)

## Blocked
- {blocker description}

## Risks
| Risk | Severity | Status |

## Next Step
{exact command or decision}

## Forbidden
- {specific prohibition}

## Evidence
| Artifact | Path |

## Profile
- Active: {profile_name}
- Available: {list}

## Need Human
{YES/NO} — {reason}
```
