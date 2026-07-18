from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_weekly_activity_miniprogram_api.py"

spec = importlib.util.spec_from_file_location("build_weekly_activity_miniprogram_api_source_policy_test", SCRIPT)
builder = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def candidate(*, article_id: str, account: str, title: str) -> dict[str, object]:
    return {
        "article_id": article_id,
        "title": title,
        "source_url": f"https://mp.weixin.qq.com/s/{article_id}",
        "account": account,
        "event_date_text": ["2026-07-20"],
        "city": ["上海"],
        "venue": ["Policy Test Club"],
        "address": "上海市黄浦区测试路1号",
        "lineup": ["DJ Test"],
        "genres": ["techno"],
        "music_styles": ["techno"],
        "evidence": ["2026-07-20 22:00 TECHNO NIGHT"],
    }


def test_cli_source_policy_filters_blocked_account_and_reports_reason(tmp_path: Path) -> None:
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "api"
    policy_path = tmp_path / "source-policy.json"
    blocked_by_fakeid = candidate(
        article_id="blocked-fakeid-article",
        account="Mixed Policy Account",
        title="Blocked Fakeid Techno Night",
    )
    blocked_by_fakeid["account_fakeid"] = "blocked-test-fakeid"
    blocked_by_hash = candidate(
        article_id="blocked-hash-article",
        account="Mixed Policy Account",
        title="Blocked Hash Techno Night",
    )
    blocked_hash = builder.sha256_short(str(blocked_by_hash["source_url"]))
    write_jsonl(
        pack_dir / "weekly_activity_recommendation_candidates.jsonl",
        [
            candidate(article_id="blocked-article", account="Blocked Policy Account", title="Blocked Techno Night"),
            blocked_by_fakeid,
            blocked_by_hash,
            candidate(article_id="kept-article", account="Kept Policy Account", title="Kept Techno Night"),
        ],
    )
    write_json(pack_dir / "summary.json", {})
    write_json(
        policy_path,
        {
            "schema_version": "weekly_sanji_source_policy.v2",
            "blocked_accounts": ["Blocked Policy Account"],
            "blocked_account_fakeids": ["blocked-test-fakeid"],
            "blocked_source_hashes": [blocked_hash],
            "blocked_venues": [],
            "article_level_block_categories": {},
            "electronic_keep_terms": ["techno"],
        },
    )

    exit_code = builder.main(
        [
            "--pack-dir",
            str(pack_dir),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-07-18",
            "--window-days",
            "15",
            "--source-policy",
            str(policy_path),
            "--source-queue",
            "",
            "--venue-registry",
            "",
            "--account-registry",
            "",
        ]
    )

    assert exit_code == 0
    current = json.loads((out_dir / "current.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [item["article_id"] for item in current["items"]] == ["kept-article"]
    assert manifest["item_count"] == 1
    assert manifest["filtered_counts"]["source_policy_blocked_account"] == 2
    assert manifest["filtered_counts"]["source_policy_blocked_source_hash"] == 1
    assert manifest["source_policy_path"] == str(policy_path)


def test_pipeline_registries_are_versioned_runtime_contracts() -> None:
    policy_path = ROOT / "registries" / "weekly_sanji_source_policy.json"
    account_path = ROOT / "registries" / "weekly_accounts_seed.json"
    artist_path = ROOT / "registries" / "weekly_artists_seed.json"
    pipeline = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8-sig")

    assert policy_path.is_file()
    assert account_path.is_file()
    assert artist_path.is_file()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    accounts = json.loads(account_path.read_text(encoding="utf-8"))
    artists = json.loads(artist_path.read_text(encoding="utf-8"))
    assert policy["schema_version"] == "weekly_sanji_source_policy.v2"
    assert isinstance(policy["blocked_source_hashes"], list)
    assert accounts["schema_version"] == "weekly_account_registry.v1"
    assert isinstance(accounts["accounts"], list) and accounts["accounts"]
    assert artists["schema_version"] == "weekly_artist_registry.v1"
    assert isinstance(artists["artists"], list) and artists["artists"]
    for name in (
        "weekly_sanji_source_policy.json",
        "weekly_accounts_seed.json",
        "weekly_artists_seed.json",
    ):
        assert name in pipeline
