"""Unit tests for weekly_atlas_bridge resolver."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.stage7_rewrite.weekly_atlas_bridge.indexes import (
    ArtistRecord,
    MatchIndex,
    load_registry_seed,
)
from tools.stage7_rewrite.weekly_atlas_bridge.resolver import EntityResolver


REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY = REPO_ROOT / "tools/stage7_rewrite/registries/weekly_artists_seed.json"


class ResolverTests(unittest.TestCase):
    def test_registry_exact_show(self) -> None:
        registry = load_registry_seed(REGISTRY)
        resolver = EntityResolver(index=registry)
        result = resolver.resolve("Farhan")
        self.assertEqual(result.match_method, "registry_exact")
        self.assertEqual(result.display_tier, "show")
        self.assertEqual(result.artist_id, "atlas:entity:farhan")

    def test_vector_candidate_never_show(self) -> None:
        index = MatchIndex()
        index.add(
            ArtistRecord(
                artist_id="atlas:entity:other",
                canonical_name="Other DJ",
                verified=False,
            )
        )
        resolver = EntityResolver(index=index)

        class FakeVector:
            collection = "person_current"

            def review(self, raw: str, **kwargs):
                from tools.stage7_rewrite.weekly_atlas_bridge.indexes import VectorReviewHit

                return VectorReviewHit(
                    point_id="pt-1",
                    score=0.97,
                    label="Ghost Artist",
                    payload={},
                )

        resolver.vector_review = FakeVector()
        result = resolver.resolve("Ghost Artist")
        self.assertEqual(result.match_method, "vector_candidate")
        self.assertEqual(result.display_tier, "hide")
        self.assertIsNone(result.artist_id)

    def test_fuzzy_multiple_hint_only(self) -> None:
        index = MatchIndex()
        index.add(
            ArtistRecord(
                artist_id="atlas:entity:a",
                canonical_name="DJ Alpha",
                verified=False,
            ),
            "DJ Alpha",
        )
        index.add(
            ArtistRecord(
                artist_id="atlas:entity:b",
                canonical_name="DJ Alph",
                verified=False,
            ),
            "DJ Alph",
        )
        resolver = EntityResolver(index=index)
        result = resolver.resolve("DJ Alpha")
        self.assertIn(result.match_method, ("registry_exact", "fuzzy_multiple"))
        if result.match_method == "fuzzy_multiple":
            self.assertEqual(result.display_tier, "show_with_hint")
            self.assertIsNone(result.artist_id)

    def test_alias_exact_and_multiple_candidates(self) -> None:
        index = MatchIndex()
        # 模拟图谱多候选冲突
        index.add(ArtistRecord("atlas:entity:slikback_1", "Slikback", True), "Slikback")
        index.add(ArtistRecord("atlas:entity:slikback_2", "Slikback KE", False), "Slikback")
        
        resolver = EntityResolver(index=index)
        result = resolver.resolve("Slikback")
        self.assertEqual(result.match_method, "fuzzy_multiple")
        self.assertEqual(result.display_tier, "show_with_hint")
        self.assertIsNone(result.artist_id) # 不得自动匹配 ID 避免错配

    def test_fuzzy_multiple_candidates_collision(self) -> None:
        index = MatchIndex()
        index.add(ArtistRecord("atlas:entity:slikback_1", "Slikback", True), "Slikback")
        index.add(ArtistRecord("atlas:entity:slikback_2", "Slikback KE", False), "Slikback")
        
        resolver = EntityResolver(index=index, fuzzy_threshold=0.92)
        result = resolver.resolve("Slikbac")
        self.assertEqual(result.match_method, "fuzzy_multiple")
        self.assertEqual(result.display_tier, "show_with_hint")
        self.assertIsNone(result.artist_id)
        self.assertIsNotNone(result.candidates)
        self.assertEqual(len(result.candidates), 2)

    def test_blocked_term(self) -> None:
        registry = load_registry_seed(REGISTRY)
        resolver = EntityResolver(index=registry)
        result = resolver.resolve("loopy Club")
        self.assertEqual(result.match_method, "blocked")
        self.assertEqual(result.display_tier, "hide")


if __name__ == "__main__":
    unittest.main()
