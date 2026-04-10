"""Tests for server.py — API endpoints via FastAPI AsyncClient."""

import json

import pytest
from llm_cost_monitor.db import log_request, set_budget


# ── Helper ─────────────────────────────────────────────────────────────────────

def _log(provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50,
         input_cost=0.00025, output_cost=0.0005, total_cost=0.00075,
         latency_ms=500, tag=""):
    log_request(provider, model, input_tokens, output_tokens,
                input_cost, output_cost, total_cost, latency_ms, 200,
                "/v1/chat", {}, tag)


# ── Dashboard API ──────────────────────────────────────────────────────────────

class TestSummaryEndpoint:
    async def test_returns_expected_keys(self, client):
        resp = await client.get("/api/summary")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("total_requests", "total_cost", "total_input_tokens", "total_output_tokens", "avg_latency"):
            assert key in data

    async def test_reflects_logged_requests(self, client, tmp_db):
        _log(total_cost=0.01)
        _log(total_cost=0.02)
        resp = await client.get("/api/summary?hours=24")
        data = resp.json()
        assert data["total_requests"] == 2
        assert data["total_cost"] == pytest.approx(0.03)

    async def test_empty_db_returns_zeros(self, client):
        data = (await client.get("/api/summary")).json()
        assert data["total_requests"] == 0
        assert data["total_cost"] == 0.0


class TestByModelEndpoint:
    async def test_groups_by_model(self, client, tmp_db):
        _log(model="gpt-4o", total_cost=0.01)
        _log(model="gpt-4o-mini", total_cost=0.005)
        data = (await client.get("/api/by-model")).json()
        models = {r["model"] for r in data}
        assert "gpt-4o" in models
        assert "gpt-4o-mini" in models

    async def test_empty_returns_list(self, client):
        data = (await client.get("/api/by-model")).json()
        assert isinstance(data, list)


class TestByProviderEndpoint:
    async def test_groups_by_provider(self, client, tmp_db):
        _log(provider="openai")
        _log(provider="anthropic")
        data = (await client.get("/api/by-provider")).json()
        providers = {r["provider"] for r in data}
        assert "openai" in providers
        assert "anthropic" in providers


class TestByTagEndpoint:
    async def test_excludes_untagged(self, client, tmp_db):
        _log(tag="ci")
        _log(tag="")
        data = (await client.get("/api/by-tag")).json()
        assert len(data) == 1
        assert data[0]["tag"] == "ci"


class TestRecentEndpoint:
    async def test_default_limit(self, client, tmp_db):
        for _ in range(5):
            _log()
        data = (await client.get("/api/recent")).json()
        assert len(data) == 5

    async def test_custom_limit(self, client, tmp_db):
        for _ in range(10):
            _log()
        data = (await client.get("/api/recent?limit=3")).json()
        assert len(data) == 3


class TestOverTimeEndpoint:
    async def test_returns_list(self, client):
        data = (await client.get("/api/over-time")).json()
        assert isinstance(data, list)


# ── Export endpoint ────────────────────────────────────────────────────────────

class TestExportEndpoint:
    async def test_json_export_structure(self, client, tmp_db):
        _log(total_cost=0.01)
        resp = await client.get("/api/export?format=json&hours=24")
        assert resp.status_code == 200
        data = resp.json()
        assert "exported_at" in data
        assert "summary" in data
        assert "requests" in data
        assert data["summary"]["total_requests"] == 1
        assert data["summary"]["total_cost"] == pytest.approx(0.01)

    async def test_csv_export_has_header_row(self, client, tmp_db):
        _log()
        resp = await client.get("/api/export?format=csv&hours=24")
        assert resp.status_code == 200
        lines = resp.text.strip().splitlines()
        assert "timestamp" in lines[0]
        assert "model" in lines[0]
        assert "total_cost" in lines[0]

    async def test_csv_export_has_data_row(self, client, tmp_db):
        _log(model="gpt-4o", total_cost=0.005)
        resp = await client.get("/api/export?format=csv&hours=24")
        lines = resp.text.strip().splitlines()
        assert len(lines) == 2  # header + 1 data row
        assert "gpt-4o" in lines[1]

    async def test_export_all_ignores_hours(self, client, tmp_db):
        _log()
        resp = await client.get("/api/export?format=json&all=true")
        data = resp.json()
        assert data["summary"]["total_requests"] == 1

    async def test_export_filter_by_provider(self, client, tmp_db):
        _log(provider="openai")
        _log(provider="anthropic")
        resp = await client.get("/api/export?format=json&hours=24&provider=openai")
        data = resp.json()
        assert data["summary"]["total_requests"] == 1
        assert data["requests"][0]["provider"] == "openai"

    async def test_export_filter_by_model(self, client, tmp_db):
        _log(model="gpt-4o")
        _log(model="gpt-4o-mini")
        resp = await client.get("/api/export?format=json&hours=24&model=gpt-4o-mini")
        data = resp.json()
        assert all(r["model"] == "gpt-4o-mini" for r in data["requests"])

    async def test_export_content_disposition_csv(self, client, tmp_db):
        _log()
        resp = await client.get("/api/export?format=csv")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert ".csv" in resp.headers.get("content-disposition", "")

    async def test_export_content_disposition_json(self, client, tmp_db):
        _log()
        resp = await client.get("/api/export?format=json")
        assert ".json" in resp.headers.get("content-disposition", "")

    async def test_export_empty_db_returns_empty_requests(self, client):
        resp = await client.get("/api/export?format=json&all=true")
        data = resp.json()
        assert data["requests"] == []
        assert data["summary"]["total_requests"] == 0


# ── Budget endpoints ───────────────────────────────────────────────────────────

class TestBudgetEndpoints:
    async def test_list_budgets_empty(self, client):
        resp = await client.get("/api/budgets")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_budget(self, client, tmp_db):
        resp = await client.post("/api/budgets", json={
            "name": "default", "limit_usd": 5.0, "period": "daily", "hard_kill": False
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "default"
        assert data["limit"] == 5.0
        assert data["hard_kill"] is False

    async def test_list_budgets_after_create(self, client, tmp_db):
        await client.post("/api/budgets", json={"name": "test", "limit_usd": 2.0})
        budgets = (await client.get("/api/budgets")).json()
        assert len(budgets) == 1
        assert budgets[0]["name"] == "test"

    async def test_delete_budget(self, client, tmp_db):
        await client.post("/api/budgets", json={"name": "temp", "limit_usd": 1.0})
        resp = await client.delete("/api/budgets/temp")
        assert resp.status_code == 200
        assert (await client.get("/api/budgets")).json() == []

    async def test_delete_nonexistent_budget_returns_404(self, client):
        resp = await client.delete("/api/budgets/ghost")
        assert resp.status_code == 404

    async def test_create_budget_invalid_period_returns_400(self, client, tmp_db):
        resp = await client.post("/api/budgets", json={"name": "x", "limit_usd": 1.0, "period": "yearly"})
        assert resp.status_code == 400

    async def test_create_budget_missing_limit_returns_400(self, client, tmp_db):
        resp = await client.post("/api/budgets", json={"name": "x"})
        assert resp.status_code == 400

    async def test_budget_status_not_exceeded(self, client, tmp_db):
        await client.post("/api/budgets", json={"name": "default", "limit_usd": 100.0})
        _log(total_cost=0.50)
        data = (await client.get("/api/budgets/status")).json()
        assert data["any_exceeded"] is False
        assert data["hard_kill_triggered"] is False

    async def test_budget_status_exceeded(self, client, tmp_db):
        await client.post("/api/budgets", json={"name": "default", "limit_usd": 0.001})
        _log(total_cost=1.0)
        data = (await client.get("/api/budgets/status")).json()
        assert data["any_exceeded"] is True


class TestBudgetHardKill:
    async def test_hard_kill_blocks_proxy_request(self, client, tmp_db):
        """When a hard-kill budget is exceeded, proxy endpoints must return 429."""
        set_budget("default", 0.001, "daily", hard_kill=True)
        _log(total_cost=1.0)  # exceed the budget

        # Any proxy endpoint should be blocked
        resp = await client.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 429
        data = resp.json()
        assert data["error"] == "budget_exceeded"
        assert "budget" in data

    async def test_soft_budget_does_not_block(self, client, tmp_db):
        """A soft budget (hard_kill=False) should NOT return 429.
        The request will attempt to reach the real API and fail with 502,
        but it must NOT be blocked by the budget check."""
        set_budget("default", 0.001, "daily", hard_kill=False)
        _log(total_cost=1.0)

        resp = await client.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        })
        # 429 would mean budget blocked it — that must NOT happen
        assert resp.status_code != 429
