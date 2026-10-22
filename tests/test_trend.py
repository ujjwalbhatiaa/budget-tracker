"""Tests for the per-category spending trend endpoint. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-trend.db"
os.environ["BUDGET_DB"] = TEST_DB

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _add(c, date, description, amount, category):
    r = c.post("/api/transactions", json={
        "date": date, "description": description,
        "amount": amount, "category": category})
    assert r.status_code == 201, r.text


def test_trend_basic_two_months(client):
    _add(client, "2026-09-03", "Costco", -200.0, "groceries")
    _add(client, "2026-10-04", "Safeway", -100.0, "groceries")
    r = client.get("/api/summary/trend",
                   params={"category": "groceries", "months": 2})
    assert r.status_code == 200
    rows = r.json()
    assert [t["month"] for t in rows] == ["2026-09", "2026-10"]
    assert [t["spending"] for t in rows] == [200.0, 100.0]
    assert rows[0]["vs_prev_pct"] is None  # first month in window
    assert rows[1]["vs_prev_pct"] == -50.0  # halved spending


def test_trend_includes_empty_months(client):
    _add(client, "2026-10-04", "Safeway", -100.0, "groceries")
    rows = client.get("/api/summary/trend",
                      params={"category": "groceries", "months": 2}).json()
    assert [t["month"] for t in rows] == ["2026-09", "2026-10"]
    assert rows[0]["spending"] == 0.0
    assert rows[0]["vs_prev_pct"] is None
    # prev month had no spending: no meaningful % change
    assert rows[1]["vs_prev_pct"] is None


def test_trend_ignores_income_and_other_categories(client):
    _add(client, "2026-10-04", "Paycheck", 1500.0, "income")
    _add(client, "2026-10-05", "Shell", -60.0, "gas")
    _add(client, "2026-10-06", "Safeway", -100.0, "groceries")
    rows = client.get("/api/summary/trend",
                      params={"category": "groceries", "months": 1}).json()
    assert rows == [{"month": "2026-10", "spending": 100.0,
                     "vs_prev_pct": None}]


def test_trend_category_normalized(client):
    _add(client, "2026-10-04", "Safeway", -100.0, "groceries")
    rows = client.get("/api/summary/trend",
                      params={"category": "  GROCERIES ", "months": 1}).json()
    assert rows[0]["spending"] == 100.0  # strip + lowercase, like the API


def test_trend_requires_category(client):
    r = client.get("/api/summary/trend", params={"months": 2})
    assert r.status_code == 422


def test_trend_months_bounds(client):
    assert client.get("/api/summary/trend",
                      params={"category": "x", "months": 0}).status_code == 422
    assert client.get("/api/summary/trend",
                      params={"category": "x", "months": 25}).status_code == 422
    assert client.get("/api/summary/trend",
                      params={"category": "x", "months": 1}).status_code == 200


def test_trend_zero_to_zero_stays_flat(client):
    rows = client.get("/api/summary/trend",
                      params={"category": "nothing", "months": 2}).json()
    assert all(t["spending"] == 0.0 for t in rows)
    assert rows[0]["vs_prev_pct"] is None
    assert rows[1]["vs_prev_pct"] == 0.0
