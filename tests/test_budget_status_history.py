"""Tests for GET /api/budget-status/{category}/history. Run with pytest."""

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


def test_history_last_months_oldest_first(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    _txn(client, -100, "groceries", "2026-07-05")
    _txn(client, -150, "groceries", "2026-09-05")
    _txn(client, -50, "groceries", "2026-09-20")
    _txn(client, 200, "groceries", "2026-09-10")  # income: excluded
    r = client.get("/api/budget-status/groceries/history",
                   params={"month": "2026-09", "months": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["month"] for b in body] == ["2026-07", "2026-08", "2026-09"]
    assert body[0]["spent"] == 100 and body[0]["over"] is False
    assert body[1]["spent"] == 0  # no spending month still appears
    assert body[2]["spent"] == 200 and body[2]["remaining"] == 200


def test_history_year_boundary_and_defaults(client):
    client.put("/api/budgets/dining", json={"monthly_limit": 100})
    _txn(client, -130, "dining", "2025-12-05")
    r = client.get("/api/budget-status/dining/history",
                   params={"month": "2026-01", "months": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["month"] for b in body] == ["2025-12", "2026-01"]
    assert body[0]["spent"] == 130 and body[0]["over"] is True
    assert body[1]["spent"] == 0


def test_history_404_bad_month_and_bad_months(client):
    assert client.get("/api/budget-status/none/history",
                      params={"month": "2026-09"}).status_code == 404
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    assert client.get("/api/budget-status/groceries/history",
                      params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/budget-status/groceries/history",
                      params={"month": "2026-09", "months": 0}).status_code == 422
    assert client.get("/api/budget-status/groceries/history",
                      params={"month": "2026-09", "months": 13}).status_code == 422
    # Category names are case-insensitive, like the single-month endpoint.
    r = client.get("/api/budget-status/GROCERIES/history",
                   params={"month": "2026-09", "months": 1})
    assert r.status_code == 200, r.text
    assert r.json()[0]["category"] == "groceries"
