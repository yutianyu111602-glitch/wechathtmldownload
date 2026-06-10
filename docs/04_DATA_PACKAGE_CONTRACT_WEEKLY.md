# Data Package Contract — Weekly Activity

Generated: 2026-06-10
Source: `services/weekly_activity_cloudrun/data/current_release/`

## Package Structure

```
current_release/
├── manifest.json              # Pack metadata and generation info
├── current.json               # All events (index view)
├── SUMMARY.md                 # Human-readable summary
├── by-city/
│   ├── index.json             # City index with counts
│   ├── shanghai.json          # Events for Shanghai
│   ├── beijing.json           # Events for Beijing
│   └── ...                    # 25 cities total
├── by-date/
│   ├── index.json             # Date index with counts
│   ├── 2026-06-02.json        # Events on this date
│   └── ...                    # 13 dates total
├── by-id/
│   ├── hakka_baru3a8ec6d516a7e2db3a.json  # Single event detail
│   └── ...                                # 155 items total
├── llm/
│   ├── enrichment_index.json  # LLM enrichment index
│   ├── enrichments/           # Per-event LLM enrichment
│   ├── materialize_report.json
│   └── weekly_summary.json
├── source_actions/
│   └── source_url_map.json    # Source article URL mapping
├── cross_db_merge_map.json    # Cross-DB entity merge map
├── geocode_apply_report.json  # Geocode application report
├── weekly_entity_snapshot.json # Weekly entity snapshot
└── repair_report.json         # Data repair report
```

## Field-Level Contract: Event Item (current.json / by-city / by-date)

| Field | Type | Required | Description | Example |
|-------|------|----------|-------------|---------|
| `id` | string | YES | Unique event identifier | `hakka_bar:8ec6d516a7e2db3a` |
| `event_id` | string | YES | Same as id | `hakka_bar:8ec6d516a7e2db3a` |
| `account` | string | YES | Source account slug | `hakka_bar` |
| `account_key` | string | YES | Normalized account key | `hakka_bar` |
| `city` | string[] | YES | City labels | `["成都"]` |
| `city_key` | string | YES | City slug for URL routing | `chengdu` |
| `city_name` | string | YES | Display city name | `成都` |
| `content_type` | string | YES | Always `"event"` | `"event"` |
| `cover_url` | string | NO | CloudBase poster URL | `cloud://...` |
| `event_date_start` | string | YES | ISO date start | `"2026-06-02"` |
| `event_date_end` | string | NO | ISO date end (multi-day) | `"2026-06-04"` |
| `title` | string | YES | Full title with date prefix | `"06.02 今晚 |「OPEN DECKS」"` |
| `title_display` | string | YES | Clean display title | `"「OPEN DECKS」"` |
| `venue_name` | string | YES | Venue display name | `"hakka_bar"` |
| `venue_id` | string | YES | Venue unique ID | `"hakka_bar_chengdu"` |
| `detail_path` | string | YES | Relative path to detail JSON | `"by-id/hakka_baru3a8ec6d516a7e2db3a.json"` |
| `publish_status` | string | YES | `"published"` or `"blocked"` | `"published"` |
| `quality_status` | string | YES | `"READY"` or quality issue | `"READY"` |
| `schema_version` | string | YES | Event schema version | `"weekly_event_published.v1"` |
| `source_action` | object | YES | Source article link info | `{ available, label, type, url_hash }` |
| `poster_file_id` | string | NO | CloudBase file ID for poster | `cloud://...` |
| `poster_source` | string | NO | Poster storage source | `"cloudbase_storage"` |
| `quality_flags` | string[] | NO | Quality issues | `["missing_time"]` |
| `geo_lat` | number | NO | GCJ-02 latitude | `30.624273` |
| `geo_lng` | number | NO | GCJ-02 longitude | `104.076219` |
| `lineup` | object[] | NO | DJ lineup with time slots | `[{ name, time_slot }]` |
| `price` | object[] | NO | Price tiers | `[{ label, amount }]` |
| `genres` | string[] | NO | Music genres | `["techno", "house"]` |

## Field-Level Contract: Event Detail (by-id/*.json)

Wraps the index item with additional fields:

| Extra Field | Type | Description |
|-------------|------|-------------|
| `schema_version` | string | `"weekly_activity_miniprogram_detail.v1"` |
| `generated_at` | string | Pack generation timestamp |
| `item` | object | Full event object (all fields from index + extras below) |
| `item.address` | string | Venue address |
| `item.address_full` | string | Full venue address |
| `item.description_original_lines` | string[] | Original description from source |
| `item.evidence` | string[] | Source text evidence lines |
| `item.artist_profiles` | object[] | DJ profile details with bios |
| `item.dj_bio_lines` | string[] | DJ biography text |
| `item.source_article` | object | Source article metadata |
| `item.poster_cloud_path` | string | CloudBase storage path |
| `item.poster_migrated_at` | string | Poster migration timestamp |
| `item.poster_storage` | string | Storage backend (`"cloudbase"`) |
| `item.place_fields_locked` | boolean | Whether venue fields are locked |

## Field-Level Contract: manifest.json

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | `"weekly_activity_miniprogram_api.v1"` |
| `generated_at` | string | ISO timestamp with timezone |
| `item_count` | int | Total published items |
| `window_start` | string | ISO date — window start |
| `window_end` | string | ISO date — window end |
| `filtered_counts` | object | Items filtered out by reason |
| `venue_registry_count` | int | Known venues |
| `account_registry_count` | int | Known accounts |
| `city_route_count` | int | Number of city routes |
| `date_route_count` | int | Number of date routes |
| `routes` | object | Route path mapping |
| `repair_report` | object | Data repair summary |

## Invariants

1. Every item in `current.json` must have a corresponding file in `by-id/`
2. Every city in `by-city/index.json` must have a `by-city/{city_key}.json` file
3. Every date in `by-date/index.json` must have a `by-date/{date}.json` file
4. `manifest.item_count` must equal `len(current.json.items)`
5. All `event_date_start` values must fall within `[manifest.window_start, manifest.window_end]`
6. `poster_file_id` starting with `cloud://` implies `poster_source = "cloudbase_storage"`
7. `geo_coord_system` is always `"GCJ-02"` (China coordinate system)
8. `quality_status = "READY"` is required for `publish_status = "published"`
