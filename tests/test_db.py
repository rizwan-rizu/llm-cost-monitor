"""Tests for db.py — storage, queries, budget logic, and schema migration."""

import sqlite3
import time

import pytest
from llm_cost_monitor.db import (
    init_db,
    log_request,
    get_summary,
    get_cost_by_model,
    get_cost_by_provider,
    get_cost_by_tag,
    get_recent_requests,
    get_export_data,
    set_budget,
    delete_budget,
    list_budgets,
    check_all_budgets,
    get_connection,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _log(provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50,
         input_cost=0.00025, output_cost=0.0005, total_cost=0.00075,
         latency_ms=500, status_code=200, endpoint="/v1/chat", tag=""):
    log_request(provider, model, input_tokens, output_tokens,
                input_cost, output_cost, total_cost, latency_ms,
                status_code, endpoint, {}, tag)


# ── init_db ────────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_requests_table(self, tmp_db):
        conn = get_connection()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "requests" in tables

    def test_creates_budgets_table(self, tmp_db):
        conn = get_connection()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "budgets" in tables

    def test_migration_adds_hard_kill_column(self, tmp_path, monkeypatch):
        """Simulate upgrading from an old DB that has no hard_kill column."""
        db = str(tmp_path / "old.db")
        monkeypatch.setenv("LLM_COST_DB", db)

        # Create old-style schema without hard_kill
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                limit_usd REAL NOT NULL,
                period TEXT NOT NULL DEFAULT 'daily',
                active INTEGER DEFAULT 1
            )
        """)
        conn.commit()
        conn.close()

        # Running init_db should migrate without error
        init_db()

        conn = sqlite3.connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(budgets)").fetchall()}
        conn.close()
        assert "hard_kill" in cols


# ── log_request / get_summary ─────────────────────────────────────────────────

class TestLogAndSummary:
    def test_log_and_retrieve_summary(self, tmp_db):
        _log(total_cost=0.01)
        _log(total_cost=0.02)
        summary = get_summary(hours=24)
        assert summary["total_requests"] == 2
        assert summary["total_cost"] == pytest.approx(0.03)

    def test_summary_empty_db(self, tmp_db):
        summary = get_summary(hours=24)
        assert summary["total_requests"] == 0
        assert summary["total_cost"] == 0.0

    def test_summary_respects_time_window(self, tmp_db):
        _log(total_cost=0.05)
        # Summary for 0 hours should return nothing
        summary = get_summary(hours=0)
        assert summary["total_requests"] == 0

    def test_token_counts_accumulated(self, tmp_db):
        _log(input_tokens=100, output_tokens=50)
        _log(input_tokens=200, output_tokens=80)
        summary = get_summary(hours=24)
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 130

    def test_avg_latency(self, tmp_db):
        _log(latency_ms=400)
        _log(latency_ms=600)
        summary = get_summary(hours=24)
        assert summary["avg_latency"] == pytest.approx(500.0)


# ── get_cost_by_model / provider / tag ────────────────────────────────────────

class TestBreakdowns:
    def test_by_model(self, tmp_db):
        _log(model="gpt-4o", total_cost=0.01)
        _log(model="gpt-4o-mini", total_cost=0.005)
        rows = get_cost_by_model(hours=24)
        models = {r["model"] for r in rows}
        assert "gpt-4o" in models
        assert "gpt-4o-mini" in models

    def test_by_model_sorted_by_cost_desc(self, tmp_db):
        _log(model="cheap", total_cost=0.001)
        _log(model="expensive", total_cost=1.0)
        rows = get_cost_by_model(hours=24)
        assert rows[0]["model"] == "expensive"

    def test_by_provider(self, tmp_db):
        _log(provider="openai", total_cost=0.01)
        _log(provider="anthropic", total_cost=0.02)
        rows = get_cost_by_provider(hours=24)
        providers = {r["provider"] for r in rows}
        assert "openai" in providers
        assert "anthropic" in providers

    def test_by_tag_excludes_empty_tags(self, tmp_db):
        _log(tag="agent", total_cost=0.01)
        _log(tag="", total_cost=0.02)
        rows = get_cost_by_tag(hours=24)
        assert all(r["tag"] != "" for r in rows)
        assert len(rows) == 1

    def test_recent_requests_limit(self, tmp_db):
        for _ in range(10):
            _log()
        rows = get_recent_requests(limit=5)
        assert len(rows) == 5

    def test_recent_requests_ordered_desc(self, tmp_db):
        _log(total_cost=0.01)
        time.sleep(0.01)
        _log(total_cost=0.99)
        rows = get_recent_requests(limit=2)
        assert rows[0]["total_cost"] == pytest.approx(0.99)


# ── get_export_data ────────────────────────────────────────────────────────────

class TestExportData:
    def test_export_all(self, tmp_db):
        _log(model="gpt-4o")
        _log(model="gpt-4o-mini")
        rows = get_export_data(hours=None)
        assert len(rows) == 2

    def test_export_filter_by_model(self, tmp_db):
        _log(model="gpt-4o")
        _log(model="gpt-4o-mini")
        rows = get_export_data(hours=None, model="gpt-4o")
        assert len(rows) == 1
        assert rows[0]["model"] == "gpt-4o"

    def test_export_filter_by_provider(self, tmp_db):
        _log(provider="openai")
        _log(provider="anthropic")
        rows = get_export_data(hours=None, provider="anthropic")
        assert len(rows) == 1
        assert rows[0]["provider"] == "anthropic"

    def test_export_filter_by_tag(self, tmp_db):
        _log(tag="ci")
        _log(tag="prod")
        rows = get_export_data(hours=None, tag="ci")
        assert len(rows) == 1
        assert rows[0]["tag"] == "ci"

    def test_export_time_window(self, tmp_db):
        _log()
        rows = get_export_data(hours=0)
        assert len(rows) == 0

    def test_export_ordered_ascending(self, tmp_db):
        _log(total_cost=0.01)
        time.sleep(0.01)
        _log(total_cost=0.99)
        rows = get_export_data(hours=None)
        assert rows[0]["total_cost"] == pytest.approx(0.01)
        assert rows[1]["total_cost"] == pytest.approx(0.99)

    def test_export_combined_filters(self, tmp_db):
        _log(provider="openai", model="gpt-4o", tag="ci")
        _log(provider="openai", model="gpt-4o-mini", tag="prod")
        _log(provider="anthropic", model="claude-3-5-haiku-20241022", tag="ci")
        rows = get_export_data(hours=None, provider="openai", tag="ci")
        assert len(rows) == 1
        assert rows[0]["model"] == "gpt-4o"


# ── Budget management ──────────────────────────────────────────────────────────

class TestBudgets:
    def test_set_and_list_budget(self, tmp_db):
        set_budget("default", 5.0, "daily", hard_kill=False)
        budgets = list_budgets()
        assert len(budgets) == 1
        assert budgets[0]["name"] == "default"
        assert budgets[0]["limit"] == 5.0
        assert budgets[0]["hard_kill"] is False

    def test_set_hard_kill_budget(self, tmp_db):
        set_budget("ci", 1.0, "hourly", hard_kill=True)
        budgets = list_budgets()
        assert budgets[0]["hard_kill"] is True
        assert budgets[0]["period"] == "hourly"

    def test_update_existing_budget(self, tmp_db):
        set_budget("default", 5.0)
        set_budget("default", 10.0, hard_kill=True)
        budgets = list_budgets()
        assert len(budgets) == 1
        assert budgets[0]["limit"] == 10.0
        assert budgets[0]["hard_kill"] is True

    def test_delete_budget(self, tmp_db):
        set_budget("temp", 1.0)
        assert delete_budget("temp") is True
        assert list_budgets() == []

    def test_delete_nonexistent_budget(self, tmp_db):
        assert delete_budget("ghost") is False

    def test_budget_not_exceeded_when_under_limit(self, tmp_db):
        set_budget("default", 100.0)
        _log(total_cost=0.50)
        statuses = check_all_budgets()
        assert statuses[0]["exceeded"] is False
        assert statuses[0]["spent"] == pytest.approx(0.50)

    def test_budget_exceeded_when_over_limit(self, tmp_db):
        set_budget("default", 0.001)
        _log(total_cost=1.0)
        statuses = check_all_budgets()
        assert statuses[0]["exceeded"] is True

    def test_remaining_calculated_correctly(self, tmp_db):
        set_budget("default", 10.0)
        _log(total_cost=3.0)
        statuses = check_all_budgets()
        assert statuses[0]["remaining"] == pytest.approx(7.0)

    def test_invalid_period_raises(self, tmp_db):
        with pytest.raises(ValueError, match="period"):
            set_budget("bad", 1.0, period="yearly")

    def test_multiple_budgets_tracked_independently(self, tmp_db):
        set_budget("a", 5.0)
        set_budget("b", 0.001)
        _log(total_cost=1.0)
        statuses = {s["name"]: s for s in check_all_budgets()}
        assert statuses["a"]["exceeded"] is False
        assert statuses["b"]["exceeded"] is True
