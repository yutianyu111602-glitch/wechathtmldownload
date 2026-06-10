# Sample Data — Fake / Anonymized

All data in this directory is **entirely synthetic**. No real openid, unionid, phone, WeChat URL,
qpic URL, CloudBase envId, real address, or real person/DJ/venue is represented.

Purpose: allow the next AI or developer to understand the data shape without accessing real data.

## Files

| File | Description |
|------|-------------|
| `sample_event_minimal.json` | Minimal weekly event (few fields filled) |
| `sample_event_full.json` | Full weekly event (all common fields) |
| `sample_event_multi_dj.json` | Event with DJ lineup and artist profiles |
| `sample_current_index.json` | Simplified `current.json` index (3 items) |
| `sample_manifest.json` | Simplified `manifest.json` |
| `sample_source_action.json` | Source action / URL map entry |
| `sample_geo_venue.json` | Venue with geo coordinates |
| `COUNTEREXAMPLE_source_overview.md` | Counterexample: what NOT to do with source-overview |

## Schema version

All samples use `weekly_event_published.v1` / `weekly_activity_miniprogram_detail.v1` /
`weekly_activity_miniprogram_api.v1` schema versions matching current production data.
