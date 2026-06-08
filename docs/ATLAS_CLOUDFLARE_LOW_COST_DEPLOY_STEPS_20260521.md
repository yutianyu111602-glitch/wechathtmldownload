# Atlas Cloudflare Low-Cost Deploy Steps - 2026-05-21

Status: Cloudflare edge/WAF + application Turnstile session gate deployed

Goal: launch the Atlas website behind low-cost protection first, without buying DataDome or Cloudflare Business.

Current deployed state:

- Origin VPS: `149.28.150.224`
- Hostname: `sg-atlas-origin`
- Origin guard: active
- Public direct IP access to `80/443`: blocked except Cloudflare IP ranges
- Cloudflare zone: `huaidj.club` active on Free plan
- Cloudflare DNS: `atlas` A record content `149.28.150.224`, proxied / orange cloud
- Cloudflare SSL/TLS mode: `Full`
- Cloudflare Turnstile: widget `Atlas Graph`, hostname `atlas.huaidj.club`, mode `Managed`
- Origin env file: `/etc/atlas/atlas.env`, mode `600`, owner `root:root`
  - Variables present: `TURNSTILE_SECRET_KEY`, `ATLAS_TURNSTILE_SECRET_KEY`
  - Secret value is not stored in this repo, docs, chat, or command output.
- Application gate: active
  - `/atlas/graph` is public page HTML and displays the Turnstile lock until a visitor receives the httpOnly `atlas_session` cookie.
  - `/api/v1/stage7/*` requires a valid Atlas session cookie and returns `403` without it.
  - Server-side Turnstile verification is active; only the public site key is exposed to the browser.
- Graph surface:
  - `https://atlas.huaidj.club/atlas/graph` is deployed.
  - Primary renderer is `3d-force-graph` + Three.js/WebGL, with bounded read-only graph APIs.
  - Public read model filters alcohol/menu/product and broader non-electronic noise; the raw SQLite DB is not mutated.
- Cloudflare WAF custom rule: `Atlas block bulk data probes`, action `Block`
  - Match: `atlas.huaidj.club` and path contains `.sqlite`, `.db`, `/api/v1/stage7/export`, `/export`, `/dump`, or `/bulk`
- Cloudflare WAF custom rule: `Atlas challenge scripted clients`, action `Managed Challenge`
  - Match: `atlas.huaidj.club`, path not equal `/healthz`, and UA is empty or contains `curl`, `Wget`, `python`, `Python`, `httpx`, `Scrapy`, `Go-http-client`, `HeadlessChrome`, `Playwright`, or `Puppeteer`
- Cloudflare rate limiting rule: `Atlas per-IP crawl throttle`, action `Block`
  - Match: `atlas.huaidj.club` and path not equal `/healthz`
  - Threshold: `60` requests / `10 seconds`, per IP, block duration `10 seconds`
- Local origin self-test:
  - `/healthz` -> `200`
  - `/atlas` -> `503` fail-closed
  - `/atlas.sqlite` -> `403` honey endpoint
- Public edge smoke:
  - `https://atlas.huaidj.club/healthz` -> `200` via Cloudflare
  - `https://atlas.huaidj.club/atlas/graph` -> `200` for browser UA
  - no-session `https://atlas.huaidj.club/api/v1/stage7/search?q=DADA&limit=1` -> `403`
  - `https://atlas.huaidj.club/atlas.sqlite` -> `403`
  - `https://atlas.huaidj.club/api/v1/stage7/export` -> `403`
  - `curl` UA to `https://atlas.huaidj.club/atlas` -> `403`
  - `curl` UA to `https://atlas.huaidj.club/atlas/graph` -> `403`
  - `http://149.28.150.224/healthz` -> timeout / curl exit `28`
- Remote script: `/root/atlas_low_cost_origin_guard_20260521.sh`
- Repo script: `scripts/ops/atlas_low_cost_origin_guard_20260521.sh`

## What To Buy

Start with:

- Cloudflare Free: `$0/month`
- Cloudflare Turnstile: `$0/month`

Upgrade only if needed:

- Cloudflare Pro: about `$20/month annual` or `$25/month monthly`, only if the dashboard requires it for the desired WAF/rate-limit rule set.

Do not buy for first launch:

- DataDome Advanced
- DataDome Premium
- Cloudflare Business

Escalate later if needed:

- AWS WAF + CloudFront pay-as-you-go.

## User Dashboard Steps

### 1. Add The Site

1. Log in to Cloudflare.
2. Add site: `huaidj.club`.
3. Pick Free plan first.
4. At the domain registrar, change nameservers to the two Cloudflare nameservers shown by Cloudflare.
5. Wait until Cloudflare marks the zone active.

If `huaidj.club` is already in Cloudflare, skip this step.

2026-05-21 result: `huaidj.club` was already present in Cloudflare, active, and on the Free plan.

### 2. Add Atlas DNS

In Cloudflare DNS:

| Type | Name | Content | Proxy |
| --- | --- | --- | --- |
| `A` | `atlas` | `149.28.150.224` | Proxied / orange cloud |

Do not add a gray-cloud DNS record for Atlas. A gray-cloud record exposes the origin IP path directly.

2026-05-21 result: created/verified the proxied `A atlas -> 149.28.150.224` DNS record.

### 3. Set TLS Mode

Initial mode for the already-deployed self-signed origin guard:

- Cloudflare dashboard -> SSL/TLS -> Overview -> set mode to `Full`.

2026-05-21 result: SSL/TLS mode is `Full`.

After the site is stable:

1. Cloudflare dashboard -> SSL/TLS -> Origin Server.
2. Create an Origin Certificate for `atlas.huaidj.club`.
3. Install that certificate/key on `149.28.150.224`.
4. Change SSL/TLS mode to `Full (strict)`.

Do not paste the origin private key in chat or docs. Use a secure secret handoff path or give Codex a dashboard/server session where it can install directly without printing it.

### 4. Create Turnstile

Cloudflare dashboard -> Turnstile:

1. Add site.
2. Name: `Atlas Graph`.
3. Domain: `atlas.huaidj.club`.
4. Widget mode: Managed.
5. Save the Site Key and Secret Key.

The Site Key is public and can go into app config. The Secret Key must stay in server-side secret storage only.

2026-05-21 result: widget `Atlas Graph` was created for `atlas.huaidj.club` in `Managed` mode. Keys were generated in Cloudflare but are not stored in this repo or chat.

2026-05-21 result: Turnstile Secret Key was written to the Atlas origin as root-only environment file `/etc/atlas/atlas.env` with both `TURNSTILE_SECRET_KEY` and `ATLAS_TURNSTILE_SECRET_KEY`. Server-side dummy `siteverify` returned `invalid-input-response`, confirming the secret itself is accepted by Cloudflare. Local temporary secret capture files and clipboard were cleared.

### 5. Add WAF Rules

Cloudflare dashboard -> Security -> WAF -> Custom rules.

Rule A: block bulk/export/honey paths.

```text
(http.host eq "atlas.huaidj.club" and (
  starts_with(http.request.uri.path, "/api/v1/stage7/export") or
  starts_with(http.request.uri.path, "/api/v1/stage7/full-graph") or
  starts_with(http.request.uri.path, "/api/v1/stage7/dump") or
  starts_with(http.request.uri.path, "/api/v1/stage7/bulk") or
  http.request.uri.path eq "/atlas.sqlite" or
  http.request.uri.path eq "/atlas.db" or
  http.request.uri.path eq "/atlas.json"
))
```

Action: Block.

Rule B: block obvious scraper user agents.

```text
(http.host eq "atlas.huaidj.club" and (
  lower(http.user_agent) contains "python-requests" or
  lower(http.user_agent) contains "aiohttp" or
  lower(http.user_agent) contains "go-http-client" or
  lower(http.user_agent) contains "scrapy" or
  lower(http.user_agent) contains "zgrab" or
  lower(http.user_agent) contains "censys" or
  lower(http.user_agent) contains "bytespider" or
  lower(http.user_agent) contains "gptbot" or
  lower(http.user_agent) contains "claudebot" or
  lower(http.user_agent) contains "oai-searchbot"
))
```

Action: Block.

Rule C: challenge Atlas surfaces.

```text
(http.host eq "atlas.huaidj.club" and (
  starts_with(http.request.uri.path, "/atlas") or
  starts_with(http.request.uri.path, "/api/v1/stage7/")
))
```

Action: Managed Challenge if available; otherwise JS Challenge.

### 6. Add Rate Limits If Available

Cloudflare dashboard -> Security -> WAF -> Rate limiting rules.

Minimum rules:

- `/api/v1/stage7/search`: challenge/block after about `60` requests per `10` minutes per IP.
- `/api/v1/stage7/graph/*`: challenge after about `80` requests per `10` minutes per IP; block obvious repeated offenders.
- `/atlas*`: challenge after about `120` requests per `10` minutes per IP.

If Free does not expose enough rate-limit controls, upgrade to Cloudflare Pro before considering anything more expensive.

2026-05-21 result:

- Custom WAF rule `Atlas block bulk data probes` is active and blocks bulk/export/database probe paths on `atlas.huaidj.club`.
- Custom WAF rule `Atlas challenge scripted clients` is active and applies Managed Challenge to obvious script/headless UAs on Atlas non-health paths.
- Rate limiting rule `Atlas per-IP crawl throttle` is active and blocks traffic that exceeds `60` requests per `10 seconds` per IP, excluding `/healthz`.

## If Codex Should Configure Cloudflare Directly

Provide one of these safe access methods:

- temporary Cloudflare dashboard invite with minimal permissions for `huaidj.club`, or
- a scoped Cloudflare API token delivered through a secure local secret path, not pasted in chat.

Minimum token permissions if using an API token:

- Zone -> DNS -> Edit
- Zone -> Zone Settings -> Edit
- Zone -> WAF -> Edit
- Account -> Turnstile -> Edit, if Turnstile API setup is desired

Do not include billing permissions unless you explicitly want Codex to change the plan. For payment, the user should approve the Cloudflare plan in the dashboard.

## Remaining Hardening Steps

1. Install Cloudflare Origin Certificate and switch to `Full (strict)`.
2. Vendor or pin graph renderer assets if CDN dependence becomes unacceptable for production.
3. Re-run bot smokes after any WAF/session/renderer change:
   - empty user agent
   - `python-requests`
   - honey endpoint
   - repeated search loop
   - sequential detail enumeration
4. Review Cloudflare logs after launch; upgrade to Cloudflare Pro only if Free-plan controls are not enough.
