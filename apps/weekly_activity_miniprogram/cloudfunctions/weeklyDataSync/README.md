# weeklyDataSync

CloudBase Database hot-data function for the HUAIDJ Weekly mini-program.

Collections:
- `weekly_current`: one `current` document with the complete current weekly item set.
- `weekly_events`: one document per event, keyed by a stable hash of the event id.
- `weekly_cities`: one document per city.
- `weekly_ai_summary`: one `materialized-summary` document.
- `weekly_config`: sync metadata and route metadata.

Actions:
- `sync`: fetches current weekly data from CloudRun and writes hot data into CloudBase Database.
- `read`: reads hot data and returns API-shaped payloads used by the mini-program.

Environment:
- `WEEKLY_DATA_SYNC_BASE_URL`: optional CloudRun source base URL. Defaults to the public `weekly-api` CloudRun URL.
