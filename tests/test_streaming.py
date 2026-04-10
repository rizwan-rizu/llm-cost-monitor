"""Tests for streaming.py — SSE parsing and token counter logic."""

import pytest
from llm_cost_monitor.streaming import (
    _parse_sse_line,
    OpenAIStreamTokenCounter,
    AnthropicStreamTokenCounter,
)


# ── _parse_sse_line ────────────────────────────────────────────────────────────

class TestParseSSELine:
    def test_valid_data_line(self):
        result = _parse_sse_line('data: {"model": "gpt-4o", "choices": []}')
        assert result == {"model": "gpt-4o", "choices": []}

    def test_done_sentinel_returns_none(self):
        assert _parse_sse_line("data: [DONE]") is None

    def test_empty_data_returns_none(self):
        assert _parse_sse_line("data: ") is None

    def test_non_data_line_returns_none(self):
        assert _parse_sse_line("event: message_start") is None
        assert _parse_sse_line(": keep-alive") is None
        assert _parse_sse_line("") is None

    def test_invalid_json_returns_none(self):
        assert _parse_sse_line("data: {broken json") is None

    def test_data_with_leading_space(self):
        result = _parse_sse_line('data:  {"id": "1"}')
        assert result == {"id": "1"}


# ── OpenAIStreamTokenCounter ───────────────────────────────────────────────────

class TestOpenAIStreamTokenCounter:
    def test_model_extracted_from_first_chunk(self):
        counter = OpenAIStreamTokenCounter()
        counter.process_chunk({"model": "gpt-4o", "choices": []})
        assert counter.model == "gpt-4o"

    def test_usage_chunk_sets_token_counts(self):
        counter = OpenAIStreamTokenCounter()
        counter.process_chunk({
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 120, "completion_tokens": 60},
        })
        assert counter.input_tokens == 120
        assert counter.output_tokens == 60

    def test_usage_chunk_overrides_heuristic(self):
        counter = OpenAIStreamTokenCounter()
        # First, a delta chunk triggers heuristic
        counter.process_chunk({"choices": [{"delta": {"content": "Hello world"}}]})
        # Then, the final usage chunk should override
        counter.process_chunk({"usage": {"prompt_tokens": 100, "completion_tokens": 50}})
        assert counter.input_tokens == 100
        assert counter.output_tokens == 50

    def test_heuristic_fallback_when_no_usage(self):
        counter = OpenAIStreamTokenCounter()
        # 8 chars → max(1, 8//4) = 2 tokens
        counter.process_chunk({"choices": [{"delta": {"content": "12345678"}}]})
        assert counter.output_tokens == 2

    def test_heuristic_minimum_one_token(self):
        counter = OpenAIStreamTokenCounter()
        counter.process_chunk({"choices": [{"delta": {"content": "hi"}}]})
        assert counter.output_tokens == 1  # max(1, 2//4) = 1

    def test_empty_delta_content_ignored(self):
        counter = OpenAIStreamTokenCounter()
        counter.process_chunk({"choices": [{"delta": {}}]})
        assert counter.output_tokens == 0

    def test_model_updated_on_each_chunk(self):
        # OpenAI sends model on every chunk; counter keeps the most recent value
        counter = OpenAIStreamTokenCounter()
        counter.process_chunk({"model": "gpt-4o"})
        counter.process_chunk({"model": "gpt-4o-mini"})
        assert counter.model == "gpt-4o-mini"

    def test_initial_state(self):
        counter = OpenAIStreamTokenCounter()
        assert counter.input_tokens == 0
        assert counter.output_tokens == 0
        assert counter.model == "unknown"


# ── AnthropicStreamTokenCounter ───────────────────────────────────────────────

class TestAnthropicStreamTokenCounter:
    def test_message_start_sets_input_tokens_and_model(self):
        counter = AnthropicStreamTokenCounter()
        counter.process_event("message_start", {
            "message": {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {"input_tokens": 200},
            }
        })
        assert counter.input_tokens == 200
        assert counter.model == "claude-3-5-sonnet-20241022"

    def test_message_delta_sets_output_tokens(self):
        counter = AnthropicStreamTokenCounter()
        counter.process_event("message_start", {
            "message": {"model": "claude-3-haiku-20240307", "usage": {"input_tokens": 50}}
        })
        counter.process_event("message_delta", {"usage": {"output_tokens": 30}})
        assert counter.output_tokens == 30

    def test_unrecognised_event_type_ignored(self):
        counter = AnthropicStreamTokenCounter()
        counter.process_event("content_block_delta", {"delta": {"text": "hello"}})
        assert counter.input_tokens == 0
        assert counter.output_tokens == 0

    def test_message_start_without_model_field(self):
        counter = AnthropicStreamTokenCounter()
        counter.process_event("message_start", {
            "message": {"usage": {"input_tokens": 10}}
        })
        assert counter.input_tokens == 10
        assert counter.model == "unknown"

    def test_message_delta_without_usage_keeps_existing(self):
        counter = AnthropicStreamTokenCounter()
        counter.process_event("message_start", {
            "message": {"model": "claude-3-haiku-20240307", "usage": {"input_tokens": 20}}
        })
        counter.process_event("message_delta", {})
        # output_tokens should remain 0 (default)
        assert counter.output_tokens == 0

    def test_initial_state(self):
        counter = AnthropicStreamTokenCounter()
        assert counter.input_tokens == 0
        assert counter.output_tokens == 0
        assert counter.model == "unknown"

    def test_full_stream_sequence(self):
        """Simulate a complete Anthropic stream event sequence."""
        counter = AnthropicStreamTokenCounter()
        counter.process_event("message_start", {
            "message": {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {"input_tokens": 150},
            }
        })
        counter.process_event("content_block_start", {"content_block": {"type": "text"}})
        counter.process_event("content_block_delta", {"delta": {"text": "Hello!"}})
        counter.process_event("content_block_stop", {})
        counter.process_event("message_delta", {"usage": {"output_tokens": 45}})
        counter.process_event("message_stop", {})

        assert counter.model == "claude-3-5-sonnet-20241022"
        assert counter.input_tokens == 150
        assert counter.output_tokens == 45
