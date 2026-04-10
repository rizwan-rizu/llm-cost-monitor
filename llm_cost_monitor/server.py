"""
LLM Cost Monitor - Proxy Server

A transparent proxy that sits between your app and any LLM API,
tracking costs and serving a real-time dashboard.
"""

import time
import json
import os
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db, log_request, get_summary, get_cost_by_model, get_cost_over_time, get_recent_requests, get_cost_by_provider, get_cost_by_tag
from .pricing import calculate_cost
from .providers import detect_provider
from .streaming import stream_openai, stream_anthropic

logger = logging.getLogger("llm-cost-monitor")

app = FastAPI(title="LLM Cost Monitor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Target URLs for each provider
PROVIDER_TARGETS = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "groq": "https://api.groq.com",
    "mistral": "https://api.mistral.ai",
    "deepseek": "https://api.deepseek.com",
    "cohere": "https://api.cohere.ai",
}


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("LLM Cost Monitor started")


# ──────────────────────────────────────────────
# Dashboard API endpoints
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard UI."""
    static_dir = Path(__file__).parent / "static"
    html_file = static_dir / "dashboard.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text())
    return HTMLResponse("<h1>Dashboard not found. Reinstall llm-cost-monitor.</h1>")


@app.get("/api/summary")
async def api_summary(hours: int = 24):
    return JSONResponse(get_summary(hours))


@app.get("/api/by-model")
async def api_by_model(hours: int = 24):
    return JSONResponse(get_cost_by_model(hours))


@app.get("/api/by-provider")
async def api_by_provider(hours: int = 24):
    return JSONResponse(get_cost_by_provider(hours))


@app.get("/api/over-time")
async def api_over_time(hours: int = 168, bucket: int = 60):
    return JSONResponse(get_cost_over_time(hours, bucket))


@app.get("/api/recent")
async def api_recent(limit: int = 50):
    return JSONResponse(get_recent_requests(limit))


@app.get("/api/by-tag")
async def api_by_tag(hours: int = 24):
    return JSONResponse(get_cost_by_tag(hours))


# ──────────────────────────────────────────────
# Proxy endpoints - one per provider
# ──────────────────────────────────────────────

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_openai(request: Request, path: str):
    """Proxy for OpenAI API (and any OpenAI-compatible API)."""
    target = os.environ.get("LLM_PROXY_OPENAI_TARGET", PROVIDER_TARGETS["openai"])
    return await _proxy_request(request, f"{target}/v1/{path}", "openai")


@app.api_route("/anthropic/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_anthropic(request: Request, path: str):
    """Proxy for Anthropic API."""
    target = os.environ.get("LLM_PROXY_ANTHROPIC_TARGET", PROVIDER_TARGETS["anthropic"])
    return await _proxy_request(request, f"{target}/v1/{path}", "anthropic")


@app.api_route("/google/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_google(request: Request, path: str):
    """Proxy for Google Gemini API."""
    target = os.environ.get("LLM_PROXY_GOOGLE_TARGET", PROVIDER_TARGETS["google"])
    return await _proxy_request(request, f"{target}/{path}", "google")


@app.api_route("/groq/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_groq(request: Request, path: str):
    """Proxy for Groq API."""
    target = os.environ.get("LLM_PROXY_GROQ_TARGET", PROVIDER_TARGETS["groq"])
    return await _proxy_request(request, f"{target}/openai/v1/{path}", "groq")


async def _proxy_request(request: Request, target_url: str, provider_hint: str):
    """Forward request to target, log cost on response."""
    start = time.time()

    # Extract request data
    body_bytes = await request.body()
    headers = dict(request.headers)

    # Remove hop-by-hop headers
    for h in ["host", "content-length", "transfer-encoding"]:
        headers.pop(h, None)

    # Parse request body for model info
    request_body = {}
    model_from_request = "unknown"
    tag = ""
    is_streaming = False
    try:
        if body_bytes:
            request_body = json.loads(body_bytes)
            model_from_request = request_body.get("model", "unknown")
            # Support optional cost-monitor tag in request
            tag = request_body.pop("_cost_tag", "")
            is_streaming = bool(request_body.get("stream", False))
    except (json.JSONDecodeError, AttributeError):
        pass

    send_bytes = body_bytes if not tag else json.dumps(request_body).encode()
    params = dict(request.query_params)

    # Route streaming requests through dedicated handlers
    if is_streaming:
        client = httpx.AsyncClient(timeout=300.0)
        try:
            if provider_hint == "anthropic":
                return await stream_anthropic(
                    client, request.method, target_url, headers,
                    send_bytes, params, provider_hint, tag, model_from_request,
                )
            else:
                return await stream_openai(
                    client, request.method, target_url, headers,
                    send_bytes, params, provider_hint, tag, model_from_request,
                )
        except httpx.RequestError as e:
            await client.aclose()
            logger.error(f"Streaming proxy error: {e}")
            return JSONResponse(
                {"error": f"Failed to reach {provider_hint}: {str(e)}"},
                status_code=502,
            )

    # Forward the (non-streaming) request
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=send_bytes,
                params=params,
            )
    except httpx.RequestError as e:
        logger.error(f"Proxy error: {e}")
        return JSONResponse(
            {"error": f"Failed to reach {provider_hint}: {str(e)}"},
            status_code=502,
        )

    latency_ms = int((time.time() - start) * 1000)

    # Parse response for token usage
    response_body = {}
    try:
        response_body = response.json()
    except (json.JSONDecodeError, ValueError):
        pass

    provider_info = detect_provider(target_url)
    parsed = provider_info["parser"](response_body)

    model = parsed.get("model") or model_from_request
    input_tokens = parsed.get("input_tokens", 0)
    output_tokens = parsed.get("output_tokens", 0)

    # Calculate cost
    cost = calculate_cost(model, input_tokens, output_tokens)

    # Log to database
    if input_tokens > 0 or output_tokens > 0:
        log_request(
            provider=provider_hint,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost=cost["input_cost"],
            output_cost=cost["output_cost"],
            total_cost=cost["total_cost"],
            latency_ms=latency_ms,
            status_code=response.status_code,
            endpoint=target_url,
            tag=tag,
        )

    # Add cost headers to response
    resp_headers = dict(response.headers)
    resp_headers["x-llm-cost"] = str(cost["total_cost"])
    resp_headers["x-llm-input-tokens"] = str(input_tokens)
    resp_headers["x-llm-output-tokens"] = str(output_tokens)
    resp_headers["x-llm-latency-ms"] = str(latency_ms)

    # Clean hop-by-hop headers
    for h in ["content-encoding", "content-length", "transfer-encoding"]:
        resp_headers.pop(h, None)

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=resp_headers,
        media_type=response.headers.get("content-type"),
    )


def create_app():
    return app
