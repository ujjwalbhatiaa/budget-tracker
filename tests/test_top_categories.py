"""Tests for the top-categories summary endpoint. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-top-categories.db"
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


def _get(c, **params):
    r = c.get("/api/summary/top-categories", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_ranked_descending_with_share(client):
    _add(client, "2026-04-02", "Costco", -300.0, "groceries")
    _add(client, "2026-04-05", "Shell", -100.0, "transport")
    _add(client, "2026-04-09", "Safeway", -200.0, "groceries")
    body = _get(client, year=2026, month=4)
    assert body["year"] == 2026
    assert body["month"] == "2026-04"
    assert body["total_spending"] == 600.0
    cats = body["categories"]
    assert [c["category"] for c in cats] == ["groceries", "transport"]
    assert cats[0]["total"] == 500.0
    assert cats[0]["share"] == round(500.0 / 600.0, 4)
    assert cats[1]["total"] == 100.0
    assert cats[1]["share"] == round(100.0 / 600.0, 4)
    assert sum(c["share"] for c in cats) == pytest.approx(1.0)


def test_limit_is_honored(client):
    for i in range(6):
        _add(client, "2026-05-01", f"Shop {i}", -10.0 * (i + 1), f"cat{i}")
    body = _get(client, year=2026, month=5, limit=3)
    assert len(body["categories"]) == 3
    assert [c["total"] for c in body["categories"]] == [60.0, 50.0, 40.0]


def test_income_excluded(client):
    _add(client, "2026-06-01", "Paycheque", 2000.0, "income")
    _add(client, "2026-06-02", "Costco", -400.0, "groceries")
    body = _get(client, year=2026, month=6)
    assert body["total_spending"] == 400.0
    assert len(body["categories"]) == 1
    assert body["categories"][0]["category"] == "groceries"


def test_empty_month_returns_empty_list(client):
    body = _get(client, year=2026, month=7)
    assert body["month"] == "2026-07"
    assert body["total_spending"] == 0
    assert body["categories"] == []


def test_month_scoped_not_all_time(client):
    _add(client, "2026-08-01", "Costco", -500.0, "groceries")
    _add(client, "2026-09-01", "Shell", -50.0, "transport")
    body = _get(client, year=2026, month=9)
    assert body["total_spending"] == 50.0
    assert [c["category"] for c in body["categories"]] == ["transport"]


def test_year_scoped(client):
    _add(client, "2025-10-01", "Costco", -500.0, "groceries")
    _add(client, "2026-10-01", "Shell", -75.0, "transport")
    body = _get(client, year=2026, month=10)
    assert body["total_spending"] == 75.0
    assert [c["category"] for c in body["categories"]] == ["transport"]


def test_invalid_params_rejected(client):
    for params in ({"year": 1999, "month": 1}, {"year": 2026, "month": 13},
                   {"year": 2026, "month": 1, "limit": 0}):
        r = client.get("/api/summary/top-categories", params=params)
        assert r.status_code == 422, params
