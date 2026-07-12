"""Static control-plane checks for the Atlas VPS deployment script."""
from pathlib import Path


SCRIPT = Path(__file__).with_name("deploy_atlas_serving_to_vps.sh")


def test_deploy_uploads_release_independent_remote_verifier() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'REMOTE_VERIFY="$REMOTE_DIR/verify-atlas-db.mjs"' in source
    assert 'scp $SSH_OPTS "$LOCAL_VERIFY" "$VPS:$REMOTE_VERIFY.next"' in source
    assert '$REMOTE_NODE $REMOTE_VERIFY $REMOTE_NEXT' in source
    assert "/srv/baddj-cn/current/scripts/infra/verify-atlas-db.mjs" not in source


def test_deploy_reuses_only_sha_verified_next_upload() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'LOCAL_SHA="$(sha256sum "$CANDIDATE"' in source
    assert "sha256sum $REMOTE_NEXT | cut -d ' ' -f1" in source
    assert "sha256sum $REMOTE_NEXT | awk" not in source
    assert 'existing .next SHA matches candidate; reusing completed upload.' in source
    assert 'FATAL: uploaded .next SHA mismatch' in source
