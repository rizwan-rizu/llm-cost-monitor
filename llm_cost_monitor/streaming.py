"""
Streaming response support for LLM Cost Monitor.

Handles SSE (Server-Sent Events) streams from OpenAI-compatible and Anthropic APIs,
counting tokens from chunks and logging cost after the stream completes.
"""

import json
import logging
import time

import httpx
from fastapi.responses import StreamingResponse

from .db import log_request
from .pricing import calculate_cost

logger = logging.getLogger("llm-cost-monitor")


def _parse_sse_line(line: str) -> dict | None:
    """Parse a single SSE data line into a dict, or None if not parseable."""
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload in ("", "[DONE]"):
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class OpenAIStreamTokenCounter:
    """Counts tokens from an OpenAI-compatible SSE stream."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.model = "unknown"

    def process_chunk(self, chunk: dict):
        # Model name comes in the first chunk
        if chunk.get("model"):
            self.model = chunk["model"]

        # OpenAI sends usage in the final chunk when stream_options.include_usage=true
        usage = chunk.get("usage")
        if usage:
            self.input_tokens = usage.get("prompt_tokens", self.input_tokens)
            self.output_tokens = usage.get("completion_tokens", self.output_tokens)
            return

        # Fall back to counting output tokens from delta content length heuristic
        # (rough estimate — usage field is far more accurate)
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            content = delta.get("content") or ""
            # Approximate: 1 token ≈ 4 chars. Only used when include_usage is not available.
            if content and self.output_tokens == 0:
                self.output_tokens += max(1, len(content) // 4)


class AnthropicStreamTokenCounter:
    """Counts tokens from an Anthropic SSE stream."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.model = "unknown"

    def process_event(self, event_type: str, chunk: dict):
        if event_type == "message_start":
            msg = chunk.get("message", {})
            if msg.get("model"):
                self.model = msg["model"]
            usage = msg.get("usage", {})
            self.input_tokens = usage.get("input_tokens", 0)

        elif event_type == "message_delta":
            usage = chunk.get("usage", {})
            self.output_tokens = usage.get("output_tokens", self.output_tokens)


async def stream_openai(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    content: bytes,
    params: dict,
    provider: str,
    tag: str,
    model_hint: str,
) -> StreamingResponse:
    """
    Forward an OpenAI-compatible streaming request, count tokens, log cost.

    Injects stream_options.include_usage=true so the final SSE chunk carries
    accurate token counts without any guesswork.
    """
    start = time.time()

    # Inject include_usage so we get accurate token counts in the final chunk
    try:
        body = json.loads(content)
        body.setdefault("stream_options", {})["include_usage"] = True
        content = json.dumps(body).encode()
    except (json.JSONDecodeError, AttributeError):
        pass

    counter = OpenAIStreamTokenCounter()
    latency_ms_ref = [0]

    async def generate():
        first_chunk = True
        async with client.stream(method, url, headers=headers, content=content, params=params) as resp:
            async for raw_line in resp.aiter_lines():
                if first_chunk:
                    latency_ms_ref[0] = int((time.time() - start) * 1000)
                    first_chunk = False

                chunk = _parse_sse_line(raw_line)
                if chunk is not None:
                    counter.process_chunk(chunk)

                yield raw_line + "\n"

        # Stream done — log accumulated cost
        model = counter.model if counter.model != "unknown" else model_hint
        cost = calculate_cost(model, counter.input_tokens, counter.output_tokens)
        if counter.input_tokens > 0 or counter.output_tokens > 0:
            log_request(
                provider=provider,
                model=model,
                input_tokens=counter.input_tokens,
                output_tokens=counter.output_tokens,
                input_cost=cost["input_cost"],
                output_cost=cost["output_cost"],
                total_cost=cost["total_cost"],
                latency_ms=latency_ms_ref[0],
                status_code=200,
                endpoint=url,
                tag=tag,
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def stream_anthropic(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    content: bytes,
    params: dict,
    provider: str,
    tag: str,
    model_hint: str,
) -> StreamingResponse:
    """
    Forward an Anthropic streaming request, count tokens, log cost.

    Anthropic streams event/data pairs. We parse message_start for input tokens
    and message_delta for output tokens.
    """
    start = time.time()
    counter = AnthropicStreamTokenCounter()
    latency_ms_ref = [0]

    async def generate():
        first_chunk = True
        current_event_type = None

        async with client.stream(method, url, headers=headers, content=content, params=params) as resp:
            async for raw_line in resp.aiter_lines():
                if first_chunk and raw_line:
                    latency_ms_ref[0] = int((time.time() - start) * 1000)
                    first_chunk = False

                line = raw_line.strip()

                if line.startswith("event:"):
                    current_event_type = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    if payload and current_event_type:
                        try:
                            chunk = json.loads(payload)
                            counter.process_event(current_event_type, chunk)
                        except json.JSONDecodeError:
                            pass

                yield raw_line + "\n"

        # Stream done — log accumulated cost
        model = counter.model if counter.model != "unknown" else model_hint
        cost = calculate_cost(model, counter.input_tokens, counter.output_tokens)
        if counter.input_tokens > 0 or counter.output_tokens > 0:
            log_request(
                provider=provider,
                model=model,
                input_tokens=counter.input_tokens,
                output_tokens=counter.output_tokens,
                input_cost=cost["input_cost"],
                output_cost=cost["output_cost"],
                total_cost=cost["total_cost"],
                latency_ms=latency_ms_ref[0],
                status_code=200,
                endpoint=url,
                tag=tag,
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
