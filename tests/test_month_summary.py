"""Tests for GET /api/summary/month/{month}. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-month-summary.db"
os.environ["BUDGET_DB"] = TEST_DB

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _add(c, txn_date, description, amount, category="groceries"):
    r = c.post("/api/transactions", json={
        "date": txn_date, "description": description,
        "amount": amount, "category": category})
    assert r.status_code == 201, r.text


def test_month_totals_and_category_shares(client):
    _add(client, "2026-04-02", "Costco", -300.0, "groceries")
    _add(client, "2026-04-05", "Shell", -100.0, "transport")
    _add(client, "2026-04-09", "Paycheque", 2000.0, "income")
    r = client.get("/api/summary/month/2026-04")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == "2026-04"
    assert body["spending"] == 400.0
    assert body["income"] == 2000.0
    assert body["net"] == 1600.0
    cats = body["by_category"]
    assert [c["category"] for c in cats] == ["groceries", "transport"]
    assert cats[0]["total"] == 300.0
    assert cats[0]["share"] == 75.0
    assert cats[1]["total"] == 100.0
    assert cats[1]["share"] == 25.0


def test_month_scoped_not_all_time(client):
    _add(client, "2026-03-01", "Costco", -500.0, "groceries")
    _add(client, "2026-04-01", "Shell", -50.0, "transport")
    body = client.get("/api/summary/month/2026-04").json()
    assert body["spending"] == 50.0
    assert [c["category"] for c in body["by_category"]] == ["transport"]


def test_empty_month_is_zero_filled(client):
    body = client.get("/api/summary/month/2026-07").json()
    assert body == {"month": "2026-07", "spending": 0, "income": 0,
                    "net": 0, "by_category": []}


def test_invalid_month_rejected(client):
    for bad in ("2026-13", "2026-00", "2026-4", "april", "2026-04-01"):
        r = client.get(f"/api/summary/month/{bad}")
        assert r.status_code == 422, bad
