# $ llm-cost-monitor

**Track every dollar your AI spends.** One command. Works with any language. Zero code changes.

A transparent proxy that sits between your app and any LLM API, logs every request's token usage and cost, and serves a real-time dashboard. You don't touch your application code. Just change the base URL and you're done.

![Dashboard Screenshot](docs/dashboard.png)

---

## Why?

You're making LLM API calls. Maybe a few, maybe thousands. Maybe you have agents that loop unpredictably. At the end of the month you get a bill and have no idea which feature, model, or rogue agent loop ate your budget.

**llm-cost-monitor** gives you per-request, per-model, real-time visibility into what you're spending, with budget kill switches before things get out of hand.

## Quick Start

```bash
pip install llm-cost-monitor
llm-cost-monitor start
```

That's it. Dashboard is at `http://localhost:8877`. Proxy is running.

## Works With Every Language

Because it's a proxy, not an SDK. Change your base URL, keep everything else the same.

### Python (OpenAI)
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8877/v1",  # <-- only change
    api_key="sk-..."
)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```

### Python (Anthropic)
```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://localhost:8877/anthropic/v1",  # <-- only change
    api_key="sk-ant-..."
)
message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}]
)
```

### TypeScript / Node.js
```typescript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8877/v1',  // <-- only change
  apiKey: 'sk-...',
});
```

### Go
```go
config := openai.DefaultConfig("sk-...")
config.BaseURL = "http://localhost:8877/v1"  // <-- only change
client := openai.NewClientWithConfig(config)
```

### Rust
```rust
let client = Client::new()
    .base_url("http://localhost:8877/v1")  // <-- only change
    .api_key("sk-...");
```

### cURL
```bash
curl http://localhost:8877/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello"}]}'
```

Every response includes cost headers:
```
x-llm-cost: 0.000340
x-llm-input-tokens: 12
x-llm-output-tokens: 28
x-llm-latency-ms: 834
```

## Supported Providers

| Provider | Proxy Endpoint | Status |
|----------|---------------|--------|
| OpenAI | `localhost:8877/v1` | :white_check_mark: |
| Anthropic | `localhost:8877/anthropic/v1` | :white_check_mark: |
| Google Gemini | `localhost:8877/google` | :white_check_mark: |
| Groq | `localhost:8877/groq/v1` | :white_check_mark: |
| Mistral | `localhost:8877/v1` (OpenAI-compat) | :white_check_mark: |
| DeepSeek | `localhost:8877/v1` (OpenAI-compat) | :white_check_mark: |
| Any OpenAI-compatible API | `localhost:8877/v1` | :white_check_mark: |

## Features

### Real-Time Dashboard
- Total spend, request count, token usage, latency
- Cost over time chart
- Breakdown by model and provider
- Live request log with per-request costs
- Filterable by 1h, 6h, 24h, 7d, 30d

### Cost Headers on Every Response
Every proxied response gets extra headers with cost data, so your app can react to costs programmatically.

### Request Tagging
Tag requests to track costs per feature, user, or agent run:
```python
# Add _cost_tag to your request body
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    extra_body={"_cost_tag": "agent-research-task"}
)
```

### CLI Summary
```bash
llm-cost-monitor summary --hours 24

# --- Cost Summary (last 24h) ---
#   Requests:      1,247
#   Total Cost:    $3.8421
#   Input Tokens:  2,847,102
#   Output Tokens: 412,847
#   Avg Latency:   923ms
#
#   By Model:
#     gpt-4o                                   $2.1204  (312 reqs)
#     claude-sonnet-4-20250514                  $1.0847  (201 reqs)
#     gpt-4o-mini                               $0.6370  (734 reqs)
```

## Configuration

### Environment Variables
```bash
# Custom database location (default: ~/.llm-cost-monitor/costs.db)
LLM_COST_DB=/path/to/costs.db

# Override target URLs (useful for custom endpoints)
LLM_PROXY_OPENAI_TARGET=https://your-custom-openai-endpoint.com
LLM_PROXY_ANTHROPIC_TARGET=https://your-custom-anthropic-endpoint.com
```

### Docker
```bash
docker run -p 8877:8877 -v ~/.llm-cost-monitor:/data ghcr.io/YOUR_USERNAME/llm-cost-monitor
```

## How It Works

```
Your App  --->  llm-cost-monitor proxy  --->  OpenAI / Anthropic / etc.
                       |
                  Logs tokens + cost
                       |
                  SQLite (local)
                       |
                  Dashboard UI
```

1. Your app sends requests to the proxy instead of the real API
2. The proxy forwards everything transparently (auth, headers, streaming)
3. On the response, it reads token counts and calculates cost using built-in pricing
4. Logs to local SQLite, adds cost headers to the response
5. Your app gets the exact same response it would normally get
6. Dashboard reads from SQLite and updates every 5 seconds

Zero data leaves your machine. Nothing is stored except token counts and costs.

## Pricing Updates

Model pricing is built in and kept current. To update pricing without upgrading:
```bash
pip install --upgrade llm-cost-monitor
```

If a model isn't in the pricing table, the request is still proxied and logged (cost shows as $0.00 with a note). Open an issue or PR to add new models.

## Roadmap

- [ ] Budget alerts and hard kill switches (abort request if budget exceeded)
- [ ] Streaming response support with token counting
- [ ] Export to CSV/JSON
- [ ] Prometheus metrics endpoint
- [ ] Slack/Discord alerts when spend exceeds threshold
- [ ] Team mode with per-user tracking
- [ ] Hosted version (coming soon)

## Contributing

PRs welcome. The main things that need help:
1. **Pricing updates** when providers change their rates
2. **New provider parsers** for providers not yet supported
3. **Dashboard improvements** (it's a single HTML file, easy to hack on)
4. **Streaming support** for SSE responses

## License

MIT
