"""Unit tests for weekly_atlas_bridge observations and privacy compliance."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.stage7_rewrite.weekly_atlas_bridge.observations import (
    _sha256,
    build_observation_row,
    sanitize_openid,
    source_url_hash_for_item,
)


class ObservationTests(unittest.TestCase):
    def test_sanitize_openid_url_params(self) -> None:
        # 测试在 URL 中正确过滤 openid 参数，且不影响其他参数
        url1 = "https://mp.weixin.qq.com/s/abc?openid=oIWs123&other=456"
        url2 = "https://mp.weixin.qq.com/s/abc?other=456&openid=oIWs123"
        url3 = "https://mp.weixin.qq.com/s/abc?openid=oIWs123"
        url4 = "https://mp.weixin.qq.com/s/abc?other=456&OPENID=oIWs123&more=789"
        
        self.assertEqual(sanitize_openid(url1), "https://mp.weixin.qq.com/s/abc?other=456")
        self.assertEqual(sanitize_openid(url2), "https://mp.weixin.qq.com/s/abc?other=456")
        self.assertEqual(sanitize_openid(url3), "https://mp.weixin.qq.com/s/abc")
        self.assertEqual(sanitize_openid(url4), "https://mp.weixin.qq.com/s/abc?other=456&more=789")

    def test_sanitize_openid_text_fallback(self) -> None:
        # 测试文本中零散出现的 openid 敏感词被替换
        text = "This description has an openid in it. User's openid=12345."
        sanitized = sanitize_openid(text)
        self.assertNotIn("openid", sanitized.lower())
        self.assertIn("id_sanitized", sanitized)

    def test_observation_compliance_no_openid_and_hashed_url(self) -> None:
        # 确保生成的 observation row 严格遵守隐私规范：不泄露个人隐私，对 source URL 强制哈希
        item = {
            "event_id": "test:123",
            "source_url": "https://mp.weixin.qq.com/s/some_untrusted_link_with_openid_12345",
            "url": "https://mp.weixin.qq.com/s/some_untrusted_link_with_openid_12345",
            "cover_image_url": "https://mmbiz.qpic.cn/foo/0?wx_fmt=jpeg&openid=abc",
            "description_original_lines": [
                "Tonight's party! Guest list openid=abc.",
                "https://mmbiz.qpic.cn/foo/0?wx_fmt=jpeg",
                "Scan to register, openid: xyz"
            ],
            "title": "OpenID special event",
            "venue": "Club OpenID"
        }
        
        row = build_observation_row(item, publish_package="TEST_PKG")
        
        # 1. 验证整个序列化输出中不包含 "openid"（不区分大小写）
        serialized = json.dumps(row)
        self.assertNotIn("openid", serialized.lower())
        self.assertNotIn("mmbiz.qpic.cn", serialized.lower())
        self.assertNotIn("wx_fmt", serialized.lower())
        
        # 2. 验证 source_url_hash 正确生成并以 'sha256:' 开头
        self.assertTrue(row["source_url_hash"].startswith("sha256:"))
        
        # 3. 验证 source_url_hash 指向的是清洗 openid 后的 URL 哈希值
        expected_cleaned_url = sanitize_openid("https://mp.weixin.qq.com/s/some_untrusted_link_with_openid_12345")
        expected_hash = f"sha256:{_sha256(expected_cleaned_url)}"
        self.assertEqual(row["source_url_hash"], expected_hash)
        
        # 4. 验证 row 中没有存储明文的 source_url 或 url
        self.assertNotIn("source_url", row)
        self.assertNotIn("url", row)
        
        # 5. 验证其他包含 openid 的字段（如 description_lines，title，venue）均已被安全洗涤
        self.assertIn("id_sanitized", serialized)

    def test_source_url_hash_from_source_map(self) -> None:
        item = {
            "event_id": "test:source-map",
            "source_action": {"url_hash": "abc123"},
        }
        source_map = {
            "sources": {
                "abc123": {"url": "https://mp.weixin.qq.com/s/source?openid=secret&x=1"}
            }
        }

        expected_cleaned_url = sanitize_openid("https://mp.weixin.qq.com/s/source?openid=secret&x=1")
        self.assertEqual(
            source_url_hash_for_item(item, source_map),
            f"sha256:{_sha256(expected_cleaned_url)}",
        )

    def test_source_url_hash_falls_back_to_existing_hash(self) -> None:
        item = {
            "event_id": "test:source-hash",
            "source_article": {"url_hash": "deadbeef"},
        }

        self.assertEqual(source_url_hash_for_item(item), "urlhash:deadbeef")


if __name__ == "__main__":
    unittest.main()
