import json
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "enrich_weekly_activity_pack_with_qwen_vl.py"
CANDIDATE_FILE = "weekly_activity_recommendation_candidates.jsonl"
REVIEW_FILE = "weekly_activity_recommendation_review_candidates.jsonl"


def load_vl_module():
    spec = importlib.util.spec_from_file_location("enrich_weekly_activity_pack_with_qwen_vl", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_sanji_article(root: Path) -> Path:
    article_dir = root / "article"
    assets = article_dir / "assets"
    assets.mkdir(parents=True)
    image = assets / "0.png"
    image.write_bytes(b"x" * 20000)
    (image.with_name(image.name + ".meta.json")).write_text(
        json.dumps({"sourceUrl": "https://mmbiz.qpic.cn/main-poster.png", "sha": "asset-sha"}),
        encoding="utf-8",
    )
    (article_dir / "index.html").write_text('<img src="assets/0.png">', encoding="utf-8")
    return article_dir


def test_selfcheck():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--selfcheck"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"ok": true' in result.stdout


def test_quality_defaults_use_stronger_model_and_unlimited_images():
    vl = load_vl_module()
    assert vl.DEFAULT_QWEN_MODEL == "qwen3.6-plus"
    args = vl.parse_args(["--pack-dir", "p", "--weekly-queue", "q", "--out-dir", "o"])
    assert args.max_images == 0
    assert vl.provider_config("qwen3_vl", "qwen3.6-plus").model == "qwen3.6-plus"
    assert vl.provider_extra_body(vl.provider_config("qwen3_vl", "qwen3.6-plus")) == {"enable_thinking": False}
    prompt = vl.build_prompt(
        {"title": "6.21 single event", "event_date_text": ["2026-06-21"]},
        {"title": "source", "body_text": "lineup: A / B / C"},
        [],
    )
    assert "Inspect every attached image" in prompt
    assert "month/week/holiday calendars" in prompt
    assert "full visible DJ/live lineup from all attached images plus the body excerpt" in prompt


def test_max_images_zero_selects_all_images(tmp_path):
    vl = load_vl_module()
    article_dir = tmp_path / "article"
    assets_dir = article_dir / "assets"
    assets_dir.mkdir(parents=True)
    html_parts = []
    for index in range(3):
        image_path = assets_dir / f"{index}.png"
        image_path.write_bytes(b"x" * 20000)
        (image_path.with_name(image_path.name + ".meta.json")).write_text(
            json.dumps({"sourceUrl": f"https://mmbiz.qpic.cn/{index}.png", "sha": f"sha-{index}"}),
            encoding="utf-8",
        )
        html_parts.append(f'<img src="assets/{index}.png">')
    (article_dir / "index.html").write_text("".join(html_parts), encoding="utf-8")

    assert len(vl.select_article_assets(str(article_dir), 0)) == 3
    assert len(vl.select_article_assets(str(article_dir), 2)) == 2


def test_schedule_row_uses_base_sanji_article_dir_and_merges_vl_fields(tmp_path):
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    mock_path = tmp_path / "mock.json"
    base_queue_id = "loopy_club:5331a3c6cb7d1d3f"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": base_queue_id,
                "account_key": "loopy_club",
                "source_url_hash": "5331a3c6cb7d1d3f",
                "article_dir": str(article_dir),
                "title": "6.21 周日 | loopy x Open M pres.夜游 / Off - duty 唱机龙舟",
                "body_text": "2026-06-21 21:00 loopy Club",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": base_queue_id + ":schedule:0",
                "account_key": "loopy_club",
                "source_url_hash": "5331a3c6cb7d1d3f",
                "title": "loopy x Open M pres.夜游 / Off - duty 唱机龙舟",
                "event_date_text": ["2026-06-21"],
                "include_in_activity_feed": True,
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    mock_path.write_text(
        json.dumps(
            {
                "is_event": True,
                "event_title": "loopy x Open M pres.夜游 / Off - duty 唱机龙舟",
                "date_start": "2026-06-21",
                "time_text": "21:00",
                "city": "杭州",
                "venue": "loopy",
                "address": "杭州市西湖区转塘街道创意路",
                "lineup": ["Lineup", "Off-duty", "OFF DUTY", "DJ Off-duty", "Noizome / Jasmin"],
                "lineup_evidence": ["poster text: Off-duty"],
                "music_styles": ["electronic"],
                "price": ["presale"],
                "ticketing_text": "see original article",
                "main_poster_image_index": 0,
                "visible_text_lines": ["2026-06-21", "loopy"],
                "evidence": ["date and venue visible"],
                "risk_flags": [],
                "confidence": 0.91,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--mock-response",
            str(mock_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    out_rows = [json.loads(line) for line in (out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").splitlines()]
    assert len(out_rows) == 1
    row = out_rows[0]
    assert row["event_date_text"] == ["2026-06-21"]
    assert row["event_time_text"] == "21:00"
    assert row["venue"] == ["loopy"]
    assert row["poster_vl_lineup"] == ["Off-duty", "Noizome", "Jasmin"]
    assert row["lineup_artists"] == ["Off-duty", "Noizome", "Jasmin"]
    assert row["poster_vl_lineup_evidence"] == ["poster text: Off-duty"]
    assert row["cover_url"] == "https://mmbiz.qpic.cn/main-poster.png"
    assert row["poster_selection_evidence"]["selected_by"] == "qwen_vl_direct_sanji_article_assets"
    assert row["poster_selection_evidence"]["cleaned_lineup"] == ["Off-duty", "Noizome", "Jasmin"]
    assert row["poster_selection_evidence"]["lineup_evidence"] == ["poster text: Off-duty"]
    assert Path(row["source_evidence_path"]).exists()


def test_execute_requires_primary_qwen_provider_when_fallback_succeeds(tmp_path, monkeypatch):
    vl = load_vl_module()
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    source_hash = "39e8988f674671c1"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "article_dir": str(article_dir),
                "title": "6.27 周六 | 酸儿辣女",
                "body_text": "2026-06-27 21:00 loopy Club lineup: Endy / Jerry / Golgol",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "title": "6.27 周六 | 酸儿辣女",
                "event_date_text": ["2026-06-27"],
                "include_in_activity_feed": True,
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-qwen")
    monkeypatch.setenv("MIMO_API_KEY", "test-mimo")

    def fake_call(provider, prompt, assets, timeout_sec, retries):
        if provider.name == "qwen3_vl":
            raise RuntimeError("forced qwen failure")
        assert provider.name == "mimo"
        return {
            "is_event": True,
            "event_title": "酸儿辣女",
            "date_start": "2026-06-27",
            "time_text": "21:00",
            "city": "杭州",
            "venue": "loopy",
            "lineup": ["Endy", "Jerry", "Golgol"],
            "lineup_evidence": ["poster text: Endy / Jerry / Golgol"],
            "main_poster_image_index": 0,
            "visible_text_lines": ["2026-06-27", "loopy", "Endy", "Jerry", "Golgol"],
            "evidence": ["date, venue, and lineup are visible"],
            "risk_flags": [],
            "confidence": 0.93,
        }

    monkeypatch.setattr(vl, "call_openai_compatible_vl", fake_call)
    args = vl.parse_args(
        [
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--provider",
            "qwen3_vl",
            "--model",
            "qwen3.6-plus",
            "--fallback-provider",
            "mimo",
            "--execute",
        ]
    )

    assert vl.run(args) == 3
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["providers"] == {"mimo": 1}
    assert summary["primary_provider_count"] == 0
    assert summary["fallback_count"] == 1
    assert summary["fallback_ratio"] == 1.0
    assert summary["max_fallback_ratio"] == 0.2
    assert summary["primary_provider_required"] is True
    assert summary["primary_provider_gate_ok"] is False
    assert "qwen3_vl/qwen3.6-plus" in summary["primary_provider_gate_reason"]


def test_execute_require_primary_rejects_missing_primary_key_before_any_provider_call(tmp_path, monkeypatch):
    vl = load_vl_module()
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    source_hash = "missingprimary001"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "article_dir": str(article_dir),
                "title": "6.29 周一 | Primary Gate",
                "body_text": "2026-06-29 21:00 loopy Club lineup: A / B / C",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "title": "6.29 周一 | Primary Gate",
                "event_date_text": ["2026-06-29"],
                "include_in_activity_feed": True,
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    for name in (
        "ATLAS_DASHSCOPE_API_KEY",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_COMPATIBLE_API_KEY",
        "QWEN_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MIMO_API_KEY", "test-mimo")

    provider_calls = []

    def fake_call(provider, prompt, assets, timeout_sec, retries):
        provider_calls.append(provider.name)
        if provider.name == "qwen3_vl":
            raise RuntimeError("qwen3_vl API key is not configured in environment")
        return {
            "is_event": True,
            "event_title": "Primary Gate",
            "date_start": "2026-06-29",
            "time_text": "21:00",
            "city": "杭州",
            "venue": "loopy",
            "lineup": ["A", "B", "C"],
            "main_poster_image_index": 0,
            "confidence": 0.9,
        }

    monkeypatch.setattr(vl, "call_openai_compatible_vl", fake_call)
    args = vl.parse_args(
        [
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--provider",
            "qwen3_vl",
            "--fallback-provider",
            "mimo",
            "--require-primary-provider",
            "--execute",
        ]
    )

    error = None
    try:
        vl.run(args)
    except RuntimeError as exc:
        error = str(exc)

    assert error is not None, (
        "require-primary must reject a missing primary key; the old behavior completed entirely on MiMo"
    )
    assert "required primary provider qwen3_vl/qwen3.6-plus" in error
    assert "API key is not configured" in error
    assert provider_calls == [], "the primary-key gate must run before any paid provider call"


def test_execute_records_exact_qwen_vl_usage_cost(tmp_path, monkeypatch):
    vl = load_vl_module()
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    source_hash = "a1b2c3d4e5f60718"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "article_dir": str(article_dir),
                "title": "6.28 周日 | Cost Test",
                "body_text": "2026-06-28 21:00 loopy Club lineup: A / B / C",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "title": "6.28 周日 | Cost Test",
                "event_date_text": ["2026-06-28"],
                "include_in_activity_feed": True,
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-qwen")

    def fake_call(provider, prompt, assets, timeout_sec, retries):
        assert provider.name == "qwen3_vl"
        return {
            "is_event": True,
            "event_title": "Cost Test",
            "date_start": "2026-06-28",
            "time_text": "21:00",
            "city": "杭州",
            "venue": "loopy",
            "lineup": ["A", "B", "C"],
            "lineup_evidence": ["poster text: A / B / C"],
            "main_poster_image_index": 0,
            "visible_text_lines": ["2026-06-28", "loopy", "A", "B", "C"],
            "evidence": ["date, venue, and lineup are visible"],
            "risk_flags": [],
            "confidence": 0.94,
            "__vl_usage": {
                "prompt_tokens": 40_000,
                "completion_tokens": 10_000,
                "total_tokens": 50_000,
                "model": "qwen3.6-plus",
            },
        }

    monkeypatch.setattr(vl, "call_openai_compatible_vl", fake_call)
    args = vl.parse_args(
        [
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--provider",
            "qwen3_vl",
            "--model",
            "qwen3.6-plus",
            "--execute",
        ]
    )

    assert vl.run(args) == 0
    usage_summary = json.loads((out_dir / "poster_vl_usage_summary.json").read_text(encoding="utf-8"))
    assert usage_summary["exact_available"] is True
    assert usage_summary["call_count"] == 1
    assert usage_summary["prompt_tokens"] == 40_000
    assert usage_summary["completion_tokens"] == 10_000
    assert usage_summary["cost_cny"] == 0.2
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["poster_vl_cost_cny"] == 0.2
    details = [json.loads(line) for line in (out_dir / "poster_vl_usage_details.jsonl").read_text(encoding="utf-8").splitlines()]
    assert details[0]["tier"] == "0<Token<=256K"
    assert details[0]["queue_id_hash"]
    assert "loopy_club" not in json.dumps(details, ensure_ascii=False)


def test_outside_window_row_is_copied_without_vl(tmp_path):
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    mock_path = tmp_path / "mock.json"

    write_jsonl(
        queue_path,
        [{"queue_id": "x:1", "article_dir": str(article_dir), "title": "old event"}],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [{"queue_id": "x:1", "title": "old event", "event_date_text": ["2026-05-01"]}],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    mock_path.write_text(json.dumps({"date_start": "2026-05-01"}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--mock-response",
            str(mock_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    row = json.loads((out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").strip())
    assert "poster_selection_evidence" not in row
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["processed"] == 0


def test_published_source_hash_is_skipped_before_vl(tmp_path):
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    published_dir = tmp_path / "published"
    source_hash = "5331a3c6cb7d1d3f"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "article_dir": str(article_dir),
                "title": "6.21 周日 | loopy x Open M pres.夜游",
                "body_text": "2026-06-21 21:00 loopy Club",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": f"loopy_club:{source_hash}:schedule:0",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "title": "loopy x Open M pres.夜游",
                "event_date_text": ["2026-06-21"],
                "include_in_activity_feed": True,
                "lineup": ["Endy", "Jerry", "Golgol"],
                "poster_selection_evidence": {"selected_by": "fixture", "main_poster_image_index": 0},
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    (published_dir / "source_actions").mkdir(parents=True)
    (published_dir / "current.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": f"loopy_club:{source_hash}",
                        "source_url_hash": source_hash,
                        "lineup": ["Endy", "Jerry", "Golgol"],
                        "poster_selection_evidence": {"selected_by": "fixture", "main_poster_image_index": 0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (published_dir / "source_actions" / "source_url_map.json").write_text(
        json.dumps({"sources": {source_hash: {"url": "https://mp.weixin.qq.com/s/existing"}}}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--published-api-dir",
            str(published_dir),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    row = json.loads((out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").strip())
    assert row["poster_vl_status"] == "skipped_already_published"
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["processed"] == 0
    assert summary["skipped_already_published"] == 1
    assert summary["published_quality_gap"] == 0
    routing_rows = [
        json.loads(line)
        for line in (out_dir / "routing_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert routing_rows[0]["bucket"] == "easy_rule"
    assert routing_rows[0]["reason"] == "already_published_source_hash_quality_complete"


def test_published_quality_complete_but_candidate_missing_evidence_is_sent_to_vl(tmp_path):
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    published_dir = tmp_path / "published"
    mock_path = tmp_path / "mock.json"
    source_hash = "9db7663f3fbc7fed"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": f"hakka_bar:{source_hash}",
                "account_key": "hakka_bar",
                "source_url_hash": source_hash,
                "article_dir": str(article_dir),
                "title": "HYBRID BEATS · RUNDO农（Live）",
                "body_text": "2026-06-21 Hakkabar RUNDO农 Live",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": f"hakka_bar:{source_hash}",
                "account_key": "hakka_bar",
                "source_url_hash": source_hash,
                "title": "HYBRID BEATS · RUNDO农（Live）",
                "event_date_text": ["2026-06-21"],
                "include_in_activity_feed": True,
                "lineup": ["RUNDO农"],
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    (published_dir / "source_actions").mkdir(parents=True)
    (published_dir / "current.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": f"hakka_bar:{source_hash}",
                        "source_url_hash": source_hash,
                        "lineup": ["RUNDO农"],
                        "poster_selection_evidence": {
                            "selected_by": "fixture",
                            "main_poster_image_index": 0,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (published_dir / "source_actions" / "source_url_map.json").write_text(
        json.dumps({"sources": {source_hash: {"url": "https://mp.weixin.qq.com/s/existing"}}}),
        encoding="utf-8",
    )
    mock_path.write_text(
        json.dumps(
            {
                "is_event": True,
                "event_title": "HYBRID BEATS · RUNDO农（Live）",
                "date_start": "2026-06-21",
                "time_text": "21:00",
                "city": "成都",
                "venue": "Hakkabar 院吧",
                "lineup": ["RUNDO农"],
                "lineup_evidence": ["poster text: RUNDO 农 (Live)"],
                "main_poster_image_index": 0,
                "visible_text_lines": ["HYBRID BEATS", "RUNDO 农 (Live)"],
                "evidence": ["title and lineup are visible"],
                "risk_flags": [],
                "confidence": 0.9,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--published-api-dir",
            str(published_dir),
            "--mock-response",
            str(mock_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    row = json.loads((out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").strip())
    assert row["poster_vl_lineup"] == ["RUNDO农"]
    assert row["poster_selection_evidence"]["selected_by"] == "qwen_vl_direct_sanji_article_assets"
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["processed"] == 1
    assert summary["skipped_already_published"] == 0
    assert summary["published_quality_gap"] == 1
    routing_rows = [
        json.loads(line)
        for line in (out_dir / "routing_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert routing_rows[0]["bucket"] == "hard_pro"
    assert routing_rows[0]["reason"] == "published_source_quality_gap"


def test_published_source_hash_with_quality_gap_is_sent_to_vl(tmp_path):
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    published_dir = tmp_path / "published"
    mock_path = tmp_path / "mock.json"
    source_hash = "39e8988f674671c1"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "article_dir": str(article_dir),
                "title": "6.27 周六 | 酸儿辣女",
                "body_text": "2026-06-27 21:00 loopy Club lineup: Endy / Jerry / Golgol",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": f"loopy_club:{source_hash}",
                "account_key": "loopy_club",
                "source_url_hash": source_hash,
                "title": "6.27 周六 | 酸儿辣女",
                "event_date_text": ["2026-06-27"],
                "include_in_activity_feed": True,
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    (published_dir / "source_actions").mkdir(parents=True)
    (published_dir / "current.json").write_text(
        json.dumps({"items": [{"id": f"loopy_club:{source_hash}", "source_url_hash": source_hash}]}),
        encoding="utf-8",
    )
    (published_dir / "source_actions" / "source_url_map.json").write_text(
        json.dumps({"sources": {source_hash: {"url": "https://mp.weixin.qq.com/s/existing"}}}),
        encoding="utf-8",
    )
    mock_path.write_text(
        json.dumps(
            {
                "is_event": True,
                "event_title": "酸儿辣女",
                "date_start": "2026-06-27",
                "time_text": "21:00",
                "city": "杭州",
                "venue": "loopy",
                "lineup": ["Endy", "Jerry", "Golgol"],
                "lineup_evidence": ["poster text: Endy / Jerry / Golgol"],
                "main_poster_image_index": 0,
                "visible_text_lines": ["2026-06-27", "loopy", "Endy", "Jerry", "Golgol"],
                "evidence": ["date, venue, and lineup are visible"],
                "risk_flags": [],
                "confidence": 0.93,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--published-api-dir",
            str(published_dir),
            "--mock-response",
            str(mock_path),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    row = json.loads((out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").strip())
    assert row["poster_vl_lineup"] == ["Endy", "Jerry", "Golgol"]
    assert row["poster_selection_evidence"]["selected_by"] == "qwen_vl_direct_sanji_article_assets"
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["processed"] == 1
    assert summary["skipped_already_published"] == 0
    assert summary["published_quality_gap"] == 1
    routing_rows = [
        json.loads(line)
        for line in (out_dir / "routing_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert routing_rows[0]["bucket"] == "hard_pro"
    assert routing_rows[0]["reason"] == "published_source_quality_gap"


def test_missing_sanji_assets_is_nonfatal_and_keeps_candidate(tmp_path):
    article_dir = tmp_path / "article"
    (article_dir / "assets").mkdir(parents=True)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    mock_path = tmp_path / "mock.json"

    write_jsonl(
        queue_path,
        [{"queue_id": "loopy_club:noimage", "article_dir": str(article_dir), "title": "no image event"}],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [
            {
                "queue_id": "loopy_club:noimage",
                "title": "no image event",
                "event_date_text": ["2026-06-21"],
                "include_in_activity_feed": True,
            }
        ],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    mock_path.write_text(json.dumps({"date_start": "2026-06-21"}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--pack-dir",
            str(pack_dir),
            "--weekly-queue",
            str(queue_path),
            "--out-dir",
            str(out_dir),
            "--window-start",
            "2026-06-19",
            "--window-days",
            "15",
            "--mock-response",
            str(mock_path),
            "--execute",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    row = json.loads((out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").strip())
    assert row["poster_vl_status"] == "skipped_missing_assets"
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["missing_assets"] == 1
    assert summary["failures"] == 0


def test_parallel_resume_reuses_valid_evidence_without_api_call(tmp_path, monkeypatch):
    vl = load_vl_module()
    article_dir = make_sanji_article(tmp_path)
    pack_dir = tmp_path / "pack"
    out_dir = tmp_path / "out"
    queue_path = tmp_path / "queue.jsonl"
    mock_path = tmp_path / "mock.json"
    queue_id = "resume_test:abc123"

    write_jsonl(
        queue_path,
        [
            {
                "queue_id": queue_id,
                "article_dir": str(article_dir),
                "title": "Recovered event",
                "body_text": "2026-07-11",
            }
        ],
    )
    write_jsonl(
        pack_dir / CANDIDATE_FILE,
        [{"queue_id": queue_id, "title": "Recovered event", "event_date_text": ["2026-07-11"], "include_in_activity_feed": True}],
    )
    write_jsonl(pack_dir / REVIEW_FILE, [])
    mock_path.write_text(json.dumps({"is_event": True}), encoding="utf-8")

    evidence_dir = out_dir / "source_evidence"
    evidence_dir.mkdir(parents=True)
    parsed = {
        "is_event": True,
        "event_title": "Recovered event",
        "date_start": "2026-07-11",
        "lineup": ["Recovered DJ"],
        "main_poster_image_index": 0,
        "visible_text_lines": ["Recovered event"],
        "evidence": ["recovered checkpoint"],
        "risk_flags": [],
        "confidence": 0.99,
    }
    (evidence_dir / "resume_test.qwen_vl.md").write_text(
        "# Weekly Sanji VL Evidence\n\n"
        f"- queue_id: `{queue_id}`\n\n"
        "## Parsed JSON\n```json\n"
        + json.dumps(parsed, ensure_ascii=False)
        + "\n```\n",
        encoding="utf-8",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("resume evidence should prevent an API call")

    monkeypatch.setattr(vl, "call_openai_compatible_vl", fail_if_called)
    args = vl.parse_args(
        [
            "--pack-dir", str(pack_dir),
            "--weekly-queue", str(queue_path),
            "--out-dir", str(out_dir),
            "--window-start", "2026-07-11",
            "--mock-response", str(mock_path),
            "--concurrency", "4",
            "--resume-from-evidence-dir", str(evidence_dir),
        ]
    )

    assert vl.run(args) == 0
    output = [json.loads(line) for line in (out_dir / CANDIDATE_FILE).read_text(encoding="utf-8").splitlines() if line]
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert output[0]["poster_vl_lineup"] == ["Recovered DJ"]
    assert summary["resumed_from_evidence"] == 1
    assert summary["enriched"] == 1


def test_load_evidence_checkpoint_ignores_missing_or_malformed_evidence(tmp_path):
    vl = load_vl_module()
    assert vl.load_evidence_checkpoint(tmp_path / "does-not-exist") == {}

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "malformed.qwen_vl.md").write_text(
        "# Weekly Sanji VL Evidence\n- queue_id: `bad:1`\n## Parsed JSON\n```json\nnot-json\n```\n",
        encoding="utf-8",
    )
    assert vl.load_evidence_checkpoint(evidence_dir) == {}
