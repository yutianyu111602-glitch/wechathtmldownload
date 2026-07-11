#!/usr/bin/env python3
"""Read-only alignment audit for the weekly mini-program production pipeline.

This audit is intentionally report-only. It checks frontend config, stale-cache
guards, CloudRun packaged data, CloudBase DB sync entrypoints, Sanji/Hermes
static pipeline wiring, and the public API default-current window. It does not
sync CloudBase DB, deploy CloudRun, upload the mini-program, submit review, or
read secrets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MINIAPP_DIR = REPO_ROOT / "apps" / "weekly_activity_miniprogram"
DEFAULT_CLOUDRUN_DIR = REPO_ROOT / "services" / "weekly_activity_cloudrun"
DEFAULT_RELEASE_DIR = DEFAULT_CLOUDRUN_DIR / "data" / "current_release"
DEFAULT_PUBLIC_BASE_URL = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com"
DEFAULT_OUT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_miniprogram_all_pipelines_audit_20260705.json"

EXPECTED_ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
EXPECTED_SERVICE = "weekly-api"
EXPECTED_PUBLIC_BASE_URL = DEFAULT_PUBLIC_BASE_URL
EXPECTED_DB_FUNCTION = "weeklyDataSync"
EXPECTED_CACHE_PREFIX = "weeklyActivityApiCache:v20260704:"
EXPECTED_SOURCE_MODE = "sanji_desktop_rss"


Check = dict[str, Any]
JsonFetcher = Callable[[str], dict[str, Any]]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def add_check(
    checks: list[Check],
    area: str,
    name: str,
    ok: bool,
    detail: str,
    *,
    severity: str = "fail",
    evidence: Any = None,
) -> None:
    checks.append(
        {
            "area": area,
            "name": name,
            "status": "ok" if ok else severity,
            "detail": detail,
            "evidence": evidence,
        }
    )


def add_info(checks: list[Check], area: str, name: str, detail: str, *, evidence: Any = None) -> None:
    checks.append({"area": area, "name": name, "status": "info", "detail": detail, "evidence": evidence})


def require_tokens(checks: list[Check], area: str, path: Path, tokens: list[str], *, name: str | None = None) -> None:
    if not path.exists():
        add_check(checks, area, name or path.name, False, f"missing file: {path}")
        return
    text = read_text(path)
    missing = [token for token in tokens if token not in text]
    add_check(
        checks,
        area,
        name or path.name,
        not missing,
        "matched" if not missing else "missing tokens: " + ", ".join(missing),
        evidence=str(path),
    )


def iso_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def parse_time(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def today_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def first(value: Any, fallback: str = "") -> str:
    if isinstance(value, list):
        return str(value[0] if value else fallback)
    return str(value or fallback)


def item_date_start(item: dict[str, Any]) -> str:
    return (
        iso_date(item.get("event_date_start"))
        or iso_date(item.get("eventDateStart"))
        or iso_date(item.get("event_date_iso_guess"))
        or iso_date(first(item.get("event_date_iso_guesses")))
        or iso_date(item.get("date"))
    )


def item_date_end(item: dict[str, Any]) -> str:
    return (
        iso_date(item.get("event_date_end"))
        or iso_date(item.get("eventDateEnd"))
        or item_date_start(item)
    )


def is_current_or_future(item: dict[str, Any], today: str) -> bool:
    end = item_date_end(item)
    return not end or not today or end >= today


def storage_slug(value: Any) -> str:
    raw = str(value or "").strip().lower()
    out = []
    for char in raw:
        if re.match(r"[a-z0-9_-]", char):
            out.append(char)
        else:
            out.append(f"u{ord(char):x}")
    return re.sub(r"^-+|-+$", "", re.sub(r"-+", "-", "".join(out)))


def item_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("id") or item.get("event_id") or "").strip()


def current_items_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("events") or []
        return [item for item in items if isinstance(item, dict)]
    return []


def http_get_json(url: str, timeout: float = 12.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "weekly-audit/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON from {url}")
    return payload


def public_url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    base = str(base_url or "").rstrip("/")
    if query:
        return f"{base}{path}?{urllib.parse.urlencode(query)}"
    return f"{base}{path}"


def fetch_public_current(fetch_json: JsonFetcher, base_url: str, lookback_days: int, limit: int = 100) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    cursor = "0"
    for _ in range(10):
        payload = fetch_json(
            public_url(
                base_url,
                "/api/v1/weekly/current",
                {"limit": limit, "lookbackDays": lookback_days, "cursor": cursor},
            )
        )
        all_items.extend(current_items_from_payload(payload))
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        next_cursor = page.get("nextCursor")
        if next_cursor is None or next_cursor == "":
            break
        if str(next_cursor) == cursor:
            break
        cursor = str(next_cursor)
    return all_items


def audit_frontend(checks: list[Check], miniapp_dir: Path) -> None:
    app_js_path = miniapp_dir / "app.js"
    app_json_path = miniapp_dir / "app.json"
    api_js_path = miniapp_dir / "utils" / "api.js"
    api_cache_path = miniapp_dir / "utils" / "api" / "cache.js"
    index_js_path = miniapp_dir / "pages" / "index" / "index.js"
    home_filters_path = miniapp_dir / "services" / "homeFilters.js"
    location_city_path = miniapp_dir / "utils" / "locationCity.js"

    require_tokens(
        checks,
        "frontend",
        app_js_path,
        [
            f'env: "{EXPECTED_ENV_ID}"',
            f'service: "{EXPECTED_SERVICE}"',
            f'publicBaseUrl: "{EXPECTED_PUBLIC_BASE_URL}"',
            f'databaseFunctionName: "{EXPECTED_DB_FUNCTION}"',
            "useCloudDatabaseFirst: false",
            "offlineSnapshotFallback: true",
            "fastOfflineSnapshotFallback: false",
            "offlineSnapshotFallbackDelayMs: -1",
            "wx.getFuzzyLocation",
            'type: "gcj02"',
            "nearestCityKey",
            "weeklyActivityUserLocCity",
            "weeklyActivityPreferredCity",
            "onLocationReady",
        ],
        name="app.js production cloud/location config",
    )
    if app_json_path.exists():
        app_json = read_json(app_json_path)
        add_check(
            checks,
            "frontend",
            "app.json declares approved location private info",
            app_json.get("requiredPrivateInfos") == ["getFuzzyLocation"],
            f"requiredPrivateInfos={app_json.get('requiredPrivateInfos')}",
            evidence=str(app_json_path),
        )
        location_desc = ((app_json.get("permission") or {}).get("scope.userFuzzyLocation") or {}).get("desc")
        add_check(
            checks,
            "frontend",
            "app.json userFuzzyLocation permission describes city priority",
            location_desc == "用于优先推荐你所在城市的活动",
            f"desc={location_desc}",
            evidence=str(app_json_path),
        )
    else:
        add_check(checks, "frontend", "app.json exists", False, f"missing file: {app_json_path}")

    require_tokens(
        checks,
        "frontend",
        api_js_path,
        [
            EXPECTED_CACHE_PREFIX,
            "isDefaultCurrentFeedRequest",
            "normalizeStoredCurrentPayload",
            "itemIsCurrentOrFuture",
            "readPersistedResponse",
            "canStartFastOfflineSnapshot",
            "!isDefaultCurrentFeedRequest(path, data)",
            "requestOfflineSnapshot",
            "shouldRequireLiveResponse",
            "shouldSkipStoredFallback",
        ],
        name="utils/api.js stale-cache fail-closed contract",
    )
    require_tokens(
        checks,
        "frontend",
        api_cache_path,
        [EXPECTED_CACHE_PREFIX, "writeCachedResponse", "readCachedResponse"],
        name="utils/api/cache.js namespace alignment",
    )
    require_tokens(
        checks,
        "frontend",
        index_js_path,
        [
            "lookbackDays: 0",
            "__skipCache: true",
            "__liveOnly: true",
            "currentFeedBehindManifest",
            "HOME_LATE_NIGHT_CUTOFF_HOUR",
            "currentWeekendWindow",
            "applyDefaultHomeDateWindow",
            "filterItemsByDateWindow",
            "buildCityFiltersFromIndex",
            "cityIndexFilters || buildCityFiltersFallback",
            "boostLocalItems",
            "readLocatedCityKey",
            "readLocalCityKey",
            "applyLocatedCityKey",
            "weeklyActivityUserLocCity",
            "weeklyActivityPreferredCity",
        ],
        name="pages/index.js current-window/location priority contract",
    )
    if index_js_path.exists():
        index_js = read_text(index_js_path)
        add_check(
            checks,
            "frontend",
            "home feed does not request historical lookback by default",
            "lookbackDays: 45" not in index_js,
            "lookbackDays:45 absent" if "lookbackDays: 45" not in index_js else "lookbackDays:45 present",
            evidence=str(index_js_path),
        )
        add_check(
            checks,
            "frontend",
            "manual preferred city does not overwrite real located city in index page",
            "globalData.userLocationCityKey = key" not in index_js,
            "index page keeps located and preferred city storage separate",
            evidence=str(index_js_path),
        )
    require_tokens(
        checks,
        "frontend",
        home_filters_path,
        ["filterItemsByDateWindow", "dateKeysForFilter", "itemMatchesCityKey"],
        name="homeFilters date/city primitives",
    )
    require_tokens(
        checks,
        "frontend",
        location_city_path,
        ["nearestCityKey", "MAX_MATCH_KM", "chengdu", "shanghai", "guangzhou"],
        name="locationCity nearest city map",
    )


def audit_backend(checks: list[Check], cloudrun_dir: Path) -> None:
    cloudbaserc_path = cloudrun_dir / "cloudbaserc.json"
    data_store_path = cloudrun_dir / "src" / "dataStore.mjs"
    server_path = cloudrun_dir / "src" / "server.mjs"
    bake_path = cloudrun_dir / "scripts" / "bake_and_deploy.py"
    direct_deploy_path = cloudrun_dir / "scripts" / "direct_cloudbase_deploy.py"

    if cloudbaserc_path.exists():
        cloudbaserc = read_json(cloudbaserc_path)
        add_check(
            checks,
            "backend",
            "CloudRun cloudbaserc envId matches mini-program env",
            cloudbaserc.get("envId") == EXPECTED_ENV_ID,
            f"envId={cloudbaserc.get('envId')}",
            evidence=str(cloudbaserc_path),
        )
        add_check(
            checks,
            "backend",
            "CloudRun service name matches frontend service",
            ((cloudbaserc.get("cloudrun") or {}).get("name")) == EXPECTED_SERVICE,
            f"service={((cloudbaserc.get('cloudrun') or {}).get('name'))}",
            evidence=str(cloudbaserc_path),
        )
    else:
        add_check(checks, "backend", "CloudRun cloudbaserc exists", False, f"missing file: {cloudbaserc_path}")

    require_tokens(
        checks,
        "backend",
        data_store_path,
        [
            "const DEFAULT_CURRENT_LOOKBACK_DAYS = 0",
            "normalizeLookbackDays",
            "currentThreshold",
            "itemIsCurrentOrFuture",
            "isElectronicMusicRelevantItem",
            "dedupeItems",
            "lookbackDays: lookback || null",
        ],
        name="WeeklyActivityDataStore current feed default filter",
    )
    require_tokens(
        checks,
        "backend",
        server_path,
        [
            'pathname === "/api/v1/weekly/current"',
            '["cityKey", "date", "limit", "cursor", "lookbackDays"]',
            "store.getCurrent",
            "sendCachedWeeklyJson",
        ],
        name="server current route accepts lookbackDays but defaults through store",
    )
    require_tokens(
        checks,
        "backend",
        bake_path,
        [
            "refresh_offline_snapshot: bool = False",
            '"--refresh-offline-snapshot"',
            "skip mini-program offlineSnapshot.js refresh",
            "last live API cache tracks package updates",
        ],
        name="bake/deploy does not refresh bundled miniapp snapshot by default",
    )
    require_tokens(
        checks,
        "backend",
        direct_deploy_path,
        ["DescribeCloudBaseBuildService", "UpdateCloudRunServer", "EnvId", "ServiceName"],
        name="direct deploy script is explicit final-stage CloudBase action",
    )


def audit_cloudbase_db(checks: list[Check], miniapp_dir: Path) -> None:
    cloudbaserc_path = miniapp_dir / "cloudbaserc.json"
    function_path = miniapp_dir / "cloudfunctions" / EXPECTED_DB_FUNCTION / "index.js"
    sync_script_path = miniapp_dir / "scripts" / "sync_cloudbase_database.cjs"

    if cloudbaserc_path.exists():
        cloudbaserc = read_json(cloudbaserc_path)
        names = {str(item.get("name")) for item in cloudbaserc.get("functions", []) if isinstance(item, dict)}
        add_check(
            checks,
            "cloudbase_db",
            "miniapp CloudBase envId matches backend",
            cloudbaserc.get("envId") == EXPECTED_ENV_ID,
            f"envId={cloudbaserc.get('envId')}",
            evidence=str(cloudbaserc_path),
        )
        add_check(
            checks,
            "cloudbase_db",
            "weeklyDataSync function is registered",
            EXPECTED_DB_FUNCTION in names,
            f"functions={sorted(names)}",
            evidence=str(cloudbaserc_path),
        )
    else:
        add_check(checks, "cloudbase_db", "miniapp cloudbaserc exists", False, f"missing file: {cloudbaserc_path}")

    require_tokens(
        checks,
        "cloudbase_db",
        function_path,
        [
            f'const DEFAULT_BASE_URL = "{EXPECTED_PUBLIC_BASE_URL}"',
            f'const DEFAULT_ENV_ID = "{EXPECTED_ENV_ID}"',
            'current: "weekly_current"',
            'events: "weekly_events"',
            "function normalizeLookbackDays(value, fallback = 0)",
            "syncLookbackDaysFromEvent",
            "buildCurrentFetchPath",
            "lookbackDays=${lookbackDays}",
            "getContainerFreshness",
            "db-behind-container",
            "container-readthrough",
            "skipFreshness",
            "ADMIN_ACTIONS",
            "adminActionAllowed",
        ],
        name="weeklyDataSync DB read/sync freshness contract",
    )
    require_tokens(
        checks,
        "cloudbase_db",
        sync_script_path,
        [
            'functionName = process.env.WEEKLY_DATA_FUNCTION || "weeklyDataSync"',
            'action: "sync"',
            "adminToken",
            'path: "/api/v1/weekly/current"',
            "readProbe",
        ],
        name="sync_cloudbase_database is explicit sync plus read probe",
    )


def audit_data_package(
    checks: list[Check],
    release_dir: Path,
    *,
    today: str,
    min_generated_date: str,
) -> dict[str, Any]:
    manifest_path = release_dir / "manifest.json"
    current_path = release_dir / "current.json"
    if not manifest_path.exists() or not current_path.exists():
        add_check(checks, "data_package", "current release package files exist", False, f"missing {manifest_path} or {current_path}")
        return {}

    manifest = read_json(manifest_path)
    current = read_json(current_path)
    items = current_items_from_payload(current)
    ids = [item_id(item) for item in items if item_id(item)]
    duplicate_ids = sorted([key for key, count in Counter(ids).items() if count > 1])
    generated_at = manifest.get("generated_at") or manifest.get("generatedAt")
    window_start = iso_date(manifest.get("window_start") or manifest.get("windowStart"))
    window_end = iso_date(manifest.get("window_end") or manifest.get("windowEnd"))

    add_check(
        checks,
        "data_package",
        "manifest item_count matches current.json",
        int(manifest.get("item_count") or 0) == len(items),
        f"manifest={manifest.get('item_count')} current_items={len(items)}",
        evidence=str(release_dir),
    )
    add_check(
        checks,
        "data_package",
        "current item ids are unique",
        not duplicate_ids,
        f"duplicates={duplicate_ids[:20]}",
        evidence=str(current_path),
    )
    add_check(
        checks,
        "data_package",
        "package generated_at is latest expected date",
        str(generated_at or "")[:10] >= min_generated_date,
        f"generated_at={generated_at} min={min_generated_date}",
        evidence=str(manifest_path),
    )
    add_check(
        checks,
        "data_package",
        "package window includes current China date",
        bool(window_start and window_end and window_start <= today <= window_end),
        f"window={window_start}..{window_end} today={today}",
        evidence=str(manifest_path),
    )
    sanji_contract = manifest.get("sanji_source_contract") if isinstance(manifest.get("sanji_source_contract"), dict) else {}
    add_check(
        checks,
        "data_package",
        "manifest records Sanji desktop snapshot source",
        manifest.get("source_mode") == EXPECTED_SOURCE_MODE and sanji_contract.get("sanji_db_snapshot_export") is True,
        f"source_mode={manifest.get('source_mode')} sanji_db_snapshot_export={sanji_contract.get('sanji_db_snapshot_export')}",
        evidence=str(manifest_path),
    )
    add_check(
        checks,
        "data_package",
        "manifest forbids direct RSS as production source",
        manifest.get("direct_rss_feed_fetch") is False and sanji_contract.get("direct_rss_feed_fetch") is False,
        f"top={manifest.get('direct_rss_feed_fetch')} contract={sanji_contract.get('direct_rss_feed_fetch')}",
        evidence=str(manifest_path),
    )
    poster_migration = manifest.get("poster_migration") if isinstance(manifest.get("poster_migration"), dict) else {}
    if poster_migration:
        add_check(
            checks,
            "data_package",
            "poster migration manifest uses production CloudBase env",
            poster_migration.get("env_id") == EXPECTED_ENV_ID,
            f"env_id={poster_migration.get('env_id')} migrated_count={poster_migration.get('migrated_count')}",
            evidence=str(manifest_path),
        )
    else:
        add_check(checks, "data_package", "poster migration manifest exists", False, "poster_migration missing", severity="warn")

    by_id_dir = release_dir / "by-id"
    missing_by_id = []
    if by_id_dir.exists():
        for value in ids:
            if not (by_id_dir / f"{storage_slug(value)}.json").exists():
                missing_by_id.append(value)
                if len(missing_by_id) >= 20:
                    break
    add_check(
        checks,
        "data_package",
        "by-id contains current item detail files",
        by_id_dir.exists() and not missing_by_id,
        f"missing_samples={missing_by_id}",
        evidence=str(by_id_dir),
    )

    raw_history = [item for item in items if item_date_end(item) and item_date_end(item) < today]
    default_candidates = [item for item in items if is_current_or_future(item, today)]
    default_past = [item for item in default_candidates if item_date_end(item) and item_date_end(item) < today]
    add_check(
        checks,
        "data_package",
        "local package can produce non-empty default-current window",
        len(default_candidates) > 0,
        f"default_current_count={len(default_candidates)} today={today}",
        evidence=str(current_path),
    )
    add_check(
        checks,
        "data_package",
        "local default-current window excludes ended past rows",
        not default_past,
        f"past_samples={[item_id(item) for item in default_past[:10]]}",
        evidence=str(current_path),
    )
    add_info(
        checks,
        "data_package",
        "raw current_release history rows",
        "raw package may include historical rows; frontend/API default-current filtering remains mandatory",
        evidence={"past_before_today": len(raw_history), "today": today},
    )

    return {
        "manifest": manifest,
        "current_item_count": len(items),
        "raw_history_count": len(raw_history),
        "default_current_count": len(default_candidates),
    }


def audit_online_api(
    checks: list[Check],
    base_url: str,
    local_manifest: dict[str, Any],
    *,
    today: str,
    require_online: bool = False,
    fetch_json: JsonFetcher | None = None,
) -> dict[str, Any]:
    fetcher = fetch_json or http_get_json
    try:
        manifest = fetcher(public_url(base_url, "/api/v1/weekly/manifest"))
        current_items = fetch_public_current(fetcher, base_url, 0)
        lookback_items = fetch_public_current(fetcher, base_url, 45)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as exc:
        add_check(
            checks,
            "online_api",
            "public API reachable",
            False,
            f"{type(exc).__name__}: {exc}",
            severity="fail" if require_online else "warn",
            evidence=base_url,
        )
        return {}

    local_count = int(local_manifest.get("item_count") or 0) if local_manifest else 0
    online_count = int(manifest.get("item_count") or manifest.get("itemCount") or 0)
    local_generated = local_manifest.get("generated_at") or local_manifest.get("generatedAt") if local_manifest else ""
    online_generated = manifest.get("generated_at") or manifest.get("generatedAt")
    online_source_mode = manifest.get("source_mode") or manifest.get("sourceMode")
    past_default = [item for item in current_items if item_date_end(item) and item_date_end(item) < today]
    past_lookback = [item for item in lookback_items if item_date_end(item) and item_date_end(item) < today]

    add_check(
        checks,
        "online_api",
        "public manifest item count matches local current_release",
        not local_count or online_count == local_count,
        f"online={online_count} local={local_count}",
        evidence=public_url(base_url, "/api/v1/weekly/manifest"),
    )
    add_check(
        checks,
        "online_api",
        "public manifest is not older than local manifest",
        not local_generated or parse_time(online_generated) >= parse_time(local_generated),
        f"online={online_generated} local={local_generated}",
        evidence=public_url(base_url, "/api/v1/weekly/manifest"),
    )
    add_check(
        checks,
        "online_api",
        "public manifest source mode is Sanji desktop RSS",
        online_source_mode == EXPECTED_SOURCE_MODE,
        f"source_mode={online_source_mode}",
        evidence=public_url(base_url, "/api/v1/weekly/manifest"),
    )
    add_check(
        checks,
        "online_api",
        "public default current API returns no ended past rows",
        len(current_items) > 0 and not past_default,
        f"default_items={len(current_items)} past_before_today={len(past_default)} today={today}",
        evidence=public_url(base_url, "/api/v1/weekly/current", {"limit": 100, "lookbackDays": 0}),
    )
    add_info(
        checks,
        "online_api",
        "public lookback current API history boundary",
        "lookbackDays=45 may expose historical rows by design; frontend stale guards must stay",
        evidence={"lookback_items": len(lookback_items), "past_before_today": len(past_lookback), "today": today},
    )
    return {
        "manifest": manifest,
        "default_current_items": len(current_items),
        "lookback_current_items": len(lookback_items),
        "lookback_past_before_today": len(past_lookback),
    }


def audit_sanji_hermes_static(checks: list[Check], repo_root: Path) -> None:
    run_openclaw = repo_root / "tools" / "stage7_rewrite" / "run_openclaw_weekly_daily_publish.ps1"
    daily_twice = repo_root / "tools" / "stage7_rewrite" / "run_huaidj_sanji_daily_twice.ps1"
    installer = repo_root / "tools" / "stage7_rewrite" / "scripts" / "install_huaidj_sanji_hermes_jobs.py"
    hermes_audit = repo_root / "tools" / "stage7_rewrite" / "scripts" / "audit_huaidj_sanji_hermes_contract.py"

    require_tokens(
        checks,
        "sanji_hermes",
        run_openclaw,
        [
            '[string]$SourceMode = "sanji_desktop_rss"',
            "Assert-SanjiLatestExportReady",
            "$script:SanjiRunQueuePath",
            "sanji_source_contract",
            "direct_rss_feed_fetch must stay false",
            "--max-missing 0",
            "if ($DeployBackend)",
            "if ($UploadFrontend)",
            "$script:CloudRunDeployExecuted = $false",
            "$script:MiniProgramUploadExecuted = $false",
        ],
        name="OpenClaw weekly publish wrapper Sanji/default final-stage gates",
    )
    require_tokens(
        checks,
        "sanji_hermes",
        daily_twice,
        [
            "[int]$PosterVlMaxImages = 0",
            "-SkipSanjiExport",
            "sanji_db_snapshot_export",
            "direct_rss_feed_fetch must stay false",
            "huaidj_sanji_daily_publish.lock",
        ],
        name="Sanji daily wrapper snapshot/no-direct-RSS contract",
    )
    require_tokens(
        checks,
        "sanji_hermes",
        installer,
        [
            "HUAIDJ Sanji Wed 21:10",
            "HUAIDJ Sanji Fri 20:10",
            "10 21 * * 3",
            "10 20 * * 5",
            "*/30 8-23 * * *",
            "HUAIDJ Coverage Audit Fri 21:40",
            "LEGACY_JOB_NAMES",
        ],
        name="Hermes installer current schedule contract",
    )
    require_tokens(
        checks,
        "sanji_hermes",
        hermes_audit,
        [
            "EXPECTED_HERMES_JOBS",
            "HUAIDJ Sanji Fri 20:10",
            "HUAIDJ Coverage Audit Fri 21:40",
            "LEGACY_ALLOWED_PAUSED_HERMES_JOBS",
            "Windows task disabled",
            "Codex duplicate executor paused",
        ],
        name="Hermes live schedule audit coverage",
    )


def audit_release_boundaries(checks: list[Check], repo_root: Path, miniapp_dir: Path) -> None:
    preflight = repo_root / "tools" / "stage7_rewrite" / "scripts" / "run_weekly_deploy_upload_preflight.py"
    clean_ci = miniapp_dir / "scripts" / "Test-CleanCiQuality.ps1"
    upload_script = miniapp_dir / "scripts" / "upload_native_windows.ps1"

    require_tokens(
        checks,
        "release_boundaries",
        preflight,
        [
            "direct_cloudbase_deploy.py",
            "final-stage only",
            "bake_and_deploy.py must use --dry-run or --prepare-only in preflight",
            "upload_native_windows.ps1",
            "-whatif",
            '"deployment_executed": False',
            '"upload_executed": False',
            '"database_mutations": False',
        ],
        name="deploy/upload preflight blocks final-stage commands",
    )
    require_tokens(
        checks,
        "release_boundaries",
        clean_ci,
        [
            "$useNpmExecCi = -not (Test-Path -LiteralPath $cli)",
            "npm exec --yes --package miniprogram-ci -- miniprogram-ci check-code-quality",
        ],
        name="clean CI quality gate has miniprogram-ci npm fallback",
    )
    require_tokens(
        checks,
        "release_boundaries",
        upload_script,
        [
            "[CmdletBinding(SupportsShouldProcess = $true)]",
            "$WhatIfPreference",
            "ShouldProcess",
            "miniprogram-ci",
            "upload",
        ],
        name="upload script has explicit WhatIf/final upload boundary",
    )


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    checks = report["checks"]
    failures = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    by_area = Counter(item["area"] for item in checks)
    lines = [
        "# Weekly Mini-Program All Pipelines Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- report_only: `{report['report_only']}`",
        f"- mutations_executed: `{report['mutations_executed']}`",
        f"- failures: `{len(failures)}`",
        f"- warnings: `{len(warnings)}`",
        "",
        "## Areas",
    ]
    for area, count in sorted(by_area.items()):
        area_failures = sum(1 for item in checks if item["area"] == area and item["status"] == "fail")
        area_warnings = sum(1 for item in checks if item["area"] == area and item["status"] == "warn")
        lines.append(f"- `{area}`: checks `{count}`, failures `{area_failures}`, warnings `{area_warnings}`")
    lines += ["", "## Findings"]
    if failures or warnings:
        for item in failures + warnings:
            lines.append(f"- `{item['status']}` `{item['area']}/{item['name']}`: {item['detail']}")
    else:
        lines.append("- None.")
    lines += [
        "",
        "## Boundary",
        "- This audit did not run Sanji sync, CloudBase DB sync, CloudRun deploy, CloudBase poster migration, mini-program upload, review submission, public release, private-key read, cookie/token/env read, or destructive Git action.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_audit(
    *,
    repo_root: Path = REPO_ROOT,
    miniapp_dir: Path = DEFAULT_MINIAPP_DIR,
    cloudrun_dir: Path = DEFAULT_CLOUDRUN_DIR,
    release_dir: Path = DEFAULT_RELEASE_DIR,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    today: str | None = None,
    min_generated_date: str = "2026-07-04",
    skip_online: bool = False,
    require_online: bool = False,
    fetch_json: JsonFetcher | None = None,
) -> dict[str, Any]:
    today_key = today or today_shanghai()
    checks: list[Check] = []

    add_check(checks, "scope", "repo root exists", repo_root.exists(), str(repo_root))
    audit_frontend(checks, miniapp_dir)
    audit_backend(checks, cloudrun_dir)
    audit_cloudbase_db(checks, miniapp_dir)
    package_summary = audit_data_package(checks, release_dir, today=today_key, min_generated_date=min_generated_date)
    audit_sanji_hermes_static(checks, repo_root)
    audit_release_boundaries(checks, repo_root, miniapp_dir)
    online_summary: dict[str, Any] = {}
    if skip_online:
        add_info(checks, "online_api", "public API check skipped", "--skip-online was provided", evidence=public_base_url)
    else:
        online_summary = audit_online_api(
            checks,
            public_base_url,
            package_summary.get("manifest") or {},
            today=today_key,
            require_online=require_online,
            fetch_json=fetch_json,
        )

    failures = [item for item in checks if item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "schema_version": "weekly_miniprogram_all_pipelines_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "weekly_miniprogram_all_pipelines_aligned" if not failures else "weekly_miniprogram_all_pipelines_findings",
        "report_only": True,
        "mutations_executed": False,
        "safety": {
            "sanji_sync_executed": False,
            "cloudbase_database_sync_executed": False,
            "cloudrun_deploy_executed": False,
            "cloudbase_poster_migration_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "secret_files_read": False,
        },
        "repo": str(repo_root),
        "miniapp_dir": str(miniapp_dir),
        "cloudrun_dir": str(cloudrun_dir),
        "release_dir": str(release_dir),
        "public_base_url": public_base_url,
        "today": today_key,
        "min_generated_date": min_generated_date,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "summary": {
            "package": package_summary,
            "online": online_summary,
            "checks_total": len(checks),
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--miniapp-dir", type=Path, default=DEFAULT_MINIAPP_DIR)
    parser.add_argument("--cloudrun-dir", type=Path, default=DEFAULT_CLOUDRUN_DIR)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
    parser.add_argument("--today", default="")
    parser.add_argument("--min-generated-date", default="2026-07-04")
    parser.add_argument("--skip-online", action="store_true")
    parser.add_argument("--require-online", action="store_true")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--md-out", type=Path, default=None)
    args = parser.parse_args()

    report = run_audit(
        repo_root=args.repo_root,
        miniapp_dir=args.miniapp_dir,
        cloudrun_dir=args.cloudrun_dir,
        release_dir=args.release_dir,
        public_base_url=args.public_base_url,
        today=args.today or None,
        min_generated_date=args.min_generated_date,
        skip_online=args.skip_online,
        require_online=args.require_online,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out = args.md_out or args.json_out.with_suffix(".md")
    write_markdown(md_out, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "failure_count": report["failure_count"],
                "warning_count": report["warning_count"],
                "json": str(args.json_out),
                "markdown": str(md_out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["failure_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
