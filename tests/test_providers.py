"""Tests for providers/__init__.py — response parsers and provider detection."""

import pytest
from llm_cost_monitor.providers import (
    parse_openai_response,
    parse_anthropic_response,
    parse_google_response,
    detect_provider,
)


class TestParseOpenAIResponse:
    def test_standard_response(self):
        body = {
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        result = parse_openai_response(body)
        assert result["model"] == "gpt-4o"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50

    def test_missing_usage_returns_zeros(self):
        result = parse_openai_response({"model": "gpt-4o"})
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_empty_body_returns_unknown_model(self):
        result = parse_openai_response({})
        assert result["model"] == "unknown"
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_partial_usage(self):
        body = {"model": "gpt-4o-mini", "usage": {"prompt_tokens": 200}}
        result = parse_openai_response(body)
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 0


class TestParseAnthropicResponse:
    def test_standard_response(self):
        body = {
            "model": "claude-3-5-sonnet-20241022",
            "usage": {"input_tokens": 150, "output_tokens": 75},
        }
        result = parse_anthropic_response(body)
        assert result["model"] == "claude-3-5-sonnet-20241022"
        assert result["input_tokens"] == 150
        assert result["output_tokens"] == 75

    def test_missing_usage_returns_zeros(self):
        result = parse_anthropic_response({"model": "claude-3-opus-20240229"})
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_empty_body(self):
        result = parse_anthropic_response({})
        assert result["model"] == "unknown"


class TestParseGoogleResponse:
    def test_standard_response(self):
        body = {
            "modelVersion": "gemini-1.5-pro",
            "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 40},
        }
        result = parse_google_response(body)
        assert result["model"] == "gemini-1.5-pro"
        assert result["input_tokens"] == 80
        assert result["output_tokens"] == 40

    def test_missing_usage_metadata(self):
        result = parse_google_response({"modelVersion": "gemini-2.0-flash"})
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_empty_body(self):
        result = parse_google_response({})
        assert result["model"] == "unknown"


class TestDetectProvider:
    @pytest.mark.parametrize("url,expected_name", [
        ("https://api.openai.com/v1/chat/completions", "openai"),
        ("https://api.anthropic.com/v1/messages", "anthropic"),
        ("https://generativelanguage.googleapis.com/v1/models", "google"),
        ("https://api.groq.com/openai/v1/chat/completions", "groq"),
        ("https://api.mistral.ai/v1/chat/completions", "mistral"),
        ("https://api.deepseek.com/v1/chat/completions", "deepseek"),
        ("https://api.cohere.ai/v1/generate", "cohere"),
    ])
    def test_known_providers(self, url, expected_name):
        result = detect_provider(url)
        assert result["name"] == expected_name
        assert callable(result["parser"])

    def test_unknown_url_falls_back_to_openai_parser(self):
        result = detect_provider("https://some-custom-llm.example.com/v1/chat")
        assert result["name"] == "unknown"
        assert result["parser"] == parse_openai_response

    def test_detected_parser_is_callable(self):
        result = detect_provider("https://api.anthropic.com/v1/messages")
        # Parser should work on a real-shaped body
        parsed = result["parser"]({"model": "claude-3-haiku-20240307", "usage": {"input_tokens": 10, "output_tokens": 5}})
        assert parsed["input_tokens"] == 10
