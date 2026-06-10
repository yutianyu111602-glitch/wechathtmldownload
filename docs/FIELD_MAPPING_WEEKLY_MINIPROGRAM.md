# Weekly Activity Mini Program — Unified Field Mapping

> DB/Incremental Package → CloudRun API → Frontend `compactItem` → WXML Display

## 1. Data Pipeline Overview

```
Atlas SQLite (source/raw + serving)
  ↓ stage7 export
current.json (incremental package, 171 items)
  ↓ dataStore.getCurrent() → withListCompatItem()
CloudRun API /api/v1/weekly/current (38 filtered items)
  ↓ api.js fetch → canonicalizeItemFields() → compactItem()
Frontend viewItems (26 display items)
```

## 2. Incremental Package Fields (current.json raw item)

Source: `services/weekly_activity_cloudrun/data/current_release/current.json`

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `id` / `event_id` / `article_id` | string | `hakka_bar:8ec6d516a7e2db3a` | Primary key |
| `account` / `account_key` / `promoter` | string | `hakka_bar` | Source WeChat account |
| `title` | string | `06.02 今晚 \|「OPEN DECKS」` | Raw title |
| `title_display` / `display_title` | string | `「OPEN DECKS」` | Cleaned display title |
| `title_original` | string | Same as title | Unprocessed title |
| `city` | string[] | `["成都"]` | City labels |
| `city_key` | string | `chengdu` | City slug |
| `city_keys` | string[] | `["chengdu"]` | Multi-city slugs |
| `city_name` | string | `成都` | Primary city name |
| `event_date_start` | string | `2026-06-02` | ISO start date |
| `event_date_end` | string | `2026-06-02` | ISO end date |
| `event_date_iso_guess` | string | `2026-06-02` | Guessed date |
| `event_date_iso_guesses` | string[] | `["2026-06-02"]` | All date guesses |
| `event_date_text` | string[] | `["2026-06-02"]` | Raw date text |
| `event_time_text` | string | `""` | Time text |
| `time_start` / `time_end` | string | `""` | Time range |
| `post_date` | string | `2026-06-02` | Article publish date |
| `cover_url` / `cover_image_url` / `coverUrl` | string | `cloud://...` | Poster image |
| `poster_file_id` / `posterFileId` | string | `cloud://...` | Cloud file ID |
| `poster_url` / `posterUrl` / `flyer_url` | string | `cloud://...` | Poster URL variants |
| `poster_source` / `posterStorage` | string | `cloudbase_storage` / `cloudbase` | Storage type |
| `venue` | string[] | `[]` | Venue names |
| `venue_name` | string | `hakka_bar` | Primary venue |
| `venue_id` | string | `hakka_bar_chengdu` | Venue slug |
| `address` / `address_full` | string | Full address | |
| `address_source` | string | `venue_registry_verified` | Address provenance |
| `venue_lat` / `venue_lng` | number | 30.624, 104.076 | GCJ-02 coords |
| `geo_lat` / `geo_lng` | number | Same | Alt coord fields |
| `lineup` / `lineup_artists` | array | `[]` | Artist names |
| `music_styles` / `genres` / `style_tags` | array | `[]` | Style tags |
| `price` / `price_text` / `ticketing_text` | mixed | `[]` / `""` | Price info |
| `description_original_lines` | string[] | Lines | Description |
| `quality_status` | string | `READY` | Publish gate |
| `quality_flags` | string[] | `["missing_time"]` | Quality markers |
| `publish_status` | string | `published` | |
| `content_type` | string | `event` / `calendar_preview` | |
| `is_calendar_preview` | boolean | false | |
| `source_action` | object | `{available, url_hash, type}` | Source link |
| `source_article` | object | `{url_hash, account_name, published_at}` | Article ref |
| `sourceHash` / `source_hash` | string | hash | Dedupe key component |
| `schema_version` | string | `weekly_event_published.v1` | Data schema |
| `dedupe_key` | string | `成都\|hakkabar\|...` | Deduplication |

## 3. API Response Fields (CloudRun /api/v1/weekly/current)

Source: `dataStore.mjs` → `withListCompatItem()` → `LIST_COMPAT_FIELDS`

The API filters raw items by:
- `quality_status === "READY"` 
- `event_date_start >= currentThreshold` (or date filter match)
- Optional `cityKey` filter
- Deduplication via `dedupeItems()`

Then applies `withListCompatItem()` which:
1. Runs `withClubProfile()` to attach venue profile data
2. Keeps only `LIST_COMPAT_FIELDS` (non-null, non-empty)
3. Compacts `evidence`, `description_original_lines` (limit 2-3 items, 160 chars)
4. Compacts `description`, `digest`, `summary` (260 chars)
5. Picks `source_action: {available, url_hash}` and `source_article: {url_hash, title, account_name, published_at}`

API response structure:
```json
{
  "schemaVersion": "weekly_activity_api.current_response.v1",
  "generatedAt": "2026-06-08T20:41:45+08:00",
  "filters": { "cityKey": null, "date": null, "lookbackDays": 2 },
  "page": { "limit": 50, "cursor": "0", "nextCursor": null, "total": 38 },
  "items": [...]
}
```

## 4. Frontend compactItem Output Fields

Source: `utils/format.js` → `compactItem()`

Each API item passes through:
1. `canonicalizeItemFields()` — merges camelCase/snake_case variants
2. `compactItem()` — computes display fields

| Output Field | Source | Type | Display Use |
|-------------|--------|------|-------------|
| `id` | raw | string | Item key |
| `sourceHash` | `source_action.url_hash` \| `source_hash` | string | Navigation |
| `coverUrl` | `poster_url` \| `cover_url` (via `posterUrl()`) | string | Image src |
| `posterFileId` | `poster_file_id` (via `posterFileId()`) | string | Cloud preview |
| `posterTempUrl` | runtime | string | Temp URL cache |
| `displayTitle` | `displayTitle()` → `title_display` \| `title` | string | Card title |
| `dateLabel` | `event_date_start` \| `event_date_iso_guess` | string | Date display |
| `dateRangeLabel` | `start - end` | string | Date range |
| `dateRangeCompact` | `06.02-06.03` format | string | Pill date |
| `dateCompact` | same as dateRangeCompact | string | Alt compact |
| `event_date_start` | raw | string | Filter key |
| `event_date_end` | raw | string | Filter key |
| `event_date_iso_guesses` | raw | string[] | Date scope |
| `post_date` | raw | string | Sort key |
| `weekdayLabel` | derived from date | string | "Thu" |
| `isCalendarPreview` | `quality_flags` \| `content_type` | boolean | Overview marker |
| `isSourceOverview` | source overview detection | boolean | |
| `calendarPreviewLabel` | `"活动一览"` if preview | string | |
| `cardLocationLabel` | city/venue/promoter | string | Card location |
| `city_key` / `city_keys` | raw | string | Filter key |
| `cityLabel` | `city[0]` \| `city_key` | string | Display |
| `listLocationLabel` | derived | string | |
| `venueLabel` | `venue_name` \| `venue[0]` | string | |
| `addressLabel` | verified address \| `address` | string | |
| `hasStyle` | `musicStyles.length > 0` | boolean | UI toggle |
| `styleLabel` | `joinList(musicStyles)` | string | Style text |
| `hasLineup` | `cleanLineup.length > 0` | boolean | UI toggle |
| `lineupLabel` | `joinList(cleanedLineup)` | string | Lineup text |
| `lineupItems` | `cleanLineup()` result | array | Artist list |
| `hasLineupHint` | raw lineup but none cleaned | boolean | Show hint |
| `lineupHint` | `"点击海报跳转公众号原文查看"` | string | Fallback hint |
| `hasAddress` | `Boolean(addressLabel)` | boolean | |
| `hasDescription` | `descriptionLines.length > 0` | boolean | |
| `hasPrice` | `priceItems.length > 0` | boolean | |
| `interestLabel` | `24 + (seed % 78)` | string | Fake interest count |

## 5. Key Transformations

### Date Display Chain
```
event_date_start → dateRangeForItem() → dateLabel → compactDate() → "06.02"
event_date_start + event_date_end → dateRangeLabel → "2026-06-02 - 2026-06-03"
compactDateRange() → dateRangeCompact → "06.02-06.03"
weekdayLabel() → "Thu"
```

### Title Display Chain
```
title_original → displayTitle() → strips date prefix, emoji, stop tokens → displayTitle
calendar_preview items → originalArticleTitle() instead
```

### Poster URL Chain
```
poster_file_id / cover_file_id → posterFileId()
poster_url / cover_url / flyer_url → posterUrl() → coverUrl
cloud://... → cloudPosterUrls.js → wx.getTempFileURL() → posterTempUrl
```

### Location Chain
```
city[0] → cityLabel
venue_name / venue[0] → venueLabel
verifiedAddress / address → addressLabel
cityLabel + venueLabel → cardLocationLabel (Shanghai shows venue first)
venue_name + address + coords → mapLocationForItem()
```

### Source/Navigation Chain
```
source_action.url_hash → sourceHash → hasSource → tap to open article
source_article → {url_hash, title, account_name, published_at}
```

## 6. Filter Field Mapping

| Filter | Frontend Param | API Param | Source Field |
|--------|---------------|-----------|-------------|
| City | `selectedCity` | `cityKey` | `item.city_key` / `item.city_keys` |
| Date | `selectedDate` | `date` | `item.event_date_start` via `itemMatchesDate()` |

## 7. Data Count Summary (2026-06-08 snapshot)

| Stage | Count | Filter |
|-------|-------|--------|
| current.json raw | 171 | — |
| CloudRun API (no filter) | 38 | `quality_status=READY` + current/future + dedupe |
| Static CDN current.json | 167 | Unfiltered (includes past) |
| Frontend viewItems | 26 | After client-side `compactItem` + `dedupeItems` |
| Offline snapshot | ~40 | Hardcoded in `offlineSnapshot.js` |
