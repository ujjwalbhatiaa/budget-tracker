"""Tests for GET /api/budget-status/{category}. Run with pytest."""

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


def _txn(c, amount, category, txn_date="2026-09-05"):
    r = c.post("/api/transactions", json={
        "date": txn_date, "description": "x", "amount": amount,
        "category": category})
    assert r.status_code == 201, r.text


def test_single_category_status(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    _txn(client, -120, "groceries")
    _txn(client, -30, "groceries", "2026-09-20")
    _txn(client, -50, "groceries", "2026-08-05")  # other month: excluded
    _txn(client, 200, "groceries")  # income: excluded from spent
    r = client.get("/api/budget-status/groceries", params={"month": "2026-09"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "category": "groceries", "month": "2026-09",
        "monthly_limit": 400, "spent": 150, "remaining": 250,
        "pct_used": 37.5, "over": False,
    }


def test_single_category_status_case_insensitive_and_over(client):
    client.put("/api/budgets/Dining", json={"monthly_limit": 100})
    _txn(client, -130, "dining")
    r = client.get("/api/budget-status/DINING", params={"month": "2026-09"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "dining"
    assert body["spent"] == 130 and body["over"] is True
    assert body["remaining"] == -30


def test_single_category_status_404_and_bad_month(client):
    assert client.get("/api/budget-status/none",
                      params={"month": "2026-09"}).status_code == 404
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    assert client.get("/api/budget-status/groceries",
                      params={"month": "2026-13"}).status_code == 422
