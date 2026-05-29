from __future__ import annotations

import unittest
from unittest.mock import patch

from axiom_scanner.analysis.image_generation import (
    ImageGenerationError,
    get_openai_api_keys,
    should_try_next_openai_key,
)
from axiom_scanner.analysis.narratives import generate_narratives, normalize_og_memecoins
from axiom_scanner.analysis.scoring import rank_tokens
from axiom_scanner.analysis.wavespeed_hybrid import HybridImageError, should_try_next_key
from axiom_scanner.analysis.wavespeed_hybrid import rotated_wavespeed_api_keys
from axiom_scanner.config import ScannerConfig
from axiom_scanner.models import TokenSnapshot
from axiom_scanner.sources.dexscreener import _passes_basic_filters
from axiom_dashboard import _token_identity_keys


class ScoringTests(unittest.TestCase):
    def test_stronger_token_ranks_higher(self) -> None:
        config = ScannerConfig()
        weak = TokenSnapshot(
            source="test",
            chain_id="solana",
            token_address="weak",
            symbol="WEAK",
            name="Weak",
            liquidity_usd=20_000,
            volume_1h=2_000,
            txns_1h=15,
            price_change_1h=2,
            age_minutes=500,
        )
        strong = TokenSnapshot(
            source="test",
            chain_id="solana",
            token_address="strong",
            symbol="STRONG",
            name="Strong",
            liquidity_usd=120_000,
            volume_1h=160_000,
            txns_1h=260,
            buys_1h=170,
            sells_1h=90,
            price_change_5m=6,
            price_change_1h=42,
            price_change_6h=70,
            age_minutes=75,
            socials_count=3,
        )

        ranked = rank_tokens([weak, strong], config)

        self.assertEqual(ranked[0].snapshot.symbol, "STRONG")
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_sell_pressure_adds_risk_flag(self) -> None:
        config = ScannerConfig()
        token = TokenSnapshot(
            source="test",
            chain_id="solana",
            token_address="risk",
            symbol="RISK",
            name="Risk",
            liquidity_usd=60_000,
            volume_1h=80_000,
            txns_1h=120,
            buys_1h=20,
            sells_1h=80,
            price_change_1h=20,
            age_minutes=90,
        )

        ranked = rank_tokens([token], config)

        self.assertIn("sell_pressure", ranked[0].risk_flags)

    def test_market_cap_filter_rejects_small_tokens(self) -> None:
        config = ScannerConfig(min_market_cap_usd=500_000)
        token = TokenSnapshot(
            source="test",
            chain_id="solana",
            token_address="small",
            symbol="SMALL",
            name="Small",
            liquidity_usd=50_000,
            market_cap=120_000,
        )

        self.assertFalse(_passes_basic_filters(token, config))

    def test_narrative_generator_blends_trend_with_og_token(self) -> None:
        trend = {
            "token": "AXIOM",
            "name": "Axiom Trend",
            "signal": "HOT",
            "score": 88.2,
            "market_cap": 1_200_000,
            "volume_1h": 240_000,
            "price_change_1h": 31,
        }
        og_tokens = normalize_og_memecoins(["Pepe,PEPE,frog meta"])

        narratives = generate_narratives([trend], og_tokens, limit=1)

        self.assertEqual(len(narratives), 1)
        self.assertEqual(narratives[0]["og_token"], "PEPE")
        self.assertIn("image_prompt", narratives[0])
        self.assertIn("visual_modifiers", narratives[0])

    def test_duplicate_symbols_can_remain_when_names_differ(self) -> None:
        og_tokens = normalize_og_memecoins(["Wen,WEN", "WenWenCoin,WEN"])

        self.assertEqual(len(og_tokens), 2)

    def test_speculative_tokens_can_still_feed_narratives(self) -> None:
        trend = {
            "token": "ALIENS",
            "name": "Aliens are real",
            "signal": "SPECULATIVE",
            "score": 18,
            "image_url": "https://example.com/aliens.png",
        }
        og_tokens = normalize_og_memecoins(["AIntivirus,AINTI,AI security pun"])

        narratives = generate_narratives([trend], og_tokens, limit=1)

        self.assertEqual(len(narratives), 1)
        self.assertIn("trend_image_url", narratives[0])

    def test_wavespeed_fallback_handles_quota_rejections(self) -> None:
        error = HybridImageError(
            "WaveSpeed did not return an output image: insufficient balance",
            code="provider_rejected",
            status=502,
        )

        self.assertTrue(should_try_next_key(error))

    def test_wavespeed_fallback_handles_busy_keys(self) -> None:
        error = HybridImageError(
            "WaveSpeed API error: too many concurrent requests",
            code="wavespeed_error",
            status=429,
        )

        self.assertTrue(should_try_next_key(error))

    def test_wavespeed_keeps_primary_key_first_and_rotates_fallbacks(self) -> None:
        keys = ["first-key", "second-key", "third-key"]

        first_order = rotated_wavespeed_api_keys(keys)
        second_order = rotated_wavespeed_api_keys(keys)

        self.assertCountEqual(first_order, [(1, "first-key"), (2, "second-key"), (3, "third-key")])
        self.assertEqual(first_order[0], (1, "first-key"))
        self.assertEqual(second_order[0], (1, "first-key"))
        self.assertNotEqual(first_order[1], second_order[1])

    def test_openai_key_list_deduplicates_fallback_keys(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEYS": "first-key, second-key; first-key", "OPENAI_API_KEY": "ignored"},
            clear=False,
        ):
            self.assertEqual(get_openai_api_keys(), ["first-key", "second-key"])

    def test_openai_fallback_handles_quota_and_rate_errors(self) -> None:
        error = ImageGenerationError(
            "OpenAI API error: insufficient quota",
            code="openai_error",
            status=429,
        )

        self.assertTrue(should_try_next_openai_key(error))

    def test_token_identity_keys_include_address_and_label(self) -> None:
        keys = _token_identity_keys(
            address="So111",
            symbol="BONK",
            name="Bonk",
        )

        self.assertIn("address:so111", keys)
        self.assertIn("label:bonk:bonk", keys)


if __name__ == "__main__":
    unittest.main()
