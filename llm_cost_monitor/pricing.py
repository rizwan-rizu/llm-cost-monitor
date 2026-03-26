"""
Up-to-date pricing for major LLM providers.
Prices are per 1M tokens (input/output).
Last updated: 2026-03-26
"""

# fmt: off
MODEL_PRICING = {
    # OpenAI
    "gpt-4o":                    {"input": 2.50,  "output": 10.00,  "provider": "openai"},
    "gpt-4o-2024-11-20":         {"input": 2.50,  "output": 10.00,  "provider": "openai"},
    "gpt-4o-2024-08-06":         {"input": 2.50,  "output": 10.00,  "provider": "openai"},
    "gpt-4o-mini":               {"input": 0.15,  "output": 0.60,   "provider": "openai"},
    "gpt-4o-mini-2024-07-18":    {"input": 0.15,  "output": 0.60,   "provider": "openai"},
    "gpt-4-turbo":               {"input": 10.00, "output": 30.00,  "provider": "openai"},
    "gpt-4-turbo-2024-04-09":    {"input": 10.00, "output": 30.00,  "provider": "openai"},
    "gpt-4":                     {"input": 30.00, "output": 60.00,  "provider": "openai"},
    "gpt-4-0613":                {"input": 30.00, "output": 60.00,  "provider": "openai"},
    "gpt-3.5-turbo":             {"input": 0.50,  "output": 1.50,   "provider": "openai"},
    "gpt-3.5-turbo-0125":        {"input": 0.50,  "output": 1.50,   "provider": "openai"},
    "o1":                        {"input": 15.00, "output": 60.00,  "provider": "openai"},
    "o1-mini":                   {"input": 3.00,  "output": 12.00,  "provider": "openai"},
    "o1-preview":                {"input": 15.00, "output": 60.00,  "provider": "openai"},
    "o3":                        {"input": 10.00, "output": 40.00,  "provider": "openai"},
    "o3-mini":                   {"input": 1.10,  "output": 4.40,   "provider": "openai"},
    "o4-mini":                   {"input": 1.10,  "output": 4.40,   "provider": "openai"},

    # Anthropic
    "claude-opus-4-20250514":          {"input": 15.00, "output": 75.00,  "provider": "anthropic"},
    "claude-sonnet-4-20250514":        {"input": 3.00,  "output": 15.00,  "provider": "anthropic"},
    "claude-3-7-sonnet-20250219":      {"input": 3.00,  "output": 15.00,  "provider": "anthropic"},
    "claude-3-5-sonnet-20241022":      {"input": 3.00,  "output": 15.00,  "provider": "anthropic"},
    "claude-3-5-sonnet-20240620":      {"input": 3.00,  "output": 15.00,  "provider": "anthropic"},
    "claude-3-5-haiku-20241022":       {"input": 0.80,  "output": 4.00,   "provider": "anthropic"},
    "claude-3-opus-20240229":          {"input": 15.00, "output": 75.00,  "provider": "anthropic"},
    "claude-3-haiku-20240307":         {"input": 0.25,  "output": 1.25,   "provider": "anthropic"},

    # Google
    "gemini-2.0-flash":          {"input": 0.10,  "output": 0.40,   "provider": "google"},
    "gemini-2.0-flash-lite":     {"input": 0.075, "output": 0.30,   "provider": "google"},
    "gemini-1.5-pro":            {"input": 1.25,  "output": 5.00,   "provider": "google"},
    "gemini-1.5-flash":          {"input": 0.075, "output": 0.30,   "provider": "google"},
    "gemini-2.5-pro":            {"input": 1.25,  "output": 10.00,  "provider": "google"},
    "gemini-2.5-flash":          {"input": 0.15,  "output": 0.60,   "provider": "google"},

    # Mistral
    "mistral-large-latest":      {"input": 2.00,  "output": 6.00,   "provider": "mistral"},
    "mistral-small-latest":      {"input": 0.20,  "output": 0.60,   "provider": "mistral"},
    "codestral-latest":          {"input": 0.30,  "output": 0.90,   "provider": "mistral"},

    # Groq (hosted open-source)
    "llama-3.3-70b-versatile":   {"input": 0.59,  "output": 0.79,   "provider": "groq"},
    "llama-3.1-8b-instant":      {"input": 0.05,  "output": 0.08,   "provider": "groq"},
    "mixtral-8x7b-32768":        {"input": 0.24,  "output": 0.24,   "provider": "groq"},
    "gemma2-9b-it":              {"input": 0.20,  "output": 0.20,   "provider": "groq"},

    # DeepSeek
    "deepseek-chat":             {"input": 0.27,  "output": 1.10,   "provider": "deepseek"},
    "deepseek-reasoner":         {"input": 0.55,  "output": 2.19,   "provider": "deepseek"},

    # Cohere
    "command-r-plus":            {"input": 2.50,  "output": 10.00,  "provider": "cohere"},
    "command-r":                 {"input": 0.15,  "output": 0.60,   "provider": "cohere"},

    # Local / free models
    "_local":                    {"input": 0.00,  "output": 0.00,   "provider": "local"},
}
# fmt: on

# Aliases
MODEL_PRICING["gpt-4o-latest"] = MODEL_PRICING["gpt-4o"]
MODEL_PRICING["claude-3-5-sonnet-latest"] = MODEL_PRICING["claude-3-5-sonnet-20241022"]
MODEL_PRICING["claude-3-7-sonnet-latest"] = MODEL_PRICING["claude-3-7-sonnet-20250219"]
MODEL_PRICING["claude-sonnet-4-6"] = MODEL_PRICING["claude-sonnet-4-20250514"]
MODEL_PRICING["claude-opus-4-6"] = MODEL_PRICING["claude-opus-4-20250514"]


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    """Calculate cost for a given model and token counts."""
    pricing = MODEL_PRICING.get(model)

    if not pricing:
        # Try fuzzy match
        for key in MODEL_PRICING:
            if key in model or model in key:
                pricing = MODEL_PRICING[key]
                break

    if not pricing:
        return {
            "input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
            "model_found": False,
        }

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6),
        "model_found": True,
        "provider": pricing.get("provider", "unknown"),
    }


def get_all_models():
    """Return all known models grouped by provider."""
    providers = {}
    for model, info in MODEL_PRICING.items():
        provider = info.get("provider", "unknown")
        if provider not in providers:
            providers[provider] = []
        providers[provider].append(model)
    return providers
