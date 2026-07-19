from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from weekly_public_projection import (  # noqa: E402
    find_public_payload_leaks,
    local_path_reason,
    project_public_item,
    project_public_source_map_payload,
    public_package_json_paths,
    scrub_public_value,
)


def test_path_gate_catches_object_keys_file_urls_and_wrapped_local_paths() -> None:
    payload = {
        "field_evidence_refs": {
            "/home/win/private/evidence.json": "value",
            r"C:\Users\win\private\evidence.json": "value",
        },
        "file_url": "file:///home/win/private/article.html",
        "wrapped_windows": r"https://example.invalid/x?debug=C:\Users\win\private\trace.json",
        "wrapped_posix": "https://example.invalid/x?debug=/home/win/private/trace.json",
    }

    findings = find_public_payload_leaks(payload)
    reasons = {finding["reason"] for finding in findings}
    assert "object_key_posix_absolute_path" in reasons
    assert "object_key_windows_absolute_path" in reasons
    assert "file_url" in reasons
    assert "windows_absolute_path" in reasons
    assert "posix_absolute_path" in reasons

    scrubbed = scrub_public_value(payload)
    assert scrubbed == {"field_evidence_refs": {}}


@pytest.mark.parametrize(
    "url",
    [
        "file:///home/win/private/article.html",
        r"https://example.invalid/x?debug=C:\Users\win\private\trace.json",
        "https://example.invalid/x?debug=/home/win/private/trace.json",
        "ftp://example.invalid/article",
        "http://localhost/private/article",
    ],
)
def test_source_map_projection_rejects_non_public_urls(url: str) -> None:
    payload = {
        "schema_version": "weekly_activity_source_url_map.v1",
        "sources": {"aaaaaaaaaaaaaaaa": {"type": "wechat_article", "url": url}},
    }
    with pytest.raises(ValueError, match="unsafe public URL"):
        project_public_source_map_payload(payload)


def test_source_map_projection_keeps_only_reviewed_fields_and_http_url() -> None:
    projected = project_public_source_map_payload(
        {
            "schema_version": "weekly_activity_source_url_map.v1",
            "generated_at": "2026-07-19T00:00:00+08:00",
            "source_count": 99,
            "sources": {
                "aaaaaaaaaaaaaaaa": {
                    "type": "wechat_article",
                    "url": "https://mp.weixin.qq.com/s/public-source",
                    "event_id": "event-a",
                    "debug_trace": "must not publish",
                }
            },
        }
    )

    assert projected["source_count"] == 1
    assert projected["sources"]["aaaaaaaaaaaaaaaa"] == {
        "event_id": "event-a",
        "type": "wechat_article",
        "url": "https://mp.weixin.qq.com/s/public-source",
    }


def test_item_projection_removes_non_http_nested_source_urls() -> None:
    projected = project_public_item(
        {
            "id": "event-a",
            "source_action": {"url_hash": "a" * 16, "url": "file:///home/private/article.html"},
            "source_article": {"url_hash": "a" * 16, "url": "ftp://example.invalid/article"},
        }
    )
    assert projected["source_action"] == {"url_hash": "a" * 16}
    assert projected["source_article"] == {"url_hash": "a" * 16}


def test_public_package_paths_include_source_map_and_filter_dispositions(tmp_path: Path) -> None:
    for relative in (
        "current.json",
        "manifest.json",
        "source_actions/source_url_map.json",
        "build_filter_dispositions.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    relatives = {
        path.relative_to(tmp_path).as_posix()
        for path in public_package_json_paths(tmp_path)
    }
    assert "source_actions/source_url_map.json" in relatives
    assert "build_filter_dispositions.json" in relatives


def test_public_routes_and_urls_are_not_misclassified_as_local_paths() -> None:
    for value in (
        "https://example.com/atlas/dj/alpha",
        "/api/v1/weekly/current",
        "/atlas/starmap/alpha",
        "by-id/event-a.json",
    ):
        assert local_path_reason(value) == ""
    assert local_path_reason("/assets/../../home/private.json") == "posix_absolute_path"
