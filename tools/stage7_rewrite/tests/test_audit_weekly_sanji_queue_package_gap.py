import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_weekly_sanji_queue_package_gap.py"

spec = importlib.util.spec_from_file_location("audit_weekly_sanji_queue_package_gap", SCRIPT)
audit_mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = audit_mod
spec.loader.exec_module(audit_mod)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def run_audit(
    tmp_path,
    queue_rows,
    package_items,
    max_missing=0,
    source_map=None,
    pack_rows=None,
    review_pack_rows=None,
    manifest_extra=None,
    repair_report=None,
    source_policy_repair_report=None,
):
    queue_path = tmp_path / "latest_queue.jsonl"
    api_dir = tmp_path / "api"
    pack_dir = tmp_path / "pack"
    report_path = tmp_path / "gap.json"
    write_jsonl(queue_path, queue_rows)
    write_json(api_dir / "current.json", {"items": package_items})
    manifest = dict(manifest_extra or {})
    if pack_rows is not None or review_pack_rows is not None:
        manifest["source_pack_dir"] = str(pack_dir)
        write_jsonl(pack_dir / "weekly_activity_recommendation_candidates.jsonl", pack_rows or [])
        write_jsonl(pack_dir / "weekly_activity_recommendation_review_candidates.jsonl", review_pack_rows or [])
    if manifest:
        write_json(api_dir / "manifest.json", manifest)
    if source_map is not None:
        write_json(api_dir / "source_actions" / "source_url_map.json", source_map)
    if repair_report is not None:
        write_json(api_dir / "repair_report.json", repair_report)
    if source_policy_repair_report is not None:
        write_json(api_dir / "source_policy_package_repair.json", source_policy_repair_report)
    args = audit_mod.parse_args(
        [
            "--queue",
            str(queue_path),
            "--api-dir",
            str(api_dir),
            "--report",
            str(report_path),
            "--week-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--max-missing",
            str(max_missing),
        ]
    )
    return audit_mod.audit(args)


def test_missing_loopy_future_single_event_blocks(tmp_path):
    url = "https://mp.weixin.qq.com/s/_nroubXFTGv9mXGNZ8Bdzg"
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "loopy Club",
                "title": "6.27 周六｜「酸儿辣女·贵州厨房」全员贵州帮阵容，都别傻站着了！保持躁动！",
                "post_date": "2026-06-17",
                "source_url": url,
            }
        ],
        [],
    )

    assert report["ok"] is False
    assert report["missing_row_count"] == 1
    assert report["missing_rows"][0]["source_hash"] == audit_mod.stable_hash(url)
    assert report["missing_by_account"] == {"loopy Club": 1}


def test_parent_overview_is_excluded_from_activity_gap(tmp_path):
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "loopy Club",
                "title": "loopy Club 端午假期活动一览",
                "post_date": "2026-06-18",
                "source_url": "https://mp.weixin.qq.com/s/overview",
            }
        ],
        [],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 0
    assert report["excluded_reason_counts"]["parent_overview_excluded"] == 1


def test_ep_release_announcement_is_excluded_but_release_party_is_not(tmp_path):
    announcement = audit_mod.classify_row(
        {
            "account_name": "TAGChengdu",
            "title": "Leonwill 发布全新 EP",
            "post_date": "2026-06-19",
            "source_url": "https://mp.weixin.qq.com/s/ep-announcement",
            "body_text": "Techno producer and club DJ released a new record.",
        },
        week_start=audit_mod.date(2026, 6, 19),
        window_end=audit_mod.date(2026, 7, 3),
        source_policy=audit_mod.load_source_policy(audit_mod.DEFAULT_SOURCE_POLICY),
    )
    party = audit_mod.classify_row(
        {
            "account_name": "TAGChengdu",
            "title": "6.19 Leonwill 全新 EP 首发派对",
            "post_date": "2026-06-19",
            "source_url": "https://mp.weixin.qq.com/s/ep-release-party",
            "body_text": "6.19 22:00 Techno DJ Set",
        },
        week_start=audit_mod.date(2026, 6, 19),
        window_end=audit_mod.date(2026, 7, 3),
        source_policy=audit_mod.load_source_policy(audit_mod.DEFAULT_SOURCE_POLICY),
    )

    assert announcement["include"] is False
    assert "non_target_activity_editorial_release" in announcement["exclude_reasons"]
    assert party["include"] is True


def test_holiday_multi_day_parent_overview_is_excluded_from_activity_gap(tmp_path):
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "敲敲电子俱乐部 KNOCK&KNOCKCLUB",
                "title": "【端午三日派对】敲敲爆炒老三样 地三鲜 HOUSE/TECHNO/DISCO 上桌！",
                "post_date": "2026-06-14",
                "source_url": "https://mp.weixin.qq.com/s/holiday-parent",
            }
        ],
        [],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 0
    assert report["excluded_reason_counts"]["parent_overview_excluded"] == 1


def test_source_hash_match_passes(tmp_path):
    url = "https://mp.weixin.qq.com/s/-0nAxRP8ZeZzt_1zojBBBA"
    url_hash = audit_mod.stable_hash(url)
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "loopy Club",
                "title": "今晚，欢迎来到Jasmín的茉莉心房！",
                "post_date": "2026-06-19",
                "source_url": url,
            }
        ],
        [{"id": f"loopy_club:{url_hash}", "title": "今晚，欢迎来到Jasmín的茉莉心房！"}],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 1
    assert report["matched_row_count"] == 1
    assert report["missing_row_count"] == 0


def test_review_flags_account_for_filtered_source_row(tmp_path):
    url = "https://mp.weixin.qq.com/s/filtered-by-llm"
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "院吧 Hakka Bar",
                "title": "06.29 周一｜城市阳台·微醺计划",
                "post_date": "2026-06-29",
                "source_url": url,
            }
        ],
        [],
        pack_rows=[
            {
                "title": "06.29 周一｜城市阳台·微醺计划",
                "source_url": url,
                "review_flags": ["missing_lineup_visible"],
            }
        ],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 1
    assert report["package_matched_row_count"] == 0
    assert report["disposition_accounted_row_count"] == 1
    assert report["disposition_by_reason"] == {"review_flag:missing_lineup_visible": 1}
    assert report["missing_row_count"] == 0


def test_review_disposition_accounts_for_every_deduped_source_alias(tmp_path):
    older_url = "https://mp.weixin.qq.com/s/older-duplicate-source"
    newer_url = "https://mp.weixin.qq.com/s/newer-canonical-source"
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "CaveCave",
                "title": "6.19 周五｜地下电子音乐派对",
                "post_date": "2026-06-19",
                "source_url": older_url,
            }
        ],
        [],
        pack_rows=[
            {
                "title": "6.19 周五｜地下电子音乐派对",
                "source_url": newer_url,
                "_source_aliases": [
                    {
                        "url_hash": audit_mod.stable_hash(older_url),
                        "url": older_url,
                    }
                ],
                "review_flags": ["source_review_needed"],
            }
        ],
    )

    assert report["ok"] is True
    assert report["disposition_accounted_row_count"] == 1
    assert report["disposition_by_reason"] == {"review_flag:source_review_needed": 1}
    assert report["missing_row_count"] == 0


def test_review_pack_not_event_status_accounts_for_filtered_source_row(tmp_path):
    url = "https://mp.weixin.qq.com/s/not-event-review-row"
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "莫须有工舍",
                "title": "开放日放映｜“逻各斯之困”探寻理性之外",
                "post_date": "2026-06-29",
                "source_url": url,
                "body_text": "影片排期 6月29日 20:00",
            }
        ],
        [],
        review_pack_rows=[
            {
                "title": "开放日放映｜“逻各斯之困”探寻理性之外",
                "source_url": url,
                "poster_vl_status": "not_event",
            }
        ],
    )

    assert report["ok"] is True
    assert report["disposition_accounted_row_count"] == 1
    assert report["missing_row_count"] == 0


def test_weekly_date_range_row_is_excluded_from_single_event_gap(tmp_path):
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "WITH BAR",
                "title": "WITH · Stop Motion DJs Weekly｜ 06.29-07.05",
                "post_date": "2026-06-29",
                "source_url": "https://mp.weixin.qq.com/s/weekly-range",
            }
        ],
        [],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 0
    assert report["excluded_reason_counts"]["parent_overview_excluded"] == 1


def test_source_url_map_alias_match_passes_for_deduped_article(tmp_path):
    url = "https://mp.weixin.qq.com/s/deduped-alias"
    url_hash = audit_mod.stable_hash(url)
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "POOLS",
                "title": "06.19 周五｜茶马计划 CHAMA PROJECT #40",
                "post_date": "2026-06-18",
                "source_url": url,
            }
        ],
        [{"id": "pools:canonical", "title": "06.19 周五｜茶马计划 CHAMA PROJECT #40"}],
        source_map={
            "schema_version": "weekly_activity_source_url_map.v1",
            "sources": {
                url_hash: {
                    "type": "wechat_article",
                    "url": url,
                    "event_id": "pools:canonical",
                }
            },
        },
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 1
    assert report["matched_row_count"] == 1
    assert report["missing_row_count"] == 0


def test_publish_timestamp_in_digest_is_not_event_date_signal(tmp_path):
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "OIL油",
                "title": "【预告】OIL七月最重磅：电子乐浪漫美学传奇 SCSI-9 (Live)",
                "post_date": "2026-07-01",
                "source_url": "https://mp.weixin.qq.com/s/oil-preview",
                "digest": "OIL油 2026年7月1日 23:03 限量早鸟及预售票已上架",
            }
        ],
        [],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 0
    assert report["excluded_reason_counts"]["no_current_future_event_date_signal"] == 1


def test_article_and_queue_id_hash_match_passes_for_schedule_split_child(tmp_path):
    url = "https://mp.weixin.qq.com/s/schedule-child"
    url_hash = audit_mod.stable_hash(url)
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "厅Tin",
                "title": "6.19 周五｜质地有声",
                "post_date": "2026-06-19",
                "source_url": url,
            }
        ],
        [
            {
                "id": "tin:canonical",
                "title": "质地有声",
                "article_id": f"tin:{url_hash}",
                "queue_id": f"tin:{url_hash}:schedule:20260619:1",
            }
        ],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 1
    assert report["matched_row_count"] == 1
    assert report["missing_row_count"] == 0


def test_merge_provenance_hash_match_passes_for_deduped_source(tmp_path):
    url = "https://mp.weixin.qq.com/s/deduped-provenance"
    url_hash = audit_mod.stable_hash(url)
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "POTENT",
                "title": "6.19 周五｜OH MY GOD",
                "post_date": "2026-06-19",
                "source_url": url,
            }
        ],
        [
            {
                "id": "potent:canonical",
                "title": "OH MY GOD",
                "merge_provenance": {
                    "schema_version": "weekly_merge_provenance.v1",
                    "merged_source_hashes": [url_hash],
                    "sources": [{"source_hash": url_hash, "event_id": f"potent:{url_hash}"}],
                },
            }
        ],
    )

    assert report["ok"] is True
    assert report["candidate_event_like_row_count"] == 1
    assert report["matched_row_count"] == 1
    assert report["missing_row_count"] == 0


def test_release_repair_removed_item_accounts_for_cross_source_conflict(tmp_path):
    url = "https://mp.weixin.qq.com/s/repaired-conflict"
    url_hash = audit_mod.stable_hash(url)
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "POTENT",
                "title": "6.19 周五｜OH MY GOD",
                "post_date": "2026-06-19",
                "source_url": url,
            }
        ],
        [],
        repair_report={
            "schema_version": "weekly_activity_release_repair.v1",
            "removed_items": [
                {
                    "id": f"potent:{url_hash}",
                    "source_hash": url_hash,
                    "reason": "cross_source_conflict",
                }
            ],
        },
    )

    assert report["ok"] is True
    assert report["package_matched_row_count"] == 0
    assert report["disposition_accounted_row_count"] == 1
    assert report["disposition_by_reason"] == {"release_repair:cross_source_conflict": 1}
    assert report["missing_row_count"] == 0


def test_source_policy_repair_removed_item_accounts_for_intentional_filter(tmp_path):
    url = "https://mp.weixin.qq.com/s/source-policy-filtered"
    url_hash = audit_mod.stable_hash(url)
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "AURORA BJ",
                "title": "6.19 周五｜HIP-HOP 与 DJ 派对",
                "post_date": "2026-06-19",
                "source_url": url,
                "body_text": "TECHNO HOUSE DJ SET",
            }
        ],
        [],
        source_policy_repair_report={
            "schema_version": "weekly_api_package_source_policy_repair.v1",
            "policy_removed_history": [
                {
                    "id": f"aurora_bj:{url_hash}",
                    "reason": "non_target_activity_hiphop",
                }
            ],
        },
    )

    assert report["ok"] is True
    assert report["disposition_accounted_row_count"] == 1
    assert report["disposition_by_reason"] == {
        "release_repair:non_target_activity_hiphop": 1
    }
    assert report["missing_row_count"] == 0


def test_incremental_release_repair_report_accounts_for_merged_final_api(tmp_path):
    url = "https://mp.weixin.qq.com/s/incremental-conflict"
    url_hash = audit_mod.stable_hash(url)
    incremental_dir = tmp_path / "incremental_api"
    write_json(
        incremental_dir / "release_conflict_repair_report.json",
        {
            "schema_version": "weekly_activity_release_repair.v1",
            "removed_items": [
                {
                    "id": f"tin:{url_hash}:schedule:20260619:1",
                    "source_hash": url_hash,
                    "reason": "cross_source_conflict",
                }
            ],
        },
    )
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "厅Tin",
                "title": "6.19 周五｜质地有声",
                "post_date": "2026-06-19",
                "source_url": url,
            }
        ],
        [],
        manifest_extra={"source_incremental_api_dir": str(incremental_dir)},
    )

    assert report["ok"] is True
    assert report["disposition_accounted_row_count"] == 1
    assert report["disposition_by_reason"] == {"release_repair:cross_source_conflict": 1}
    assert report["missing_row_count"] == 0


def test_run_report_release_repair_accounts_for_post_merge_conflict(tmp_path):
    url = "https://mp.weixin.qq.com/s/post-merge-conflict"
    url_hash = audit_mod.stable_hash(url)
    write_json(
        tmp_path / "release_conflict_repair.json",
        {
            "schema_version": "weekly_activity_release_repair.v1",
            "removed_items": [
                {
                    "id": f"potent:{url_hash}",
                    "source_hash": url_hash,
                    "reason": "cross_source_conflict",
                }
            ],
        },
    )
    report = run_audit(
        tmp_path,
        [
            {
                "account_name": "POTENT",
                "title": "6.19 周五｜OH MY GOD",
                "post_date": "2026-06-19",
                "source_url": url,
            }
        ],
        [],
    )

    assert report["ok"] is True
    assert report["disposition_accounted_row_count"] == 1
    assert report["disposition_by_reason"] == {"release_repair:cross_source_conflict": 1}
    assert report["missing_row_count"] == 0
