"""SQLite storage for request logs and cost tracking."""

import json
import os
import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = os.path.expanduser("~/.llm-cost-monitor/costs.db")


def get_db_path():
    return os.environ.get("LLM_COST_DB", DEFAULT_DB_PATH)


def get_connection():
    db_path = get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            input_cost REAL DEFAULT 0.0,
            output_cost REAL DEFAULT 0.0,
            total_cost REAL DEFAULT 0.0,
            latency_ms INTEGER DEFAULT 0,
            status_code INTEGER DEFAULT 200,
            endpoint TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            tag TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_timestamp ON requests(timestamp);
        CREATE INDEX IF NOT EXISTS idx_provider ON requests(provider);
        CREATE INDEX IF NOT EXISTS idx_model ON requests(model);
        CREATE INDEX IF NOT EXISTS idx_tag ON requests(tag);

        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            limit_usd REAL NOT NULL,
            period TEXT NOT NULL DEFAULT 'daily',
            active INTEGER DEFAULT 1,
            hard_kill INTEGER DEFAULT 0
        );
    """)
    # Migrate: add hard_kill column if upgrading from an older schema
    try:
        conn.execute("ALTER TABLE budgets ADD COLUMN hard_kill INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # Column already exists
    conn.commit()
    conn.close()


def log_request(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    input_cost: float,
    output_cost: float,
    total_cost: float,
    latency_ms: int = 0,
    status_code: int = 200,
    endpoint: str = "",
    metadata: dict | None = None,
    tag: str = "",
):
    conn = get_connection()
    conn.execute(
        """INSERT INTO requests
        (timestamp, provider, model, input_tokens, output_tokens, total_tokens,
         input_cost, output_cost, total_cost, latency_ms, status_code, endpoint, metadata, tag)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            time.time(),
            provider,
            model,
            input_tokens,
            output_tokens,
            input_tokens + output_tokens,
            input_cost,
            output_cost,
            total_cost,
            latency_ms,
            status_code,
            endpoint,
            json.dumps(metadata or {}),
            tag,
        ),
    )
    conn.commit()
    conn.close()


def get_summary(hours: int = 24):
    """Get cost summary for the last N hours."""
    conn = get_connection()
    since = time.time() - (hours * 3600)

    row = conn.execute(
        """SELECT
            COUNT(*) as total_requests,
            COALESCE(SUM(total_cost), 0) as total_cost,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(AVG(latency_ms), 0) as avg_latency
        FROM requests WHERE timestamp >= ?""",
        (since,),
    ).fetchone()

    conn.close()
    return dict(row)


def get_cost_by_model(hours: int = 24):
    conn = get_connection()
    since = time.time() - (hours * 3600)

    rows = conn.execute(
        """SELECT model, provider,
            COUNT(*) as requests,
            SUM(total_cost) as total_cost,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens
        FROM requests WHERE timestamp >= ?
        GROUP BY model ORDER BY total_cost DESC""",
        (since,),
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_cost_over_time(hours: int = 168, bucket_minutes: int = 60):
    """Get cost bucketed over time."""
    conn = get_connection()
    since = time.time() - (hours * 3600)
    bucket_seconds = bucket_minutes * 60

    rows = conn.execute(
        """SELECT
            CAST((timestamp / ?) AS INTEGER) * ? as bucket,
            SUM(total_cost) as cost,
            COUNT(*) as requests,
            SUM(input_tokens + output_tokens) as tokens
        FROM requests WHERE timestamp >= ?
        GROUP BY bucket ORDER BY bucket ASC""",
        (bucket_seconds, bucket_seconds, since),
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_recent_requests(limit: int = 50):
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM requests ORDER BY timestamp DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cost_by_provider(hours: int = 24):
    conn = get_connection()
    since = time.time() - (hours * 3600)
    rows = conn.execute(
        """SELECT provider,
            COUNT(*) as requests,
            SUM(total_cost) as total_cost,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens
        FROM requests WHERE timestamp >= ?
        GROUP BY provider ORDER BY total_cost DESC""",
        (since,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cost_by_tag(hours: int = 24):
    conn = get_connection()
    since = time.time() - (hours * 3600)
    rows = conn.execute(
        """SELECT tag,
            COUNT(*) as requests,
            SUM(total_cost) as total_cost
        FROM requests WHERE timestamp >= ? AND tag != ''
        GROUP BY tag ORDER BY total_cost DESC""",
        (since,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_export_data(
    hours: int | None = 24,
    since_ts: float | None = None,
    until_ts: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """
    Fetch requests for export with optional filters.

    Priority: explicit since_ts/until_ts > hours > all data (hours=None).
    """
    conn = get_connection()

    conditions = []
    params = []

    if since_ts is not None:
        conditions.append("timestamp >= ?")
        params.append(since_ts)
    elif hours is not None:
        conditions.append("timestamp >= ?")
        params.append(time.time() - hours * 3600)

    if until_ts is not None:
        conditions.append("timestamp <= ?")
        params.append(until_ts)

    if model:
        conditions.append("model = ?")
        params.append(model)

    if provider:
        conditions.append("provider = ?")
        params.append(provider)

    if tag:
        conditions.append("tag = ?")
        params.append(tag)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM requests {where} ORDER BY timestamp ASC",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _budget_status(budget: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    """Compute current spend against a budget row and return a status dict."""
    period_hours = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720}
    hours = period_hours.get(budget["period"], 24)
    since = time.time() - (hours * 3600)

    spent = conn.execute(
        "SELECT COALESCE(SUM(total_cost), 0) as spent FROM requests WHERE timestamp >= ?",
        (since,),
    ).fetchone()

    return {
        "name": budget["name"],
        "limit": budget["limit_usd"],
        "spent": round(spent["spent"], 6),
        "remaining": round(budget["limit_usd"] - spent["spent"], 6),
        "exceeded": spent["spent"] >= budget["limit_usd"],
        "period": budget["period"],
        "hard_kill": bool(budget["hard_kill"]),
        "active": bool(budget["active"]),
    }


def check_budget(name: str) -> dict | None:
    """Check if a named budget limit has been exceeded. Returns None if not found."""
    conn = get_connection()
    budget = conn.execute(
        "SELECT * FROM budgets WHERE name = ? AND active = 1", (name,)
    ).fetchone()

    if not budget:
        conn.close()
        return None

    result = _budget_status(budget, conn)
    conn.close()
    return result


def check_all_budgets() -> list[dict]:
    """Return status for all active budgets."""
    conn = get_connection()
    budgets = conn.execute("SELECT * FROM budgets WHERE active = 1").fetchall()
    result = [_budget_status(b, conn) for b in budgets]
    conn.close()
    return result


def set_budget(name: str, limit_usd: float, period: str = "daily", hard_kill: bool = False) -> dict:
    """Create or update a named budget. Returns the new status."""
    valid_periods = {"hourly", "daily", "weekly", "monthly"}
    if period not in valid_periods:
        raise ValueError(f"period must be one of: {', '.join(sorted(valid_periods))}")

    conn = get_connection()
    conn.execute(
        """INSERT INTO budgets (name, limit_usd, period, hard_kill, active)
           VALUES (?, ?, ?, ?, 1)
           ON CONFLICT(name) DO UPDATE SET
               limit_usd = excluded.limit_usd,
               period = excluded.period,
               hard_kill = excluded.hard_kill,
               active = 1""",
        (name, limit_usd, period, int(hard_kill)),
    )
    conn.commit()
    budget = conn.execute("SELECT * FROM budgets WHERE name = ?", (name,)).fetchone()
    result = _budget_status(budget, conn)
    conn.close()
    return result


def delete_budget(name: str) -> bool:
    """Delete a budget by name. Returns True if it existed."""
    conn = get_connection()
    cursor = conn.execute("DELETE FROM budgets WHERE name = ?", (name,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def list_budgets() -> list[dict]:
    """Return all budgets (active and inactive) with current spend status."""
    conn = get_connection()
    budgets = conn.execute("SELECT * FROM budgets ORDER BY name").fetchall()
    result = [_budget_status(b, conn) for b in budgets]
    conn.close()
    return result
