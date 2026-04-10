"""Shared fixtures for all test modules."""

import os
import tempfile

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point LLM_COST_DB at a fresh temp file for each test."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LLM_COST_DB", db)

    from llm_cost_monitor.db import init_db
    init_db()
    yield db


@pytest.fixture
async def client(tmp_db):
    """AsyncClient wired to the FastAPI app with an isolated DB."""
    from llm_cost_monitor.server import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
