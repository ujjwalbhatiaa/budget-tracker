"""Tests for GET /api/budget-status/totals. Run with: pytest."""

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


def test_totals_aggregates_caps_and_spend(client):
    _cap(client, "groceries", 400)
    _cap(client, "dining", 50)
    _txn(client, -450, "groceries")  # over its cap
    _txn(client, -20, "dining")
    _txn(client, -999, "housing")  # no cap -> excluded from totals
    _txn(client, -10, "groceries", txn_date="2026-08-05")  # other month
    r = client.get("/api/budget-status/totals?month=2026-09")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "month": "2026-09",
        "categories": 2,
        "total_limit": 450,
        "total_spent": 470,
        "total_remaining": -20,
        "pct_used": 104.4,
        "over_count": 1,
    }


def test_totals_empty_and_bad_month(client):
    r = client.get("/api/budget-status/totals?month=2026-09")
    assert r.json() == {
        "month": "2026-09",
        "categories": 0,
        "total_limit": 0,
        "total_spent": 0,
        "total_remaining": 0,
        "pct_used": 0.0,
        "over_count": 0,
    }
    assert client.get("/api/budget-status/totals?month=2026-13").status_code == 422
    # "totals" must not be swallowed by the /{category} route.
    _cap(client, "groceries", 100)
    assert client.get("/api/budget-status/totals").status_code == 200


def test_totals_category_without_spending_counts_zero(client):
    _cap(client, "groceries", 400)
    _txn(client, -100, "dining")  # uncapped category, ignored
    r = client.get("/api/budget-status/totals?month=2026-09")
    assert r.json()["total_spent"] == 0
    assert r.json()["total_remaining"] == 400
    assert r.json()["over_count"] == 0
