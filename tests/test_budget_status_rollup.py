"""Tests for GET /api/budget-status/rollup. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

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


def _txn(c, amount, category, txn_date):
    r = c.post("/api/transactions", json={
        "date": txn_date, "description": "x", "amount": amount,
        "category": category})
    assert r.status_code == 201, r.text


def test_rollup_last_months_oldest_first(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    client.put("/api/budgets/dining", json={"monthly_limit": 50})
    _txn(client, -100, "groceries", "2026-07-05")
    _txn(client, -450, "groceries", "2026-09-05")  # over its cap
    _txn(client, -20, "dining", "2026-09-10")
    _txn(client, -999, "housing", "2026-09-12")  # no cap -> excluded
    _txn(client, 200, "groceries", "2026-09-15")  # income: excluded
    r = client.get("/api/budget-status/rollup",
                   params={"month": "2026-09", "months": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["month"] for b in body] == ["2026-07", "2026-08", "2026-09"]
    assert body[0]["total_spent"] == 100
    assert body[0]["total_limit"] == 450
    assert body[0]["over_count"] == 0
    # Empty month still appears, with zeros for spend but caps intact.
    assert body[1]["total_spent"] == 0
    assert body[1]["total_limit"] == 450
    assert body[2]["total_spent"] == 470
    assert body[2]["over_count"] == 1
    assert body[2]["pct_used"] == 104.4


def test_rollup_year_boundary_and_defaults(client):
    client.put("/api/budgets/dining", json={"monthly_limit": 100})
    _txn(client, -130, "dining", "2025-12-05")
    r = client.get("/api/budget-status/rollup",
                   params={"month": "2026-01", "months": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["month"] for b in body] == ["2025-12", "2026-01"]
    assert body[0]["total_spent"] == 130 and body[0]["over_count"] == 1
    assert body[1]["total_spent"] == 0 and body[1]["over_count"] == 0
    # Defaults: 6 months ending at the current month.
    r = client.get("/api/budget-status/rollup")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 6


def test_rollup_bad_month_and_bad_months(client):
    assert client.get("/api/budget-status/rollup",
                      params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/budget-status/rollup",
                      params={"month": "2026-09", "months": 0}).status_code == 422
    assert client.get("/api/budget-status/rollup",
                      params={"month": "2026-09", "months": 13}).status_code == 422
    # "rollup" must not be swallowed by the /{category} route.
    r = client.get("/api/budget-status/rollup",
                   params={"month": "2026-09", "months": 1})
    assert r.status_code == 200, r.text
    assert r.json()[0] == {
        "month": "2026-09",
        "categories": 0,
        "total_limit": 0,
        "total_spent": 0,
        "total_remaining": 0,
        "pct_used": 0.0,
        "over_count": 0,
    }
