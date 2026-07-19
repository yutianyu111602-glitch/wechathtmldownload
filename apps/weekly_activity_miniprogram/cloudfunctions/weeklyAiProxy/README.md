# weeklyAiProxy

WeChat CloudBase cloud function used by the mini-program AI page.

Input shape from `utils/api.js`:

```json
{
  "method": "GET",
  "path": "/api/v1/weekly/llm/materialized-summary",
  "query": {
    "_ts": 1760000000000
  },
  "body": {},
  "source": "wechat-cloud-ai"
}
```

Runtime behavior:
- Allows only `/api/v1/weekly/llm/*` routes used by the mini-program.
- Uses CloudBase AI first for `/api/v1/weekly/llm/weekly-summary`.
- Returns CloudBase AI status for `/api/v1/weekly/llm/status`.
- Falls back to `WEEKLY_AI_PROXY_BASE_URL` or the public `weekly-api` CloudRun URL when CloudBase AI generation fails or for materialized data routes.
- Returns the payload plus a `cloudFunction` metadata block.
- Returns `{ error: ... }` for blocked paths, upstream errors, or timeout.

Environment:
- `WEEKLY_AI_PROXY_BASE_URL`: optional upstream base URL.
- `WEEKLY_AI_PROXY_TIMEOUT_MS`: optional request timeout, default `2500` because the DevTools-created function currently reports a 3 second cloud timeout.
- `WEEKLY_CLOUDBASE_AI_PROVIDER`: optional CloudBase AI provider, default `hunyuan-v3`.
- `WEEKLY_CLOUDBASE_AI_MODEL`: optional CloudBase AI model, default `hy3-preview`.
- `WEEKLY_CLOUDBASE_AI_TIMEOUT_MS`: optional CloudBase AI generation timeout, default `60000`.
