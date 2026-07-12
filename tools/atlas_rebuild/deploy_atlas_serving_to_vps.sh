#!/bin/bash
# Phase 6: deploy a verified Atlas serving candidate to the production VPS, with auto-rollback.
#
# Atlas v2 dedupe/freshness design
# (C:\code\mavelpoint-cn-v2\docs\site-clone\ATLAS_V2_DEDUP_SANJI_AUTOMATION_DEEP_DESIGN_2026-07-06.md).
#
# Sequence (every step gates the next; any failure before the swap aborts with production
# untouched; any failure after the swap triggers automatic rollback to .prev):
#   1. local gates: mavelpoint verify-atlas-db.mjs + slug-audit.mjs against the candidate
#   2. scp candidate -> /srv/baddj-cn/shared/data/atlas_serving.next.sqlite
#   3. remote verify-atlas-db.mjs against .next (proves the UPLOADED bytes, not the local file)
#   4. cp current -> atlas_serving.prev.sqlite (rollback point)
#   5. mv .next -> atlas_serving.sqlite (atomic on same filesystem)
#   6. systemctl restart baddj-cn; healthz + one real DJ profile route must return 200
#   7. on step-6 failure: mv .prev back, restart, report ROLLBACK
#
# Usage:
#   bash deploy_atlas_serving_to_vps.sh <candidate.sqlite> [--yes]
# Without --yes it stops after the local gates and prints what WOULD happen (default safe).

set -euo pipefail

CANDIDATE="${1:?usage: deploy_atlas_serving_to_vps.sh <candidate.sqlite> [--yes]}"
CONFIRM="${2:-}"
VPS="root@139.180.136.181"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=15"
REMOTE_DIR="/srv/baddj-cn/shared/data"
REMOTE_DB="$REMOTE_DIR/atlas_serving.sqlite"
REMOTE_NEXT="$REMOTE_DIR/atlas_serving.next.sqlite"
REMOTE_PREV="$REMOTE_DIR/atlas_serving.prev.sqlite"
REMOTE_VERIFY="$REMOTE_DIR/verify-atlas-db.mjs"
REMOTE_NODE="/opt/node-v24.15.0-linux-x64/bin/node"   # PATH node is v20, too old for node:sqlite
WEBSITE_REPO="${WEBSITE_REPO:-/mnt/c/code/mavelpoint-cn-v2}"
LOCAL_VERIFY="$WEBSITE_REPO/scripts/infra/verify-atlas-db.mjs"
PROFILE_CHECK_PATH="/artists"   # listing page exercises the atlas DB read path

[ -f "$CANDIDATE" ] || { echo "FATAL: candidate not found: $CANDIDATE"; exit 1; }
[ -f "$LOCAL_VERIFY" ] || { echo "FATAL: local verifier not found: $LOCAL_VERIFY"; exit 1; }

echo "=== [1/6] local gates ==="
(
    cd "$WEBSITE_REPO"
    node scripts/infra/verify-atlas-db.mjs "$CANDIDATE"
    node scripts/verify/slug-audit.mjs "$CANDIDATE" --check
)
echo "local gates passed."

if [ "$CONFIRM" != "--yes" ]; then
    SIZE=$(stat -c%s "$CANDIDATE" 2>/dev/null || stat -f%z "$CANDIDATE")
    echo ""
    echo "DRY STOP (no --yes): would upload $CANDIDATE ($SIZE bytes) to $VPS:$REMOTE_NEXT,"
    echo "verify remotely, swap atomically with a .prev rollback point, and restart baddj-cn."
    exit 0
fi

echo "=== [2/6] upload to .next ==="
LOCAL_SHA="$(sha256sum "$CANDIDATE" | awk '{print $1}')"
REMOTE_SHA="$(ssh $SSH_OPTS "$VPS" "test -f $REMOTE_NEXT && sha256sum $REMOTE_NEXT | cut -d ' ' -f1" || true)"
if [ "$REMOTE_SHA" = "$LOCAL_SHA" ]; then
    echo "existing .next SHA matches candidate; reusing completed upload."
else
    scp $SSH_OPTS "$CANDIDATE" "$VPS:$REMOTE_NEXT"
    REMOTE_SHA="$(ssh $SSH_OPTS "$VPS" "sha256sum $REMOTE_NEXT | cut -d ' ' -f1")"
    [ "$REMOTE_SHA" = "$LOCAL_SHA" ] || { echo "FATAL: uploaded .next SHA mismatch"; exit 1; }
fi
scp $SSH_OPTS "$LOCAL_VERIFY" "$VPS:$REMOTE_VERIFY.next"
ssh $SSH_OPTS "$VPS" "mv $REMOTE_VERIFY.next $REMOTE_VERIFY && chmod 640 $REMOTE_VERIFY"

echo "=== [3/6] remote verify of uploaded bytes ==="
ssh $SSH_OPTS "$VPS" "$REMOTE_NODE $REMOTE_VERIFY $REMOTE_NEXT"

echo "=== [4/6] snapshot rollback point (.prev) ==="
ssh $SSH_OPTS "$VPS" "cp -p $REMOTE_DB $REMOTE_PREV"

echo "=== [5/6] atomic swap ==="
ssh $SSH_OPTS "$VPS" "mv $REMOTE_NEXT $REMOTE_DB && chmod 640 $REMOTE_DB"

echo "=== [6/6] restart + health checks ==="
if ssh $SSH_OPTS "$VPS" "
    set -e
    systemctl restart baddj-cn
    sleep 5
    systemctl is-active baddj-cn
    curl -sf -o /dev/null -w 'healthz:%{http_code}\n' http://127.0.0.1:3010/healthz
    curl -sf -o /dev/null -w 'profile_route:%{http_code}\n' http://127.0.0.1:3010$PROFILE_CHECK_PATH
"; then
    echo ""
    echo "DEPLOY OK. Rollback point kept at $REMOTE_PREV (delete manually after soak)."
    ssh $SSH_OPTS "$VPS" "$REMOTE_NODE $REMOTE_VERIFY $REMOTE_DB"
else
    echo ""
    echo "!!! HEALTH CHECK FAILED — rolling back to .prev !!!"
    ssh $SSH_OPTS "$VPS" "
        mv $REMOTE_PREV $REMOTE_DB
        systemctl restart baddj-cn
        sleep 5
        systemctl is-active baddj-cn
        curl -sf -o /dev/null -w 'healthz_after_rollback:%{http_code}\n' http://127.0.0.1:3010/healthz
    "
    echo "ROLLBACK COMPLETE — production restored to the previous snapshot. Investigate before retrying."
    exit 1
fi
