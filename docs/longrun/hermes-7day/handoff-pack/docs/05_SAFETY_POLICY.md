<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Safety Policy — Hermes WSL2 7-Day Longrun

**Version:** v1.0
**Date:** 2026-04-28

---

## 1. D Drive Scan Guard

**FORBIDDEN:**
```bash
# Recursive scan of 16TB HDD
find /mnt/d/DDownload -type f
find /mnt/d/aidata -type f
Get-ChildItem -Recurse D:\DDownload
Get-ChildItem -Recurse D:\aidata
ls -R /mnt/d/DDownload
ls -R /mnt/d/aidata
rg /mnt/d/DDownload
rg /mnt/d/aidata
du -sh /mnt/d/DDownload
```

**ALLOWED:**
```bash
# Targeted access via known paths
ls /mnt/d/DDownload/_llm_release_v2/manifest.json
head -5 /mnt/d/DDownload/_llm_release_v2/index.jsonl
ls /mnt/d/DDownload/_llm_release_v2/articles/
```

---

## 2. Release Pack Protection

`D:\DDownload\_llm_release_v2` is **final output, read-only**.

- Do NOT write to this directory
- Do NOT delete this directory
- Do NOT rebuild or re-run `finalize-llm-pack`
- Do NOT modify `manifest.json` or `index.jsonl`

---

## 3. Old Directory Isolation

`D:\DDownload\_llm_release` is **legacy partial directory**.

- Do NOT use as input for any processing
- Do NOT delete (may contain unique data)
- All downstream must use `_llm_release_v2`

---

## 4. Model & Provider

- Primary planning: `deepseek-v4-pro` via `https://api.deepseek.com`
- Local extraction: `Qwen3.6-27B` via `llama-swap:11434`
- Commands must explicitly specify model
- **FORBIDDEN:** OpenRouter fallback without approval
- **FORBIDDEN:** Auto-switch to external model
- **FORBIDDEN:** Using `WECHAT_DOWNSTREAM_MODEL` env var (untrusted)

---

## 5. WeChat UI Automation Safety

- **FORBIDDEN:** Blind mouse clicks without window verification
- **FORBIDDEN:** Sending keystrokes to wrong window
- **REQUIRED:** Verify WeChat window title before automation
- **REQUIRED:** Check window is responding before interaction
- **LIMIT:** Max 100 items per capture run (prevents runaway)

---

## 6. Agent Control

- OpenClaw / AG / Hermes: Only Hermes runs as orchestrator
- If OpenClaw or AG detected running as controller: Mark RED, do NOT kill
- **FORBIDDEN:** Starting OpenClaw as main controller
- **FORBIDDEN:** Starting AG as main controller
- **FORBIDDEN:** Auto-starting `final_pack`

---

## 7. Cleanup

All cleanup must be **dry-run first**.

- **FORBIDDEN:** `rm`, `del`, `rmdir`, `Remove-Item` on data directories
- **FORBIDDEN:** Moving or archiving data without human approval
- **ALLOWED:** Writing cleanup plan for review
- **ALLOWED:** Cleaning temp files in output directory

---

## 8. Longrun Requirements

All long tasks MUST have:

- [ ] Checkpoint (every 50 items or 30 min)
- [ ] Run log (append-only)
- [ ] Monitor summary (GREEN/AMBER/RED)
- [ ] Recovery command documented
- [ ] Checkpoint > 60 min stale = RED

---

## 9. Failure Budget

| Level | Budget |
|-------|--------|
| Single article retry | Max 2 times |
| Single story fix | Max 3 attempts |
| Capture failure rate | < 15% GREEN, 15-25% AMBER, > 25% RED |
| Model unreachable | 3 consecutive = RED |
| Same failure pattern 3x | Stop and analyze |

---

## 10. WSL2-Specific Safety

- **FORBIDDEN:** Running `wsl --shutdown` during active capture
- **FORBIDDEN:** Accessing Windows registry from WSL2
- **FORBIDDEN:** Modifying Windows system files via `/mnt/c/`
- **ALLOWED:** Reading files via `/mnt/c/`, `/mnt/d/`
- **ALLOWED:** Running Windows executables via `powershell.exe -Command`

---

## 11. mem0 Safety

- **FORBIDDEN:** Storing API keys, tokens, passwords in mem0
- **FORBIDDEN:** Storing raw conversation logs
- **ALLOWED:** Storing learnings, patterns, decisions
- **ALLOWED:** Storing checkpoint summaries
- **REQUIRED:** Use `agent_id=hermes_wechat_pipeline`

---

## 12. User Away Special Rules

When user is away (7-day unattended):

- Do NOT execute destructive actions requiring human judgment
- Write plans and reasons for blocked actions
- Wait for user return for:
  - Deleting any data directory
  - Changing model/provider configuration
  - Starting new pipeline stages not in PRD
  - Any action with irreversible consequences

---

**End of Safety Policy. Next: `docs/06_WSL2_HERMES_CONFIG.md`**
