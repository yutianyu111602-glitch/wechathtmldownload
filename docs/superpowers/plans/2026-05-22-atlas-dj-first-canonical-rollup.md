# Atlas DJ-First Canonical Rollup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first safe local canary that turns raw Atlas SQLite rows into DJ-first canonical identities and relation rollups without mutating the source database or exposing bulk data.

**Architecture:** Add a report-only Python builder that reads `atlas.sqlite`, classifies a bounded seed set into canonical DJ/venue/label/noise identities, derives event/co-performance/venue rollups, writes a small sidecar SQLite + JSON/Markdown report under `reports/`, and proves behavior with a fixture-based pytest suite. This is the first implementation step for `docs/ATLAS_DJ_FIRST_FULL_DESIGN_AND_PLAN_20260522.md`.

**Tech Stack:** Python 3, stdlib `sqlite3`, JSON reports, pytest, existing Stage7 report-only script patterns.

## 2026-05-22 Execution Update

The plan has moved past the first canary. The current DJ-first implementation seam is:

- `tools/stage7_rewrite/scripts/build_atlas_dj_first_canary.py` — canonical/noise/radio seed canary.
- `tools/stage7_rewrite/config/atlas_curated_entity_rules_20260522.json` — curated public classification rules.
- `tools/stage7_rewrite/scripts/build_atlas_dj_history_rollup.py` — full DJ historical performance + relationship rollup builder.
- `reports/atlas_dj_history_rollup_20260522/summary.md` — 5-DJ proof run.
- `reports/atlas_dj_history_rollup_top25_20260522/summary.md` — top-25 batch proof run.

The product rule is now stricter: DJ is the primary economic subject. For each DJ, materialize all historical performance records before graph visualization. Relationships are derived from those event facts first; same-article context remains weak evidence only.

Latest real sidecar proof:

- Focus run: `5` DJs, `270` DJ-event facts, `322` collaborator rollups, `48` venue rollups.
- Top-25 batch: `25` DJs, `22,521` DJ-event facts, `9,401` collaborator rollups, `1,157` venue rollups.
- All outputs are report-only sidecars; no source SQLite, Neo4j, Qdrant, mem0, CloudRun, model, paid API, or production write occurred.

---

## File Structure

- Create: `tools/stage7_rewrite/scripts/build_atlas_dj_first_canary.py`
  - Responsibility: read source `atlas.sqlite`, classify canonical music identities including radio/media channels, derive DJ relation rollups, write sidecar outputs only.
- Create: `tools/stage7_rewrite/tests/test_build_atlas_dj_first_canary.py`
  - Responsibility: fixture SQLite tests for classification, noise rejection, source-scoped IDs, event relation rollups, and safety flags.
- Modify: `docs/current-runtime.md`
  - Responsibility: record the design/plan/canary execution status and boundaries.
- Modify: `docs/DOCUMENTATION_INDEX.md`
  - Responsibility: already links the DJ-first authority document; add canary report after implementation if generated.

## Task 1: Fixture Tests For DJ-First Canary

**Files:**

- Create: `tools/stage7_rewrite/tests/test_build_atlas_dj_first_canary.py`

- [ ] **Step 1: Write fixture setup and classification test**

```python
import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_atlas_dj_first_canary.py"
spec = importlib.util.spec_from_file_location("build_atlas_dj_first_canary", SCRIPT)
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE articles (
          article_uid TEXT PRIMARY KEY,
          title TEXT,
          source_account TEXT,
          publish_time TEXT,
          city_label TEXT
        );
        CREATE TABLE entities (
          eid TEXT,
          name TEXT,
          type TEXT,
          city TEXT,
          source_article_uid TEXT,
          confidence REAL,
          aliases_json TEXT,
          bio TEXT,
          evidence_quote TEXT,
          vector_text_preview TEXT,
          raw_json TEXT
        );
        CREATE TABLE events (
          evid TEXT,
          name TEXT,
          place TEXT,
          city TEXT,
          time_iso TEXT,
          time_text TEXT,
          source_article_uid TEXT,
          confidence REAL,
          participants_json TEXT,
          organizers_json TEXT,
          vector_text_preview TEXT,
          raw_json TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def test_classifies_dj_venue_label_and_noise(tmp_path):
    db = tmp_path / "atlas.sqlite"
    make_db(db)
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO articles VALUES (?, ?, ?, ?, ?)",
        [
            ("art1", "ALL night", "All俱乐部", "2024-01-01", "上海"),
            ("art2", "OIL show", "OIL油", "2024-02-01", "深圳"),
        ],
    )
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("local:e1", "MaFoL", "person", "", "art1", 0.98, "[]", "", "", "", "{}"),
            ("local:e2", "OIL", "organization", "深圳", "art2", 0.95, "[]", "", "", "", "{}"),
            ("local:e3", "SHCR", "organization", "", "art1", 0.90, "[]", "", "", "", "{}"),
            ("local:e4", "葡萄酒", "product", "", "art1", 0.90, "[]", "", "", "", "{}"),
        ],
    )
    conn.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("local:ev1", "ALL night", "ALL", "上海", "2024-01-01", "", "art1", 0.9, '["MaFoL", "DaRou"]', '["SHCR"]', "", "{}"),
            ("local:ev2", "OIL show", "OIL", "深圳", "2024-02-01", "", "art2", 0.9, '["MaFoL", "GuangYu"]', '["OIL油"]', "", "{}"),
        ],
    )
    conn.commit()
    conn.close()

    result = canary.build_canary(db, tmp_path / "out", seeds=["MaFoL", "OIL", "SHCR", "葡萄酒"], max_sources=100)

    assert result["summary"]["safety"]["source_sqlite_write_executed"] is False
    assert result["summary"]["canonical_counts"]["dj"] == 1
    assert result["summary"]["canonical_counts"]["venue"] == 1
    assert result["summary"]["canonical_counts"]["label_org"] == 1
    assert result["summary"]["canonical_counts"]["radio"] == 1
    assert result["summary"]["canonical_counts"]["noise"] == 1
```

- [ ] **Step 2: Write relation rollup assertions**

```python
def test_builds_dj_collaborator_and_venue_rollups(tmp_path):
    db = tmp_path / "atlas.sqlite"
    make_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO articles VALUES (?, ?, ?, ?, ?)", ("art1", "ALL night", "All俱乐部", "2024-01-01", "上海"))
    conn.executemany(
        "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("local:e1", "MaFoL", "person", "", "art1", 0.98, "[]", "", "", "", "{}"),
            ("local:e2", "DaRou", "person", "", "art1", 0.96, "[]", "", "", "", "{}"),
        ],
    )
    conn.execute(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("local:ev1", "ALL night", "ALL", "上海", "2024-01-01", "", "art1", 0.9, '["MaFoL", "DaRou"]', "[]", "", "{}"),
    )
    conn.commit()
    conn.close()

    result = canary.build_canary(db, tmp_path / "out", seeds=["MaFoL"], max_sources=100)

    collabs = result["relations"]["dj_collaborators"]
    venues = result["relations"]["dj_venues"]
    assert collabs[0]["src_name"] == "MaFoL"
    assert collabs[0]["dst_name"] == "DaRou"
    assert collabs[0]["same_event_count"] == 1
    assert venues[0]["venue_name"] == "ALL"
    assert venues[0]["played_event_count"] == 1
```

- [ ] **Step 3: Run test to verify it fails before implementation**

Run:

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_dj_first_canary.py -q
```

Expected: FAIL because `build_atlas_dj_first_canary.py` does not exist yet.

## Task 2: Implement The Report-Only Canary Builder

**Files:**

- Create: `tools/stage7_rewrite/scripts/build_atlas_dj_first_canary.py`

- [ ] **Step 1: Add module header, constants, and safe writers**

Implement:

```python
#!/usr/bin/env python3
"""Build a report-only DJ-first canonical Atlas canary.

Reads a local Atlas SQLite database, derives bounded canonical music identities
and relation rollups, and writes sidecar reports only. It never writes to the
source SQLite database, Neo4j, Qdrant, mem0, CloudRun, or production state.
"""
```

The module must define:

- `DEFAULT_DB`
- `DEFAULT_OUT_DIR`
- `DEFAULT_SEEDS`
- `NOISE_TERMS`
- `VENUE_TERMS`
- `LABEL_TERMS`
- `MUSIC_TERMS`
- `now_iso()`
- `norm_text(value)`
- `stable_id(prefix, *parts)`
- `write_json(path, payload)`
- `write_jsonl(path, rows)`

- [ ] **Step 2: Implement robust JSON parsing and source-scoped IDs**

Add:

```python
def parse_json_list(value):
    if isinstance(value, list):
        return [norm_text(item) for item in value if norm_text(item)]
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [norm_text(item) for item in parsed if norm_text(item)]
    return []


def source_scoped_id(source_article_uid, local_id, fallback):
    source = norm_text(source_article_uid)
    local = norm_text(local_id)
    if source and local:
        return f"{source}#{local}"
    if source:
        return f"{source}#{fallback}"
    return fallback
```

- [ ] **Step 3: Implement classification**

Rules:

- noise if lowercase text contains `葡萄酒`, `酒单`, `菜单`, `咖啡`, `餐厅`, `招聘`, `瑜伽`, `酒店推荐`, `课程表`, `白葡萄酒`, `红葡萄酒`, or raw type is `product`;
- DJ if raw type is `person` and not noise;
- venue if text/source account/place contains `club`, `bar`, `live`, `俱乐部`, `dada`, `oil`, `tag`, `all`, `bo live`, `zhaodai`, `venue`, `场地`;
- label/org if raw type is `organization`, `brand`, or text contains `厂牌`, `crew`, `records`, `collective`, `shcr`;
- otherwise `context`.

- [ ] **Step 4: Implement data loading**

Use parameterized SQLite queries only:

- load seed entity mentions by exact `LOWER(name)=LOWER(?)`;
- load all events for the seed source articles;
- load article metadata for evidence samples;
- parse event participants and organizers;
- infer venues from event `place`.

Use a bounded `max_sources` window to avoid accidental full-corpus scans in the canary.

- [ ] **Step 5: Implement rollups**

Generate:

- `canonical_identities`
- `dj_collaborators`
- `dj_venues`
- `label_edges`
- `noise_rows`
- `evidence_refs`

Each row must contain `write_status="report_only"` and sampled source evidence.

- [ ] **Step 6: Write outputs**

Output directory contents:

- `atlas_dj_first_canary.sqlite`
- `canonical_identities.jsonl`
- `dj_collaborators.jsonl`
- `dj_venues.jsonl`
- `evidence_refs.jsonl`
- `summary.json`
- `summary.md`

The sidecar SQLite contains only canary rows under the output directory. It must not modify the source DB.

- [ ] **Step 7: Add CLI**

CLI:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_dj_first_canary.py --db tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite --out-dir reports\atlas_dj_first_canary_20260522 --seed MaFoL --seed OIL --seed DADA昆明
```

JSON stdout:

```json
{"ok": true, "summary": "reports/atlas_dj_first_canary_20260522/summary.json"}
```

## Task 3: Verify The Canary On Fixtures And Real Golden Seeds

**Files:**

- Test: `tools/stage7_rewrite/tests/test_build_atlas_dj_first_canary.py`
- Run script: `tools/stage7_rewrite/scripts/build_atlas_dj_first_canary.py`

- [ ] **Step 1: Run fixture tests**

Run:

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_dj_first_canary.py -q
```

Expected: PASS.

- [ ] **Step 2: Run syntax check**

Run:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_atlas_dj_first_canary.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run real local canary**

Run:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_dj_first_canary.py --db tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite --out-dir reports\atlas_dj_first_canary_20260522 --max-sources 2000 --seed MaFoL --seed OIL --seed DADA昆明 --seed "BO LIVE" --seed TAG --seed "DONG 洞"
```

Expected:

- `summary.json` exists;
- `summary.safety.source_sqlite_write_executed=false`;
- at least one DJ identity;
- at least one venue identity;
- at least one DJ collaborator or venue rollup for a seeded DJ;
- noise terms are counted under noise/context, not promoted to DJ.

## Task 4: Update Runtime And Index Evidence

**Files:**

- Modify: `docs/current-runtime.md`
- Modify: `docs/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Add current-runtime section**

Add a new top section with:

- design authority path;
- plan path;
- script path;
- test command/result;
- real canary command/result;
- report output path;
- explicit no raw DB mutation / no graph write / no deploy / no secret read boundary.

- [ ] **Step 2: Add documentation-index evidence line**

Add an `ACTIVE_EVIDENCE` line for `reports/atlas_dj_first_canary_20260522/summary.md` once generated.

## Task 5: Self-Review And Decide Next Slice

**Files:**

- Read: `docs/ATLAS_DJ_FIRST_FULL_DESIGN_AND_PLAN_20260522.md`
- Read: `reports/atlas_dj_first_canary_20260522/summary.md`

- [ ] **Step 1: Check plan coverage**

Confirm the implemented canary covers:

- canonical DJ;
- canonical venue;
- label/org classification;
- radio/media classification for SHCR / BYYB / baihui / CDCR-style electronic music channels;
- noise rejection;
- source-scoped mention IDs;
- same-event DJ collaborator rollups;
- DJ venue rollups;
- evidence samples;
- read-only safety flags.

- [ ] **Step 2: Decide the next implementation slice**

If canary passes, next slice is:

```text
build_atlas_canonical_music_entities.py -> atlas_canonical.sqlite
```

If canary fails on real data due missing source/event evidence, next slice is:

```text
improve event participant/name matching before canonical full build
```

## Execution Mode For This Thread

The user explicitly said: `先计划 后执行 自动迭代 我去睡了`.

Therefore, after this plan is written, continue with inline execution in bounded local slices. Do not wait for another approval unless the next action would read secrets, mutate production, deploy, call paid APIs, run broad D: scans, or write to production graph/vector databases.
