# COUNTEREXAMPLE: Source-Overview Usage

## What NOT to do

The `source-overview` counter in `current.json` is a **derived aggregation**, not a primary
data source. The following patterns are incorrect:

### Wrong: Treating source-overview as real-time truth

```
source_overview.total_events = 171   <-- This is the count AT generation time
```

This value becomes stale the moment a new event is published or an old one expires.
The mini-program should NEVER cache this number as a static truth.

### Wrong: Using source-overview to decide data freshness

```
if (source_overview.generated_at < Date.now() - 86400000) {
  // "data is stale, show error"
}
```

The `generated_at` reflects the **pipeline run time**, not the data freshness of individual
events. An event from 2026-06-05 in a pack generated 2026-06-10 is still valid for
2026-06-05.

### Correct: Use per-event `event_date_start` for display filtering

The mini-program should filter by `event_date_start` relative to today, not rely on
the pack-level overview count or generated_at timestamp for display logic.

### Correct: Use `manifest.window_start` / `window_end` for date range

The manifest defines the valid date window. Events outside this window were filtered
out during pack generation and should not be expected in the data.
