# Project Map — wechathtmldownload

Generated: 2026-06-10

## Quick Orientation

This is a **China underground/electronic music atlas pipeline** that:
1. Scrapes WeChat public accounts for event info
2. Extracts structured event data via Python+LLM pipeline
3. Serves event data to a WeChat mini-program via CloudRun
4. Powers an Atlas graph UI for DJ/venue/event exploration

## Directory Map

```
wechathtmldownload/
├── apps/
│   └── weekly_activity_miniprogram/    # WeChat mini-program (WXML/WXSS/JS)
│       ├── app.js                      # Entry — config, lifecycle, offline snapshot
│       ├── utils/api.js                # Frontend API layer with 3-tier fallback
│       ├── utils/i18n.js               # Internationalization
│       ├── utils/offlineSnapshot.js    # Offline fallback data
│       ├── pages/index/                # Event list page
│       ├── pages/artist/               # DJ/Artist detail page
│       ├── pages/detail/               # Event detail page
│       └── tests/                      # Node:test based unit tests
│
├── services/
│   └── weekly_activity_cloudrun/       # CloudRun API server
│       ├── src/
│       │   ├── server.mjs              # Main HTTP server (Node native http)
│       │   ├── dataStore.mjs           # JSON-file data store for weekly events
│       │   ├── stage7AtlasStore.mjs    # Atlas in-memory JSON store
│       │   ├── stage7AtlasSqliteStore.mjs # Atlas SQLite store (better-sqlite3)
│       │   ├── miniappAtlasApi.mjs     # Atlas API for mini-program
│       │   ├── deepSeekClient.mjs      # DeepSeek LLM client
│       │   ├── interviewStore.mjs      # DJ interview store
│       │   ├── soundStore.mjs          # Sound/audio store
│       │   ├── atlasPage.mjs           # Atlas HTML page renderer
│       │   ├── atlasDetailPage.mjs     # DJ detail page renderer
│       │   ├── atlasGraphPage.mjs      # Graph visualization page
│       │   ├── atlasIdentityPage.mjs   # Identity review page
│       │   ├── atlasLocalPage.mjs      # Local data page
│       │   ├── previewPage.mjs         # Event preview page
│       │   └── cloudbaserc.json        # CloudBase deployment config
│       ├── data/
│       │   ├── current_release/        # Production data (171 events)
│       │   └── samples/                # Fake sample data for AI handover
│       └── .env                        # DEEPSEEK_API_KEY (DO NOT COMMIT)
│
├── tools/
│   └── stage7_rewrite/                 # Python pipeline (874 scripts)
│       ├── scripts/                    # Extraction, enrichment, pipeline scripts
│       ├── registries/                 # Venue & account seed registries
│       ├── reports/                    # Atlas report-only artifacts
│       ├── SSOT.md                     # Stage7 single source of truth
│       └── LONGRUN_STATE.md            # Longrun execution state
│
├── desktop/                            # Electron PCUI operator workbench
│
├── src/                                # TypeScript source (84 files)
│   ├── cli.ts                          # CLI entry point
│   └── ...                             # WeChat archive, OCR, pipeline modules
│
├── docs/                               # Project documentation
│   ├── 00_AI_README.md                 # AI onboarding guide
│   ├── 01_PROJECT_MAP.md               # This file
│   ├── 02_PRD.md                       # Product requirements
│   ├── 03_ARCHITECTURE.md              # System architecture
│   ├── 03_API_CONTRACTS_WEEKLY.md      # Weekly API contracts
│   ├── 04_DATA_PACKAGE_CONTRACT_WEEKLY.md # Data field contracts
│   ├── 06_RUNTIME_STATE_TRUTH_TABLE.md # Runtime state matrix
│   ├── 07_DATABASE_SCHEMA.md           # Database schema docs
│   ├── 08_DATA_PIPELINE.md             # Pipeline flow docs
│   ├── 09_LOCAL_DEV_SOP.md             # Local dev setup guide
│   ├── 10_DEPLOYMENT_SOP.md            # Deployment guide
│   ├── 11_TROUBLESHOOTING.md           # Common issues & fixes
│   └── adr/                            # Architecture Decision Records
│
├── AGENTS.md                           # Agent rules and boundaries
├── README.md                           # Human-readable project intro
├── package.json                        # Node project config (wechat-ingest)
├── tsconfig.json                       # TypeScript config
└── mkdocs.yml                          # MkDocs documentation config
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| API Server | Node.js (native http, ESM) | Weekly event + Atlas API |
| Data Store | JSON files on disk | Weekly event data |
| Atlas DB | SQLite (better-sqlite3) | DJ/venue/event graph |
| Pipeline | Python 3 + DeepSeek LLM | Extraction & enrichment |
| Mini-program | WeChat WXML/WXSS/JS | Mobile frontend |
| Desktop | Electron | Operator workbench |
| CLI | TypeScript (oclif-style) | Archive & pipeline commands |
| Cloud | Tencent CloudBase + CloudRun | Hosting & deployment |
| Auth | Cloudflare Turnstile | Atlas session protection |

## Key Personas

| Persona | Uses | Access |
|---------|------|--------|
| End user | WeChat mini-program | Public (no auth) |
| DJ/venue owner | Atlas profile pages | Turnstile-protected |
| Operator | Electron desktop + CLI | Local only |
| AI agent | Docs + source code | Full read, bounded write |
