"""Tests for GET /api/budget-status/alerts. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

# Same DB path convention as test_api.py so the module-level DB_PATH
# bindings in app.main / app.budgets agree within one pytest process.
TEST_DB = "/tmp/budget-tracker/test.db"
os.environ["BUDGET_DB"] = TEST_DB
os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _txn(c, amount, category, txn_date="2026-09-05"):
    r = c.post("/api/transactions", json={
        "date": txn_date, "description": "x", "amount": amount,
        "category": category})
    assert r.status_code == 201, r.text


def _cap(c, category, limit):
    r = c.put(f"/api/budgets/{category}", json={"monthly_limit": limit})
    assert r.status_code == 200, r.text


def test_alerts_default_threshold_and_order(client):
    _cap(client, "groceries", 100)
    _cap(client, "dining", 100)
    _cap(client, "transit", 100)
    _txn(client, -120, "groceries")  # 120% — over cap, always alerts
    _txn(client, -85, "dining")  # 85% — above the default 80 threshold
    _txn(client, -50, "transit")  # 50% — below threshold, excluded
    r = client.get("/api/budget-status/alerts?month=2026-09")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["category"] for row in rows] == ["groceries", "dining"]
    assert rows[0]["pct_used"] == 120.0 and rows[0]["over"] is True
    assert rows[1]["pct_used"] == 85.0 and rows[1]["over"] is False


def test_alerts_custom_threshold_and_bad_month(client):
    _cap(client, "groceries", 100)
    _txn(client, -60, "groceries")
    r = client.get("/api/budget-status/alerts?month=2026-09&threshold=50")
    assert [row["category"] for row in r.json()] == ["groceries"]
    r = client.get("/api/budget-status/alerts?month=2026-09&threshold=61")
    assert r.json() == []
    assert client.get("/api/budget-status/alerts?month=2026-13").status_code == 422
    assert client.get("/api/budget-status/alerts?threshold=101").status_code == 422
    # "alerts" must not be swallowed by the /{category} route.
    assert client.get("/api/budget-status/alerts").status_code == 200
