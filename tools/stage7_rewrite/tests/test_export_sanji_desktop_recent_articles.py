import datetime as dt
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_sanji_desktop_recent_articles.py"


def load_exporter_module():
    spec = importlib.util.spec_from_file_location("export_sanji_desktop_recent_articles", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_sanji_manifest_uses_only_fetched_article_files(tmp_path):
    sanji_root = tmp_path / "sanji"
    article_dir = sanji_root / "articles" / "fakeid1" / "aid1"
    article_dir.mkdir(parents=True)
    (article_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (article_dir / "index.html.meta.json").write_text("{}", encoding="utf-8")
    deleted_dir = sanji_root / "articles" / "fakeid1" / "aid3"
    deleted_dir.mkdir(parents=True)
    (deleted_dir / "index.html").write_text("该内容已被发布者删除", encoding="utf-8")

    db_path = sanji_root / "sanji.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE wechat_account (
          fakeid TEXT PRIMARY KEY,
          nickname TEXT,
          alias TEXT
        );
        CREATE TABLE wechat_article (
          account_fakeid TEXT,
          aid TEXT,
          msgid TEXT,
          itemidx INTEGER,
          link TEXT,
          title TEXT,
          digest TEXT,
          cover TEXT,
          create_time INTEGER,
          publish_time INTEGER,
          article_type INTEGER,
          is_deleted INTEGER,
          author TEXT,
          is_original INTEGER,
          media_duration INTEGER,
          album_id TEXT,
          album_name TEXT,
          is_paid INTEGER,
          fetched_at INTEGER,
          content_fetched INTEGER,
          content_path TEXT,
          content_size INTEGER,
          content_fetched_at INTEGER,
          content_error TEXT,
          fetch_status TEXT,
          fetch_retry_count INTEGER,
          content_resources_failed INTEGER,
          comment_fetched INTEGER,
          read_num INTEGER,
          like_num INTEGER,
          old_like_num INTEGER,
          share_num INTEGER,
          comment_count INTEGER,
          reward_num INTEGER,
          html_path TEXT,
          html_fetched_at INTEGER,
          resource_retry_count INTEGER
        );
        """
    )
    now = int(dt.datetime.now().timestamp())
    con.execute("INSERT INTO wechat_account VALUES (?, ?, ?)", ("fakeid1", "Account One", "acc1"))
    con.execute(
        """
        INSERT INTO wechat_article VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            "fakeid1",
            "aid1",
            "msg1",
            1,
            "https://example.com/a",
            "Fetched title",
            "digest",
            "cover",
            now,
            now,
            9,
            0,
            "author",
            0,
            0,
            None,
            None,
            0,
            now,
            1,
            r"articles\fakeid1\aid1\index.html",
            123,
            now,
            None,
            "ok",
            0,
            0,
            0,
            1,
            2,
            0,
            3,
            4,
            0,
            None,
            None,
            0,
        ),
    )
    con.execute(
        """
        INSERT INTO wechat_article VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            "fakeid1",
            "aid3",
            "msg3",
            1,
            "https://example.com/deleted",
            "Deleted title",
            "deleted digest",
            "cover",
            now,
            now,
            9,
            1,
            "author",
            0,
            0,
            None,
            None,
            0,
            now,
            1,
            r"articles\fakeid1\aid3\index.html",
            123,
            now,
            None,
            "deleted",
            0,
            0,
            0,
            1,
            2,
            0,
            3,
            4,
            0,
            None,
            None,
            0,
        ),
    )
    con.execute(
        """
        INSERT INTO wechat_article VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            "fakeid1",
            "aid2",
            "msg2",
            1,
            "https://example.com/b",
            "Unfetched title",
            None,
            None,
            now,
            now,
            9,
            0,
            None,
            0,
            0,
            None,
            None,
            0,
            None,
            0,
            None,
            None,
            None,
            "captcha",
            "captcha",
            1,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
        ),
    )
    con.commit()
    con.close()

    out_root = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--sanji-root",
            str(sanji_root),
            "--out-root",
            str(out_root),
            "--lookback-days",
            "2",
            "--run-label",
            "test",
            "--write-latest",
            "--write-prefetch-queue",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    summary = json.loads(result.stdout)
    assert summary["exported_rows"] == 1
    assert summary["skipped_rows"]["unfetched"] == 1
    assert summary["skipped_rows"]["deleted_or_unavailable"] == 1
    assert summary["source"] == "sanji_desktop"
    assert summary["sanji_db_snapshot_export"] is True
    assert summary["snapshot_db_path"].endswith("sanji.db")
    assert summary["rss_contract"]["direct_rss_feed_fetch"] is False
    assert summary["rss_contract"]["sanji_db_snapshot_export"] is True
    assert summary["rss_contract"]["sanji_desktop_refresh_invoked"] is False

    rows = [json.loads(line) for line in (out_root / "test" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["title"] == "Fetched title"
    assert rows[0]["html_exists"] is True
    assert (out_root / "latest_summary.json").exists()
    assert (out_root / "summary.json").exists()
    assert (out_root / "latest_queue.jsonl").exists()

    queue_rows = [
        json.loads(line)
        for line in (out_root / "test" / "latest_queue.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(queue_rows) == 1
    assert queue_rows[0]["account_key"] == "acc1"
    assert queue_rows[0]["source_url"] == "https://example.com/a"
    assert queue_rows[0]["post_date"]
    assert queue_rows[0]["discovery_source"] == "sanji-desktop-rss"
    assert queue_rows[0]["body_text_source"] == "sanji_desktop_html"


def test_jsonl_dump_sanitizes_unicode_line_separators(tmp_path):
    exporter = load_exporter_module()
    out = tmp_path / "rows.jsonl"

    exporter.jsonl_dump(out, [{"title": "a\u2028b", "nested": {"text": "c\u2029d"}}])

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["title"] == "a\nb"
    assert row["nested"]["text"] == "c\nd"


def test_resolve_source_html_path_falls_back_to_hot_articles_root(tmp_path):
    exporter = load_exporter_module()
    sanji_root = tmp_path / "sanji"
    hot_articles_root = tmp_path / "hot" / "articles"
    hot_html = hot_articles_root / "fakeid1" / "aid1" / "index.html"
    hot_html.parent.mkdir(parents=True)
    hot_html.write_text("<html>hot storage</html>", encoding="utf-8")

    resolved = exporter.resolve_source_html_path(
        sanji_root,
        hot_articles_root,
        r"articles\fakeid1\aid1\index.html",
    )

    assert resolved == hot_html
    assert exporter.source_article_dir(
        sanji_root,
        hot_articles_root,
        r"articles\fakeid1\aid1\index.html",
    ) == hot_html.parent


def test_export_sanji_prefetch_queue_uses_weekly_registry_mapping(tmp_path):
    sanji_root = tmp_path / "sanji"
    article_dir = sanji_root / "articles" / "fakeid1" / "aid1"
    article_dir.mkdir(parents=True)
    (article_dir / "index.html").write_text("<html>event body</html>", encoding="utf-8")

    db_path = sanji_root / "sanji.db"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE wechat_account (
          fakeid TEXT PRIMARY KEY,
          nickname TEXT,
          alias TEXT
        );
        CREATE TABLE wechat_article (
          account_fakeid TEXT,
          aid TEXT,
          msgid TEXT,
          itemidx INTEGER,
          link TEXT,
          title TEXT,
          digest TEXT,
          cover TEXT,
          create_time INTEGER,
          publish_time INTEGER,
          article_type INTEGER,
          is_deleted INTEGER,
          author TEXT,
          is_original INTEGER,
          media_duration INTEGER,
          album_id TEXT,
          album_name TEXT,
          is_paid INTEGER,
          fetched_at INTEGER,
          content_fetched INTEGER,
          content_path TEXT,
          content_size INTEGER,
          content_fetched_at INTEGER,
          content_error TEXT,
          fetch_status TEXT,
          fetch_retry_count INTEGER,
          content_resources_failed INTEGER,
          comment_fetched INTEGER,
          read_num INTEGER,
          like_num INTEGER,
          old_like_num INTEGER,
          share_num INTEGER,
          comment_count INTEGER,
          reward_num INTEGER,
          html_path TEXT,
          html_fetched_at INTEGER,
          resource_retry_count INTEGER
        );
        """
    )
    now = int(dt.datetime.now().timestamp())
    con.execute("INSERT INTO wechat_account VALUES (?, ?, ?)", ("fakeid1", "Account One", "acc1"))
    con.execute(
        """
        INSERT INTO wechat_article VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            "fakeid1",
            "aid1",
            "msg1",
            1,
            "https://example.com/a",
            "Fetched title",
            "digest",
            "cover",
            now,
            now,
            9,
            0,
            "author",
            0,
            0,
            None,
            None,
            0,
            now,
            1,
            r"articles\fakeid1\aid1\index.html",
            123,
            now,
            None,
            "ok",
            0,
            0,
            0,
            1,
            2,
            0,
            3,
            4,
            0,
            None,
            None,
            0,
        ),
    )
    con.commit()
    con.close()

    registry = tmp_path / "weekly_accounts_seed.json"
    registry.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "fakeid": "fakeid1",
                        "account_id": "mapped_account",
                        "account_name": "Mapped Account",
                        "city_key": "shanghai",
                        "status": "active",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    out_root = tmp_path / "out"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--sanji-root",
            str(sanji_root),
            "--out-root",
            str(out_root),
            "--lookback-days",
            "2",
            "--run-label",
            "test",
            "--weekly-registry",
            str(registry),
            "--write-prefetch-queue",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    queue_rows = [
        json.loads(line)
        for line in (out_root / "test" / "latest_queue.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert queue_rows[0]["account_key"] == "mapped_account"
    assert queue_rows[0]["account_nickname"] == "Account One"
    assert queue_rows[0]["account_city_key"] == "shanghai"
