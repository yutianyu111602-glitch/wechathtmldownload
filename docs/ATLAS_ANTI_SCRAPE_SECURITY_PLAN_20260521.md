# Atlas Anti-Scrape Security Plan - 2026-05-21

Status: active security gate / deployed Atlas graph origin

Scope: protect the China underground electronic music Atlas web/API surface from bulk scraping, AI crawlers, API harvesting, and opportunistic probes. This plan covers the planned `/atlas/graph` surface, existing `/atlas`, `/atlas/local`, detail pages, and `/api/v1/stage7/*` Atlas APIs.

Hard rule: **no public Atlas data API access without Cloudflare edge protection and a server-side Turnstile session gate**.

2026-05-21 revised decision: **do not buy DataDome Advanced or Cloudflare Business for the first launch**. The first-launch route is **Cloudflare Free or Pro + Cloudflare Turnstile + strict origin/app limits**. If scraping pressure proves higher, upgrade to **AWS WAF + CloudFront pay-as-you-go** before considering expensive enterprise bot vendors.

2026-05-21 22:03 CST deployment state: `149.28.150.224` serves the Atlas graph page through Nginx -> `atlas-weekly-api.service` on `127.0.0.1:8787`. Nginx, UFW, and fail2ban are installed; 80/443 are allowed only from Cloudflare IP ranges; `/atlas/graph` returns 200 through Cloudflare; `/api/v1/stage7/*` returns 403 until a valid Turnstile-backed session cookie exists; honey bulk endpoints return 403. Direct public `curl` to the origin IP on 80/443 and direct `8787` timed out from the workstation.

2026-05-21 Cloudflare dashboard state: `huaidj.club` is active on the Free plan; DNS has proxied `A atlas -> 149.28.150.224`; SSL/TLS mode is `Full`; Turnstile widget `Atlas Graph` is created for `atlas.huaidj.club` in `Managed` mode. Turnstile keys were generated in Cloudflare but must not be stored in repo docs or chat. Edge smoke returns `200` for `https://atlas.huaidj.club/healthz` through Cloudflare; direct origin HTTP smoke times out.

2026-05-21 Turnstile state: the Atlas origin stores the Turnstile Secret Key only in `/etc/atlas/atlas.env` with mode `600` and owner `root:root`. Variables present include the secret names and public site-key names; secret values are not stored in repo docs or chat. Invalid-token smoke returns `TURNSTILE_FAILED` with Cloudflare `invalid-input-response`, confirming server-side verification is active. Do not copy the secret into docs, chat, git, static frontend config, logs, or client bundles.

2026-05-21 WAF state: Free-plan security rules are active for `atlas.huaidj.club`. Custom rule `Atlas block bulk data probes` blocks `.sqlite`, `.db`, `/api/v1/stage7/export`, `/export`, `/dump`, and `/bulk` paths. Custom rule `Atlas challenge scripted clients` applies Managed Challenge to obvious script/headless UAs on non-health paths. Rate limiting rule `Atlas per-IP crawl throttle` blocks requests above `60` per `10 seconds` per IP, excluding `/healthz`, for `10 seconds`. Public smoke: `/healthz` returns `200`; `/atlas.sqlite` and `/api/v1/stage7/export` return `403`; `curl` UA to `/atlas` returns `403`; direct origin HTTP still times out.

## Current Server Reality

Old SGP VPS:

- Host: `139.180.136.181`
- Domain surface: `huaidj.club`
- Nginx config: `/etc/nginx/sites-enabled/huaidj.club`
- Current exposed ports: `22`, `80`, `443`; app/model/db direct ports are denied by UFW.
- Current Nginx baseline already has:
  - `limit_req_zone` for general API, submit API, and lookup API.
  - `.env`, `.git`, `.svn`, `.htaccess`, `.htpasswd` blocks.
  - `.sql`, `.sqlite`, `.db`, `.dump`, `.bak`, `.old`, `.log` blocks.
  - common WordPress/PHP probe blocks.
- 2026-05-21 update:
  - former public huaidj root and old `/api` now return `410 Gone`.
  - `/finagent-beta/` remains preserved.
- fail2ban jails active:
  - `nginx-badbots`
  - `nginx-req-limit`
  - `sshd`

Recent access-log sample contains scanners/bots:

- `libredtail-http`
- `Infrawatch`
- `CensysInspect`
- `zgrab`
- `python-requests`
- `aiohttp`
- `Go-http-client`
- `OAI-SearchBot`
- WordPress/PHP exploit probes such as `/wp-login.php`, `/xmlrpc.php`, `/cgi-bin/...`

Current Atlas product truth:

- Existing public CloudRun `/atlas` and `/api/v1/stage7/*` are read-only product surfaces.
- Current local Atlas DB is about `3.98GB`; it must not be downloadable or directly exposed.
- Full graph data must never be returned to browsers. Only bounded subgraphs are allowed.

New SGP VPS:

- Host: `149.28.150.224`
- Hostname: `sg-atlas-origin`
- Former role: Claude proxy (`xray`, WARP, subscription server).
- 2026-05-21 update:
  - Claude is retired by user instruction.
  - `xray.service`, `sub-server.service`, `warp-svc.service`, and `wg-quick@warp.service` are stopped/disabled.
  - UFW now allows SSH, allows `80/tcp` and `443/tcp` only from Cloudflare IP ranges, and explicitly denies former proxy ports `8443/tcp` and `18443/tcp`.
  - This VPS is now the preferred clean Atlas origin candidate.
  - Nginx origin guard is active and fail-closed for Atlas data surfaces.
  - Deployment script: `scripts/ops/atlas_low_cost_origin_guard_20260521.sh`.
  - Remote backup artifact: `/root/atlas-origin-guard-backups/20260521T101252Z`.

## Provider Decision

### Selected Plan: Cloudflare Free/Pro + Turnstile + Origin Guard

Use Cloudflare as the low-cost edge and Turnstile as the human/session gate. Keep the Atlas origin locked so only Cloudflare can reach 80/443. Keep the application fail-closed until it has a server-side session gate and bounded graph APIs.

Buy:

- Cloudflare Free first if the user wants zero fixed edge cost.
- Cloudflare Pro only if the dashboard requires paid WAF/rate-limit features for the desired rule set; public price checked on 2026-05-21 is about `$20/month annual` or `$25/month monthly`.
- Cloudflare Turnstile is free at the time of the 2026-05-21 check.
- Do not buy Cloudflare Business or DataDome for the first launch.

Required product features:

- Done: Cloudflare proxied DNS for `atlas.huaidj.club`.
- Done: Cloudflare WAF custom rules and rate limiting on the Free plan.
- Done: Cloudflare Turnstile widget for Atlas session issuance.
- Done: origin lock so direct IP access cannot bypass Cloudflare.
- Done: Nginx/fail2ban honey endpoint handling.
- Public-enabled: server-side Atlas session middleware, Turnstile verification endpoint, app-level honey endpoints, hidden DB-path responses, read-only SQLite mode, and per-session graph API rate limits are active on `atlas.huaidj.club`.

Official basis:

- Cloudflare Turnstile pricing/docs list Turnstile as the low-cost CAPTCHA alternative.
- Cloudflare plans page lists Free, Pro, Business, and Enterprise tiers; Business is not required for this initial protected launch.
- AWS WAF pricing is pay-as-you-go and remains the next escalation path if Cloudflare Free/Pro is insufficient.

- Cloudflare docs state WAF, Bot Management, and Turnstile protect different layers: WAF filters network signals, Bot Management identifies automated threats, and Turnstile checks browser/client-side signals.
- Cloudflare docs also state WAF/Bot Management require DNS through Cloudflare, while Turnstile can be used independently.

### Escalation Plan: AWS WAF + CloudFront Pay-As-You-Go

Use AWS WAF + CloudFront if Cloudflare Free/Pro does not stop scraping pressure, but enterprise bot vendors are still too expensive.

Good fit:

- Pay-as-you-go instead of thousands of dollars per month.
- AWS WAF CAPTCHA pricing is per attempt.
- AWS Bot Control Common can be added without buying DataDome.
- CloudFront can sit in front of the same `149.28.150.224` origin if the domain route is migrated.

Tradeoff:

- More AWS setup complexity than Cloudflare.
- The Atlas origin lock and TLS mode need to be reworked for CloudFront origin access.

### Rejected For First Launch: DataDome Advanced + Cloudflare Business

Rejected because the 2026-05-21 checked public pricing is too expensive for the current phase: DataDome Advanced is around `$8,670/month`, and Cloudflare Business is around `$200-$250/month`. These remain future enterprise escalation options only if the Atlas becomes a high-revenue public product with active scraping attacks that justify the cost.

### Tencent-Native Option: Tencent Cloud EdgeOne

Use EdgeOne if Atlas remains primarily under Tencent Cloud / CloudBase domain routing.

Good fit:

- Tencent edge security stack.
- DDoS, CC, Web/Bot protection.
- CAPTCHA / JavaScript / Managed challenge options.
- Better alignment with Tencent CloudBase and China-region operations.

Tradeoff:

- Cross-provider protection for `huaidj.club` and the old Vultr VPS may be less clean than Cloudflare unless DNS/routing is consolidated.

## Defense Model

### Layer 0 - Data Minimization

Do not expose bulk data:

- No static JSON dumps of entities/events.
- No full SQLite download.
- No full graph export.
- No API endpoint returning more than bounded subgraphs.
- No unauthenticated pagination through the whole corpus.

Required API caps:

- Search: max 30 visible results, max 100 API result rows.
- Subgraph: default 120 nodes, hard cap 300 nodes / 700 edges.
- Expand: max 200 new nodes.
- Random walk: max 20 steps, fanout max 20.
- Detail pages: related rows max 50.

### Layer 1 - Edge Bot Management

Cloudflare target rules:

- Challenge low bot score traffic for `/atlas*` and `/api/v1/stage7/*`.
- Block obvious scrapers by user-agent and ASN where safe.
- Block empty UA for Atlas paths.
- Block datacenter ASNs that show repeated scraping.
- Rate-limit by IP, JA3/JA4 where available, and path.
- Add "Under Attack" / Managed Challenge mode during incidents.

If using DataDome:

- Put DataDome Nginx module or edge integration before Atlas routes.
- Enable report-only mode first, then enforce.
- Log DataDome decision headers into the access log.

If using EdgeOne:

- Enable Web/Bot protection for Atlas host.
- Add managed challenge / CAPTCHA for `/atlas*` and `/api/v1/stage7/*`.
- Enable custom rules and bot behavior library.

### Layer 2 - Origin Lock

When Cloudflare/EdgeOne is active:

- Origin Nginx must only accept proxied edge traffic for `80/443`.
- Direct origin IP access should return `444` or `403`.
- Use Cloudflare Authenticated Origin Pulls or mTLS if available.
- Keep UFW deny for app/model/db ports.
- Keep SSH key auth only.

Do not rely on DNS hiding. The origin IP is already known.

### Layer 3 - Application Human Gate

For `/atlas/graph` and high-value APIs:

- Require a server-issued Atlas session before graph API access.
- Session creation must pass Turnstile or equivalent CAPTCHA challenge.
- Session cookie:
  - `HttpOnly`
  - `Secure`
  - `SameSite=Lax` or stricter
  - short TTL, such as 30-120 minutes
- Bind session to coarse browser evidence:
  - UA hash
  - IP /24 or ASN soft binding
  - challenge timestamp
  - request-rate ledger

Do not store CAPTCHA secrets in repo or docs. Use server environment / secret manager only.

2026-05-21 code checkpoint:

- `GET /api/v1/atlas/session/status` reports whether the gate is required and returns only the public Turnstile site key.
- `POST /api/v1/atlas/session` verifies Turnstile server-side and sets an httpOnly `atlas_session` cookie.
- When `ATLAS_REQUIRE_SESSION=1`, `/api/v1/stage7/*` is fail-closed without a valid cookie.
- Sessions are HMAC-signed, short-lived, and bound to UA hash plus coarse IP prefix.
- Production uses `ATLAS_SQLITE_READONLY=1`, DB mode `root:atlas 640`, and Node bound to `127.0.0.1:8787`.
- The code path was tested with a test-only Turnstile mode and production invalid-token smoke; no production secret is stored in git or docs.

### Layer 4 - API Throttling

Strict default for Atlas paths:

- `/atlas*`: 10-30 requests/min per visitor.
- `/api/v1/stage7/search`: 10 requests/min per visitor.
- `/api/v1/stage7/graph/subgraph`: 20 requests/min per visitor.
- `/api/v1/stage7/graph/expand`: 30 requests/min per visitor.
- `/api/v1/stage7/graph/random-walk`: 5 requests/min per visitor.
- `/api/v1/stage7/articles|entities|events`: require session and lower caps.

Add global emergency caps:

- Per IP: 300 Atlas requests/hour.
- Per session: 800 Atlas requests/day.
- Per query text: detect repeated alphabetic or numeric sweeps.
- Ban or challenge sequential enumeration of IDs.

### Layer 5 - Anti-Enumeration

Do not use predictable browsing as the main UX:

- Prefer search -> selected bounded graph.
- Avoid exposing cursor pagination that can walk all entities/events.
- Do not expose raw row offsets for the graph explorer.
- Use opaque cursors for any list endpoints.
- Add entropy to public node IDs when possible, or keep stable internal IDs hidden behind API mapping.

### Layer 6 - Watermarking And Canary Traps

Add detection mechanisms:

- Canary nodes/edges that are not shown to normal users but appear in bait endpoints.
- Honey endpoints:
  - `/api/v1/stage7/export`
  - `/api/v1/stage7/full-graph`
  - `/atlas.sqlite`
  - `/atlas.json`
- Requests to honey endpoints trigger high-confidence block / fail2ban.
- Insert per-session invisible response watermark in graph payload metadata:
  - response id
  - timestamp bucket
  - session id hash
  - edge sampling order

### Layer 7 - Observability

Minimum logs:

- IP, UA, path, status, bytes, referer.
- Edge bot score / challenge result when available.
- Turnstile pass/fail.
- Atlas session id hash.
- Graph API node/edge count.
- Query text hash, not raw sensitive input if any.

Alerts:

- More than 50 graph requests/min from one IP/session.
- More than 20 unique search queries/min from one IP/session.
- Sequential detail page enumeration.
- Honey endpoint hit.
- Spike in 403/429.
- Large egress change.

## Nginx Atlas Template

The low-cost origin guard is currently active on `149.28.150.224` through `scripts/ops/atlas_low_cost_origin_guard_20260521.sh`. The template below remains the next application-proxy hardening layer to apply only after Cloudflare DNS and Turnstile session issuance are configured.

```nginx
# /etc/nginx/conf.d/atlas_anti_scrape_zones.conf
map $http_user_agent $atlas_bad_bot {
    default 0;
    "" 1;
    ~*(curl|wget|python-requests|aiohttp|Go-http-client|libwww-perl|scrapy|httpx|okhttp|java/) 1;
    ~*(zgrab|CensysInspect|libredtail|Infrawatch|masscan|nuclei|nikto|sqlmap) 1;
    ~*(GPTBot|OAI-SearchBot|ClaudeBot|Bytespider|PetalBot|SemrushBot|AhrefsBot|MJ12bot) 1;
}

limit_req_zone $binary_remote_addr zone=atlas_page:20m rate=20r/m;
limit_req_zone $binary_remote_addr zone=atlas_api:20m rate=30r/m;
limit_req_zone $binary_remote_addr zone=atlas_graph:20m rate=12r/m;
```

```nginx
# include inside the Atlas server block
location = /robots.txt {
    add_header Content-Type text/plain;
    return 200 "User-agent: *\nDisallow: /\n";
}

location ^~ /atlas {
    if ($atlas_bad_bot) { return 403; }
    limit_req zone=atlas_page burst=8 nodelay;
    limit_req_status 429;
    add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
    add_header Cache-Control "private, no-store" always;
    proxy_pass http://127.0.0.1:18888;
}

location ^~ /api/v1/stage7/graph/ {
    if ($atlas_bad_bot) { return 403; }
    limit_req zone=atlas_graph burst=6 nodelay;
    limit_req_status 429;
    add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
    add_header Cache-Control "private, no-store" always;
    proxy_pass http://127.0.0.1:18888;
}

location ^~ /api/v1/stage7/ {
    if ($atlas_bad_bot) { return 403; }
    limit_req zone=atlas_api burst=10 nodelay;
    limit_req_status 429;
    add_header X-Robots-Tag "noindex, nofollow, noarchive, nosnippet, noimageindex" always;
    add_header Cache-Control "private, no-store" always;
    proxy_pass http://127.0.0.1:18888;
}

location ~* ^/(atlas\.sqlite|atlas\.db|atlas\.json|graph\.json|api/v1/stage7/export|api/v1/stage7/full-graph)$ {
    access_log /var/log/nginx/atlas_honeypot.log combined;
    return 403;
}
```

## Cloudflare Rule Sketch

Use Cloudflare dashboard or rules-as-code later. Do not paste API tokens into docs.

### Managed Challenge

Path:

- `/atlas*`
- `/api/v1/stage7/*`

Rule idea:

```text
(http.request.uri.path starts_with "/atlas" or http.request.uri.path starts_with "/api/v1/stage7/")
and cf.bot_management.score le 30
```

Action:

- Managed Challenge

### Block Obvious Scrapers

```text
(http.request.uri.path starts_with "/atlas" or http.request.uri.path starts_with "/api/v1/stage7/")
and lower(http.user_agent) matches "(curl|wget|python-requests|aiohttp|go-http-client|scrapy|zgrab|censys|bytespider|gptbot|claudebot|oai-searchbot)"
```

Action:

- Block

### Rate Limit

Rules:

- `/api/v1/stage7/search`: challenge or block after 60 requests / 10 minutes / IP.
- `/api/v1/stage7/graph/*`: challenge after 80 requests / 10 minutes / IP; block after 150.
- `/atlas*`: challenge after 120 requests / 10 minutes / IP.

### Origin Lock

After Cloudflare is active:

- Nginx should reject non-Cloudflare source IPs.
- Prefer Authenticated Origin Pulls or mTLS.
- Verify direct `curl https://149.28.150.224/atlas` fails while `https://atlas.huaidj.club/atlas` reaches the Cloudflare-proxied edge.

## Application Changes Required Before Public Launch

Add these before `/atlas/graph` is public:

1. Done in code: `atlasAntiScrape`-style gate in `services/weekly_activity_cloudrun/src/server.mjs`.
2. Turnstile verification endpoint:
   - `POST /api/v1/atlas/session`
   - verifies token server-side
   - sets secure Atlas session cookie
3. Graph APIs require Atlas session:
   - `/api/v1/stage7/graph/*`
   - implemented as all `/api/v1/stage7/*` when `ATLAS_REQUIRE_SESSION=1`
4. Add per-session request ledger:
   - done in memory for first app gate; durable local SQLite ledger can be added for VPS abuse forensics
   - Cloudflare/edge logs for CloudRun path
5. Done in code and edge/origin layers: honey endpoints.
6. Tests added for no-session 403, valid-session 200, secret non-exposure, and honey 403. A dedicated 429 burst test remains optional before deployment.

## Deploy Gate

Before public deployment, all must be true:

- Edge provider selected and configured.
- Atlas domain proxied through edge provider.
- Origin direct IP locked.
- CAPTCHA/Turnstile keys configured in server environment.
- Graph API session gate enabled.
- Nginx Atlas limits enabled.
- Honey endpoints enabled.
- Browser smoke passes for a normal user.
- Bot smoke gets 403/429/challenge:
  - empty UA
  - `python-requests`
  - `curl`
  - repeated search loop
  - sequential detail enumeration
- Logs prove bot decisions are recorded.

## Immediate Recommendation

For this server setup:

1. Use Cloudflare Free first, or Cloudflare Pro if the dashboard requires Pro for the desired WAF/rate-limit rule set.
2. Add proxied DNS `atlas.huaidj.club -> 149.28.150.224`.
3. Set Cloudflare SSL/TLS mode to `Full` for the current self-signed origin guard, then later replace it with a Cloudflare Origin Certificate and move to `Full (strict)`.
4. Create a Turnstile widget for `atlas.huaidj.club`; keep the secret out of chat/docs.
5. Add application session middleware and bounded graph API limits before proxying real Atlas data.
6. Keep `149.28.150.224` locked to Cloudflare IP ranges.
7. Keep old `139.180.136.181` for retired huaidj 410 + `/finagent-beta/`, not as Atlas data origin.

For paid escalation:

1. Move to AWS WAF + CloudFront pay-as-you-go if Cloudflare Free/Pro is not strong enough.
2. Add AWS WAF CAPTCHA/Bot Control rules to `/atlas*` and `/api/v1/stage7/*`.
3. Rework origin locking for CloudFront before changing DNS.

For Tencent-native deployment:

1. Put Atlas behind Tencent EdgeOne.
2. Enable Web/Bot protection, CAPTCHA/JavaScript/Managed Challenge, and rate limiting.
3. Use origin locking to prevent bypassing EdgeOne.

## Source Notes

- Cloudflare Turnstile/WAF/Bot Management docs: WAF, Bot Management, and Turnstile are complementary layers; WAF/Bot Management require DNS through Cloudflare, while Turnstile can be used independently.
- Cloudflare Turnstile product page: Turnstile can be embedded without routing traffic through Cloudflare.
- DataDome product/docs: Bot Protect is a real-time bot protection platform and has Nginx integration, but it is not selected for first launch because of cost.
- AWS WAF pricing docs: WAF, Bot Control, and CAPTCHA can be charged pay-as-you-go.
- Tencent Cloud EdgeOne docs: EdgeOne includes DDoS, Web/Bot protection, custom rules, and challenge/CAPTCHA actions.
