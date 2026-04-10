"""Tests for pricing.py — cost calculation logic."""

import pytest
from llm_cost_monitor.pricing import calculate_cost, MODEL_PRICING


class TestCalculateCost:
    def test_known_model_returns_correct_cost(self):
        # gpt-4o: $2.50/M input, $10.00/M output
        result = calculate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert result["input_cost"] == 2.50
        assert result["output_cost"] == 10.00
        assert result["total_cost"] == 12.50
        assert result["model_found"] is True

    def test_zero_tokens_returns_zero_cost(self):
        result = calculate_cost("gpt-4o", 0, 0)
        assert result["total_cost"] == 0.0
        assert result["model_found"] is True

    def test_only_input_tokens(self):
        result = calculate_cost("gpt-4o-mini", 1_000_000, 0)
        assert result["input_cost"] == pytest.approx(0.15)
        assert result["output_cost"] == 0.0

    def test_only_output_tokens(self):
        result = calculate_cost("gpt-4o-mini", 0, 1_000_000)
        assert result["input_cost"] == 0.0
        assert result["output_cost"] == pytest.approx(0.60)

    def test_unknown_model_returns_zero_cost(self):
        result = calculate_cost("nonexistent-model-xyz", 1000, 500)
        assert result["total_cost"] == 0.0
        assert result["input_cost"] == 0.0
        assert result["output_cost"] == 0.0
        assert result["model_found"] is False

    def test_fuzzy_match_partial_name(self):
        # "gpt-4o" is in "gpt-4o-2024-08-06" — fuzzy should resolve
        result = calculate_cost("gpt-4o-2024-08-06", 1_000_000, 0)
        assert result["model_found"] is True
        assert result["input_cost"] > 0

    def test_anthropic_model(self):
        # claude-3-5-haiku: $0.80/M input, $4.00/M output
        result = calculate_cost("claude-3-5-haiku-20241022", 1_000_000, 1_000_000)
        assert result["input_cost"] == pytest.approx(0.80)
        assert result["output_cost"] == pytest.approx(4.00)
        assert result["provider"] == "anthropic"

    def test_provider_field_present_for_known_model(self):
        result = calculate_cost("gpt-4o", 100, 100)
        assert result["provider"] == "openai"

    def test_cost_scales_linearly(self):
        single = calculate_cost("gpt-4o", 1000, 0)
        double = calculate_cost("gpt-4o", 2000, 0)
        assert pytest.approx(double["input_cost"], rel=1e-6) == single["input_cost"] * 2

    def test_free_local_model(self):
        result = calculate_cost("_local", 999_999, 999_999)
        assert result["total_cost"] == 0.0
        assert result["model_found"] is True

    def test_alias_resolves(self):
        # claude-sonnet-4-6 is an alias
        result = calculate_cost("claude-sonnet-4-6", 1_000_000, 0)
        assert result["model_found"] is True
        assert result["input_cost"] == pytest.approx(3.00)


class TestModelPricingTable:
    def test_output_not_cheaper_than_input_for_same_model(self):
        """Output tokens should never be cheaper than input tokens."""
        for model, pricing in MODEL_PRICING.items():
            if pricing["input"] == 0:
                continue  # free/local models are exempt
            assert pricing["output"] >= pricing["input"], (
                f"{model}: output price ${pricing['output']} < input price ${pricing['input']}"
            )

    def test_all_models_have_required_fields(self):
        for model, pricing in MODEL_PRICING.items():
            assert "input" in pricing, f"{model} missing 'input'"
            assert "output" in pricing, f"{model} missing 'output'"
            assert "provider" in pricing, f"{model} missing 'provider'"

    def test_prices_are_non_negative(self):
        for model, pricing in MODEL_PRICING.items():
            assert pricing["input"] >= 0, f"{model} has negative input price"
            assert pricing["output"] >= 0, f"{model} has negative output price"
