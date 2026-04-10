"""CLI entry point for LLM Cost Monitor."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="llm-cost-monitor",
        description="Transparent LLM cost tracking proxy with a real-time dashboard.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start the proxy server")
    start_parser.add_argument("--port", "-p", type=int, default=8877, help="Port to run on (default: 8877)")
    start_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")

    # Summary command
    summary_parser = subparsers.add_parser("summary", help="Show cost summary")
    summary_parser.add_argument("--hours", type=int, default=24, help="Hours to look back (default: 24)")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export cost data to CSV or JSON")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv)")
    export_parser.add_argument("--output", "-o", default=None, help="Output file path (default: stdout)")
    export_parser.add_argument("--hours", type=int, default=24, help="Hours to look back (default: 24)")
    export_parser.add_argument("--all", action="store_true", help="Export all data (ignores --hours)")
    export_parser.add_argument("--model", default=None, help="Filter by model name")
    export_parser.add_argument("--provider", default=None, help="Filter by provider")
    export_parser.add_argument("--tag", default=None, help="Filter by tag")

    # Budget commands
    budget_parser = subparsers.add_parser("budget", help="Manage spending budgets")
    budget_sub = budget_parser.add_subparsers(dest="budget_command")

    budget_set = budget_sub.add_parser("set", help="Create or update a budget")
    budget_set.add_argument("--name", default="default", help="Budget name (default: 'default')")
    budget_set.add_argument("--limit", type=float, required=True, help="Spending limit in USD")
    budget_set.add_argument("--period", choices=["hourly", "daily", "weekly", "monthly"], default="daily")
    budget_set.add_argument("--hard-kill", action="store_true", help="Abort requests when budget is exceeded")

    budget_sub.add_parser("list", help="List all budgets with current spend")

    budget_del = budget_sub.add_parser("delete", help="Delete a budget")
    budget_del.add_argument("name", help="Budget name to delete")

    # Reset command
    subparsers.add_parser("reset", help="Clear all logged data")

    args = parser.parse_args()

    if args.command == "start":
        import uvicorn
        from .db import init_db

        init_db()
        print(f"""
╔══════════════════════════════════════════════════════╗
║           LLM Cost Monitor v0.1.0                    ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  Dashboard:  http://{args.host}:{args.port}              ║
║                                                      ║
║  Proxy endpoints:                                    ║
║    OpenAI:    http://{args.host}:{args.port}/v1          ║
║    Anthropic: http://{args.host}:{args.port}/anthropic/v1║
║    Google:    http://{args.host}:{args.port}/google      ║
║    Groq:      http://{args.host}:{args.port}/groq/v1     ║
║                                                      ║
║  Just change your base_url and you're done.          ║
╚══════════════════════════════════════════════════════╝
""")
        uvicorn.run(
            "llm_cost_monitor.server:app",
            host=args.host,
            port=args.port,
            log_level="info",
        )

    elif args.command == "summary":
        from .db import init_db, get_summary, get_cost_by_model

        init_db()
        s = get_summary(args.hours)
        print(f"\n--- Cost Summary (last {args.hours}h) ---")
        print(f"  Requests:      {s['total_requests']}")
        print(f"  Total Cost:    ${s['total_cost']:.4f}")
        print(f"  Input Tokens:  {s['total_input_tokens']:,}")
        print(f"  Output Tokens: {s['total_output_tokens']:,}")
        print(f"  Avg Latency:   {s['avg_latency']:.0f}ms")

        models = get_cost_by_model(args.hours)
        if models:
            print(f"\n  By Model:")
            for m in models:
                print(f"    {m['model']:40s} ${m['total_cost']:.4f}  ({m['requests']} reqs)")

    elif args.command == "export":
        import csv
        import io
        import sys
        from datetime import datetime, timezone
        from .db import init_db, get_export_data, get_summary

        init_db()

        rows = get_export_data(
            hours=None if args.all else args.hours,
            model=args.model,
            provider=args.provider,
            tag=args.tag,
        )

        if args.format == "csv":
            output = io.StringIO()
            fieldnames = [
                "timestamp", "model", "provider",
                "input_tokens", "output_tokens", "total_tokens",
                "input_cost", "output_cost", "total_cost",
                "latency_ms", "status_code", "tag", "endpoint",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                row["timestamp"] = datetime.fromtimestamp(
                    row["timestamp"], tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                writer.writerow(row)
            content = output.getvalue()
        else:
            summary = {
                "total_requests": len(rows),
                "total_cost": round(sum(r["total_cost"] for r in rows), 6),
                "total_input_tokens": sum(r["input_tokens"] for r in rows),
                "total_output_tokens": sum(r["output_tokens"] for r in rows),
            }
            for row in rows:
                row["timestamp"] = datetime.fromtimestamp(
                    row["timestamp"], tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "filters": {
                    "hours": None if args.all else args.hours,
                    "all": args.all,
                    "model": args.model,
                    "provider": args.provider,
                    "tag": args.tag,
                },
                "summary": summary,
                "requests": rows,
            }
            import json as _json
            content = _json.dumps(payload, indent=2)

        if args.output:
            with open(args.output, "w") as f:
                f.write(content)
            print(f"Exported {len(rows)} record(s) to {args.output}")
        else:
            sys.stdout.write(content)

    elif args.command == "budget":
        from .db import init_db, set_budget, list_budgets, delete_budget

        init_db()

        if args.budget_command == "set":
            result = set_budget(args.name, args.limit, args.period, args.hard_kill)
            kill_label = " [HARD KILL]" if result["hard_kill"] else ""
            print(f"\nBudget '{result['name']}' set{kill_label}")
            print(f"  Limit:   ${result['limit']:.4f} / {result['period']}")
            print(f"  Spent:   ${result['spent']:.4f}")
            print(f"  Status:  {'EXCEEDED' if result['exceeded'] else 'OK'}")

        elif args.budget_command == "list":
            budgets = list_budgets()
            if not budgets:
                print("No budgets configured. Use: llm-cost-monitor budget set --limit <USD>")
            else:
                print(f"\n{'NAME':<20} {'PERIOD':<10} {'LIMIT':>10} {'SPENT':>10} {'REMAINING':>12} {'STATUS'}")
                print("-" * 72)
                for b in budgets:
                    status = "EXCEEDED" if b["exceeded"] else "OK"
                    if b["hard_kill"] and b["exceeded"]:
                        status = "KILLED"
                    print(
                        f"{b['name']:<20} {b['period']:<10} "
                        f"${b['limit']:>9.4f} ${b['spent']:>9.4f} "
                        f"${b['remaining']:>11.4f} {status}"
                    )

        elif args.budget_command == "delete":
            from .db import delete_budget
            if delete_budget(args.name):
                print(f"Budget '{args.name}' deleted.")
            else:
                print(f"Budget '{args.name}' not found.")
        else:
            budget_parser.print_help()

    elif args.command == "reset":
        import os
        from .db import get_db_path

        db_path = get_db_path()
        if os.path.exists(db_path):
            confirm = input(f"Delete {db_path}? [y/N] ")
            if confirm.lower() == "y":
                os.remove(db_path)
                print("Data cleared.")
            else:
                print("Cancelled.")
        else:
            print("No data to clear.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
