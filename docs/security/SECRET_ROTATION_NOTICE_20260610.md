# Secret Rotation Notice — 2026-06-10

## Finding

A `DEEPSEEK_API_KEY` exists in `services/weekly_activity_cloudrun/.env` on the local disk.

## Current Status

- **File**: `services/weekly_activity_cloudrun/.env`
- **Tracked in Git**: NO — `.gitignore` correctly excludes `.env`
- **Pushed to private repo**: NO — verified by `git ls-files`
- **Readable on local disk**: YES — any local user/process can read it
- **Key value**: NOT RECORDED HERE — never write real keys in docs

## Required Human Action (P0)

1. **Rotate the key immediately** at https://platform.deepseek.com/api_keys
2. **Update local `.env`** with the new key: `DEEPSEEK_API_KEY=<new-key>`
3. **Verify `.gitignore` continues to exclude `.env`**: `git check-ignore services/weekly_activity_cloudrun/.env`
4. **Delete the old key** from DeepSeek platform after rotation

## Verification

```powershell
# Confirm .env is git-ignored
git check-ignore services/weekly_activity_cloudrun/.env
# Expected output: services/weekly_activity_cloudrun/.env

# Confirm .env is not tracked
git ls-files services/weekly_activity_cloudrun/.env
# Expected output: (empty)

# After rotation, verify the new key works
cd services/weekly_activity_cloudrun
node -e "require('dotenv').config(); console.log(process.env.DEEPSEEK_API_KEY ? 'KEY_SET' : 'KEY_MISSING')"
```

## Rules

- Never record real API keys in documentation, commits, memory, or chat
- Never print `.env` file contents
- The `.env.example` file documents required variables with placeholder values only
- All `.env` files must remain in `.gitignore`
