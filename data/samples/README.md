# Sample Data — Repository-Level Index

The weekly CloudRun sample data lives at:

**`services/weekly_activity_cloudrun/data/samples/`**

That directory contains 8 fully fake/anonymized sample files:

| File | Description |
|------|-------------|
| `README.md` | Sample data guide |
| `sample_event_minimal.json` | Minimal weekly event |
| `sample_event_multi_dj.json` | Event with DJ lineup |
| `sample_current_index.json` | Simplified current.json (3 items) |
| `sample_manifest.json` | Simplified manifest.json |
| `sample_source_action.json` | Source URL map entry |
| `sample_geo_venue.json` | Venue with geo coordinates |
| `COUNTEREXAMPLE_source_overview.md` | What NOT to do with source-overview |

No real openid, unionid, phone, WeChat URL, qpic URL, or CloudBase envId is present.
All `cloud://` URLs use `fake-env-id` placeholders.
