#!/usr/bin/env bash
# =============================================================================
# HUAIDJ Weekly Activity — Automated Pipeline (Docker Cron)
# =============================================================================
# Runs inside the CloudRun Docker container on a cron schedule.
# Workflow: scrape → enrich → validate → bake → deploy
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${WEEKLY_ACTIVITY_API_DIR:-${APP_DIR}/data/current_release}"
LOG_DIR="${APP_DIR}/logs"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/pipeline_${TIMESTAMP}.log"

mkdir -p "${LOG_DIR}"

log()  { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"; }
err()  { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "${LOG_FILE}"; }

# --- Config ---
ENRICH_ENABLED="${DEEPSEEK_ENRICH_ENABLED:-false}"
RELEASE_SOURCE_DIR="${DOWNSTREAM_RESULTS_DIR:-}"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"
DEEPSEEK_THINKING_TYPE="${DEEPSEEK_THINKING_TYPE:-disabled}"
LLM_ENRICH_CONCURRENCY="${LLM_ENRICH_CONCURRENCY:-2}"
LLM_ENRICH_LIMIT="${LLM_ENRICH_LIMIT:-0}"

log "=== HUAIDJ Weekly Pipeline START (${TIMESTAMP}) ==="
log "  ENRICH_ENABLED=${ENRICH_ENABLED}"
log "  RELEASE_SOURCE_DIR=${RELEASE_SOURCE_DIR:-<not set>}"
if [[ -n "${DEEPSEEK_API_KEY}" ]]; then
    log "  DEEPSEEK_API_KEY=<set>"
else
    log "  DEEPSEEK_API_KEY=<NOT SET>"
fi
log "  DEEPSEEK_MODEL=${DEEPSEEK_MODEL}"
log "  DEEPSEEK_THINKING_TYPE=${DEEPSEEK_THINKING_TYPE}"

# --- Step 1: Find latest release data ---
find_latest_release() {
    local base="${1}"
    if [[ -z "${base}" || ! -d "${base}" ]]; then
        log "Step 1: No release source dir — skipping data ingestion"
        return 1
    fi
    # Find newest upstream release directory. Matches either:
    #   WEEKLY_ACTIVITY_MINIPROGRAM_API_*  (primary naming)
    #   processed_*                         (alternative naming)
    local latest
    latest=$(find "${base}" -maxdepth 2 -type d \( -name "WEEKLY_ACTIVITY_MINIPROGRAM_API_*" -o -name "processed_*" \) \
        -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [[ -z "${latest}" ]]; then
        log "Step 1: No release directory found under ${base}"
        return 1
    fi
    echo "${latest}"
}

RELEASE_DIR=$(find_latest_release "${RELEASE_SOURCE_DIR}" || true)

if [[ -n "${RELEASE_DIR}" && -d "${RELEASE_DIR}" ]]; then
    log "Step 1: Found release: ${RELEASE_DIR}"

    # Copy release items
    for item in current.json manifest.json by-city by-date by-id; do
        src="${RELEASE_DIR}/${item}"
        dst="${DATA_DIR}/${item}"
        if [[ -e "${src}" ]]; then
            if [[ -d "${src}" ]]; then
                rm -rf "${dst}" 2>/dev/null || true
                cp -r "${src}" "${dst}"
            else
                cp "${src}" "${dst}"
            fi
            log "  copied: ${item}"
        else
            log "  SKIP (not found): ${item}"
        fi
    done

    # Copy source_url_map
    for map_candidate in \
        "${RELEASE_DIR}/source_actions/source_url_map.json" \
        "${RELEASE_DIR}/../source_actions/source_url_map.json" \
        "${RELEASE_SOURCE_DIR}/source_actions/source_url_map.json"; do
        if [[ -f "${map_candidate}" ]]; then
            mkdir -p "${APP_DIR}/data/source_actions"
            cp "${map_candidate}" "${APP_DIR}/data/source_actions/source_url_map.json"
            log "  copied: source_url_map.json (from ${map_candidate})"
            break
        fi
    done
else
    log "Step 1: No new release data — using existing data"
fi

# --- Step 2: LLM Enrichment (if enabled) ---
if [[ "${ENRICH_ENABLED}" == "true" && -n "${DEEPSEEK_API_KEY}" ]]; then
    log "Step 2: LLM enrichment enabled — materializing DeepSeek outputs..."

    # Read current.json to get item IDs
    CURRENT_JSON="${DATA_DIR}/current.json"
    if [[ -f "${CURRENT_JSON}" ]]; then
        ITEM_COUNT=$(node -e "
            const data = require('${CURRENT_JSON}');
            console.log((data.items || []).length);
        " 2>/dev/null || echo "0")
        log "  Items in release: ${ITEM_COUNT}"
        materialize_args=(--data-dir "${DATA_DIR}" --concurrency "${LLM_ENRICH_CONCURRENCY}")
        if [[ "${LLM_ENRICH_LIMIT}" != "0" ]]; then
            materialize_args+=(--enrich-limit "${LLM_ENRICH_LIMIT}")
        fi
        DEEPSEEK_MODEL="${DEEPSEEK_MODEL}" \
        DEEPSEEK_THINKING_TYPE="${DEEPSEEK_THINKING_TYPE}" \
        node "${APP_DIR}/scripts/materialize_llm_outputs.mjs" "${materialize_args[@]}" | tee -a "${LOG_FILE}"
    fi
else
    log "Step 2: LLM enrichment DISABLED (ENRICH_ENABLED=${ENRICH_ENABLED})"
fi

# --- Step 3: Health check ---
log "Step 3: Running health check..."
HEALTH=$(curl -s "http://localhost:${PORT:-8787}/healthz" 2>/dev/null || echo '{"ok":false}')
log "  Health: ${HEALTH}"

# --- Step 4: Validate data integrity ---
log "Step 4: Validating data integrity..."
FAIL=0
for required in current.json manifest.json; do
    if [[ ! -f "${DATA_DIR}/${required}" ]]; then
        err "  MISSING: ${required}"
        FAIL=1
    fi
done
for required_dir in by-city by-date by-id; do
    if [[ ! -d "${DATA_DIR}/${required_dir}" ]]; then
        err "  MISSING dir: ${required_dir}"
        FAIL=1
    fi
done
if [[ ${FAIL} -eq 0 ]]; then
    log "  All required data present ✓"
else
    err "  Data validation FAILED — check logs"
fi

# --- Step 5: Generate status report ---
REPORT_FILE="${DATA_DIR}/pipeline_status_${TIMESTAMP}.json"
node -e "
    const fs = require('fs');
    const dataDir = '${DATA_DIR}';
    let itemCount = 0, cityCount = 0, dateCount = 0;
    try {
        const c = JSON.parse(fs.readFileSync(dataDir + '/current.json', 'utf8'));
        itemCount = (c.items || []).length;
    } catch(e) {}
    try {
        const ci = JSON.parse(fs.readFileSync(dataDir + '/by-city/index.json', 'utf8'));
        cityCount = Array.isArray(ci.cities) ? ci.cities.length : (ci.item_count || 0);
    } catch(e) {}
    try {
        const di = JSON.parse(fs.readFileSync(dataDir + '/by-date/index.json', 'utf8'));
        dateCount = Array.isArray(di.dates) ? di.dates.length : (di.item_count || 0);
    } catch(e) {}
    const report = {
        schemaVersion: 'weekly_activity_api.pipeline_status.v1',
        timestamp: '${TIMESTAMP}',
        status: 'completed',
        data: { items: itemCount, cities: cityCount, dates: dateCount },
        enrich_enabled: '${ENRICH_ENABLED}' === 'true',
        release_source: '${RELEASE_DIR:-none}'
    };
    fs.writeFileSync('${REPORT_FILE}', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
" 2>/dev/null | tee -a "${LOG_FILE}"
log "  Status report: ${REPORT_FILE}"

log "=== HUAIDJ Weekly Pipeline END ==="
exit 0
