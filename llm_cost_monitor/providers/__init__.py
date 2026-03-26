"""Parsers for extracting token usage from different LLM provider responses."""


def parse_openai_response(body: dict) -> dict:
    """Parse OpenAI / OpenAI-compatible response."""
    usage = body.get("usage", {})
    model = body.get("model", "unknown")
    return {
        "model": model,
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


def parse_anthropic_response(body: dict) -> dict:
    """Parse Anthropic response."""
    usage = body.get("usage", {})
    model = body.get("model", "unknown")
    return {
        "model": model,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


def parse_google_response(body: dict) -> dict:
    """Parse Google Gemini response."""
    usage = body.get("usageMetadata", {})
    model = body.get("modelVersion", "unknown")
    return {
        "model": model,
        "input_tokens": usage.get("promptTokenCount", 0),
        "output_tokens": usage.get("candidatesTokenCount", 0),
    }


# Map provider hosts to their parsers
PROVIDER_MAP = {
    "api.openai.com": {"name": "openai", "parser": parse_openai_response},
    "api.anthropic.com": {"name": "anthropic", "parser": parse_anthropic_response},
    "generativelanguage.googleapis.com": {"name": "google", "parser": parse_google_response},
    "api.groq.com": {"name": "groq", "parser": parse_openai_response},  # OpenAI-compatible
    "api.mistral.ai": {"name": "mistral", "parser": parse_openai_response},  # OpenAI-compatible
    "api.deepseek.com": {"name": "deepseek", "parser": parse_openai_response},  # OpenAI-compatible
    "api.cohere.ai": {"name": "cohere", "parser": parse_openai_response},
}


def detect_provider(target_url: str) -> dict:
    """Detect provider from target URL."""
    for host, info in PROVIDER_MAP.items():
        if host in target_url:
            return info
    return {"name": "unknown", "parser": parse_openai_response}
