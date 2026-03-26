"""
Demo script for llm-cost-monitor.

Simulates realistic LLM API traffic so you can screen-record
the dashboard for a GIF/video. Run this while the server is up:

    Terminal 1:  llm-cost-monitor start
    Terminal 2:  python demo.py

Then screen-record http://localhost:8877 for 30-60 seconds.
"""

import random
import time
import sys
import os

# Add parent dir so we can import directly
sys.path.insert(0, os.path.dirname(__file__))

from llm_cost_monitor.db import init_db, log_request
from llm_cost_monitor.pricing import calculate_cost


# ──────────────────────────────────────────────
# Realistic request scenarios
# ──────────────────────────────────────────────

SCENARIOS = [
    # (provider, model, input_range, output_range, endpoint, tags, weight)
    # weight controls how often this scenario fires

    # Common: GPT-4o-mini for cheap classification / routing
    ("openai", "gpt-4o-mini", (80, 400), (10, 60), "/v1/chat/completions",
     ["classifier", "router", "intent-detect"], 30),

    # Common: GPT-4o for main generation
    ("openai", "gpt-4o", (500, 3000), (200, 1500), "/v1/chat/completions",
     ["chat", "agent-main", "summarize", "generate"], 25),

    # Claude Sonnet for complex tasks
    ("anthropic", "claude-sonnet-4-20250514", (800, 5000), (500, 3000), "/v1/messages",
     ["agent-research", "code-review", "analysis", "deep-dive"], 20),

    # Claude Haiku for fast/cheap tasks
    ("anthropic", "claude-3-5-haiku-20241022", (100, 800), (50, 300), "/v1/messages",
     ["triage", "extract", "tag", "quick-answer"], 15),

    # Gemini Flash for high-volume cheap stuff
    ("google", "gemini-2.0-flash", (200, 1000), (100, 500), "/google/v1/generateContent",
     ["batch-process", "translate", "format"], 12),

    # GPT-4o expensive agent loop (the "oh no" moments)
    ("openai", "gpt-4o", (4000, 12000), (2000, 6000), "/v1/chat/completions",
     ["agent-loop", "deep-research", "multi-step"], 5),

    # Claude Opus for the big guns
    ("anthropic", "claude-opus-4-20250514", (3000, 8000), (1000, 4000), "/v1/messages",
     ["critical-analysis", "architecture", "complex-reasoning"], 3),

    # DeepSeek for cost-conscious tasks
    ("deepseek", "deepseek-chat", (500, 2000), (200, 1000), "/v1/chat/completions",
     ["draft", "brainstorm", "explore"], 8),

    # Groq for speed-critical
    ("groq", "llama-3.3-70b-versatile", (300, 1500), (100, 800), "/v1/chat/completions",
     ["real-time", "autocomplete", "streaming"], 10),

    # Failed requests (realistic: ~3% error rate)
    ("openai", "gpt-4o", (500, 2000), (0, 0), "/v1/chat/completions",
     ["error", "timeout"], 3),
]


def weighted_choice(scenarios):
    """Pick a scenario based on weights."""
    total = sum(s[6] for s in scenarios)
    r = random.uniform(0, total)
    cumulative = 0
    for s in scenarios:
        cumulative += s[6]
        if r <= cumulative:
            return s
    return scenarios[0]


def simulate_request():
    """Generate one realistic request log entry."""
    provider, model, in_range, out_range, endpoint, tags, _ = weighted_choice(SCENARIOS)

    input_tokens = random.randint(*in_range)
    output_tokens = random.randint(*out_range)
    tag = random.choice(tags)

    # Simulate errors
    is_error = tag in ("error", "timeout")
    status_code = random.choice([429, 500, 503]) if is_error else 200
    if is_error:
        output_tokens = 0

    # Realistic latency based on model and tokens
    base_latency = {
        "gpt-4o-mini": 300, "gpt-4o": 800, "gpt-4-turbo": 1200,
        "claude-sonnet-4-20250514": 900, "claude-3-5-haiku-20241022": 400,
        "claude-opus-4-20250514": 2000,
        "gemini-2.0-flash": 250, "deepseek-chat": 600,
        "llama-3.3-70b-versatile": 200,
    }.get(model, 500)

    latency_ms = int(base_latency + (output_tokens * 0.3) + random.gauss(0, 100))
    latency_ms = max(150, latency_ms)

    if is_error:
        latency_ms = random.randint(5000, 30000) if tag == "timeout" else random.randint(100, 300)

    cost = calculate_cost(model, input_tokens, output_tokens)

    log_request(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost=cost["input_cost"],
        output_cost=cost["output_cost"],
        total_cost=cost["total_cost"],
        latency_ms=latency_ms,
        status_code=status_code,
        endpoint=endpoint,
        tag=tag,
    )

    return {
        "provider": provider,
        "model": model,
        "tokens": f"{input_tokens:,} in / {output_tokens:,} out",
        "cost": f"${cost['total_cost']:.4f}",
        "latency": f"{latency_ms}ms",
        "tag": tag,
        "status": status_code,
    }


# ──────────────────────────────────────────────
# Seed historical data (so charts look full)
# ──────────────────────────────────────────────

def seed_history(hours=48, requests_per_hour=25):
    """
    Pre-fill the database with historical data so the dashboard
    charts aren't empty when you start recording.
    """
    import sqlite3
    from llm_cost_monitor.db import get_connection

    print(f"  Seeding {hours}h of historical data ({hours * requests_per_hour} requests)...")

    conn = get_connection()
    now = time.time()

    for h in range(hours, 0, -1):
        # Vary volume by "time of day" (simulate usage patterns)
        hour_of_day = (24 - h) % 24
        if 2 <= hour_of_day <= 7:
            count = random.randint(3, 10)   # quiet hours
        elif 9 <= hour_of_day <= 17:
            count = random.randint(20, 45)  # business hours peak
        else:
            count = random.randint(8, 20)   # evening

        for _ in range(count):
            scenario = weighted_choice(SCENARIOS)
            provider, model, in_range, out_range, endpoint, tags, _ = scenario

            input_tokens = random.randint(*in_range)
            output_tokens = random.randint(*out_range)
            tag = random.choice(tags)

            is_error = tag in ("error", "timeout")
            status_code = random.choice([429, 500, 503]) if is_error else 200
            if is_error:
                output_tokens = 0

            cost = calculate_cost(model, input_tokens, output_tokens)
            latency_ms = random.randint(150, 3000)

            ts = now - (h * 3600) + random.randint(0, 3599)

            conn.execute(
                """INSERT INTO requests
                (timestamp, provider, model, input_tokens, output_tokens, total_tokens,
                 input_cost, output_cost, total_cost, latency_ms, status_code, endpoint, metadata, tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)""",
                (ts, provider, model, input_tokens, output_tokens,
                 input_tokens + output_tokens,
                 cost["input_cost"], cost["output_cost"], cost["total_cost"],
                 latency_ms, status_code, endpoint, tag),
            )

    conn.commit()
    conn.close()
    print("  Done.\n")


# ──────────────────────────────────────────────
# Main demo loop
# ──────────────────────────────────────────────

COLORS = {
    "openai": "\033[92m",     # green
    "anthropic": "\033[93m",  # yellow
    "google": "\033[94m",     # blue
    "groq": "\033[95m",       # magenta
    "deepseek": "\033[96m",   # cyan
}
RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"


def main():
    init_db()

    print(f"""
{BOLD}╔══════════════════════════════════════════════════════╗
║         LLM Cost Monitor - Demo Mode                 ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  This will simulate realistic LLM traffic so you     ║
║  can screen-record the dashboard for your README.    ║
║                                                      ║
║  1. Make sure the server is running:                 ║
║     llm-cost-monitor start                           ║
║                                                      ║
║  2. Open http://localhost:8877 in your browser       ║
║                                                      ║
║  3. Start your screen recorder                       ║
║                                                      ║
║  4. Press Enter here to begin...                     ║
╚══════════════════════════════════════════════════════╝{RESET}
""")

    choice = input(f"  Seed 48h of historical data first? [Y/n] ").strip().lower()
    if choice != "n":
        seed_history()

    input(f"  {BOLD}Press Enter to start live traffic simulation...{RESET} ")
    print()

    total_cost = 0.0
    total_requests = 0
    running_cost_high = 0.0

    try:
        while True:
            req = simulate_request()
            total_requests += 1
            cost_val = float(req["cost"].replace("$", ""))
            total_cost += cost_val

            color = COLORS.get(req["provider"], "")
            status_icon = "✓" if req["status"] == 200 else "✗"
            status_color = "" if req["status"] == 200 else "\033[91m"

            # Track if we hit an expensive request (fun for the demo)
            expensive = ""
            if cost_val > 0.05:
                expensive = f" \033[91m← expensive!{RESET}"
            elif cost_val > 0.02:
                expensive = f" \033[93m← watch this one{RESET}"

            print(
                f"  {DIM}#{total_requests:04d}{RESET}  "
                f"{status_color}{status_icon}{RESET}  "
                f"{color}{req['provider']:10s}{RESET}  "
                f"{req['model']:38s}  "
                f"{req['tokens']:26s}  "
                f"\033[92m{req['cost']:>10s}{RESET}  "
                f"{DIM}{req['latency']:>8s}{RESET}  "
                f"{DIM}{req['tag']}{RESET}"
                f"{expensive}"
            )

            # Print running total every 10 requests
            if total_requests % 10 == 0:
                print(
                    f"\n  {BOLD}─── Running total: ${total_cost:.4f} "
                    f"across {total_requests} requests ───{RESET}\n"
                )

            # Variable delay to make it feel organic
            delay = random.uniform(0.3, 1.5)
            # Occasionally burst (agent doing multiple calls quickly)
            if random.random() < 0.15:
                delay = random.uniform(0.05, 0.2)
            time.sleep(delay)

    except KeyboardInterrupt:
        print(f"\n\n  {BOLD}Demo complete!{RESET}")
        print(f"  Total requests: {total_requests}")
        print(f"  Total cost:     ${total_cost:.4f}")
        print(f"\n  Now stop your screen recorder and convert to GIF.")
        print(f"  Recommended: https://gifcap.dev or `ffmpeg` for conversion.\n")


if __name__ == "__main__":
    main()
