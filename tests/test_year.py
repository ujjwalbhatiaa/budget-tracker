"""Tests for the annual summary endpoint. Run with: pytest."""

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-year.db"
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


def test_year_empty_returns_twelve_zero_rows(client):
    r = client.get("/api/summary/year", params={"year": 2026})
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == 2026
    assert [m["month"] for m in body["months"]] == [
        f"2026-{m:02d}" for m in range(1, 13)]
    assert all(m["spending"] == 0 and m["income"] == 0 and m["net"] == 0
               for m in body["months"])
    assert body["total_spending"] == 0
    assert body["total_income"] == 0
    assert body["net"] == 0
    assert body["avg_monthly_spending"] == 0


def test_year_monthly_breakdown(client):
    _add(client, "2026-01-05", "Costco", -200.0)
    _add(client, "2026-01-20", "Safeway", -100.0)
    _add(client, "2026-03-02", "Paycheque", 1500.0, "income")
    body = client.get("/api/summary/year", params={"year": 2026}).json()
    jan = body["months"][0]
    assert jan["month"] == "2026-01"
    assert jan["spending"] == 300.0
    assert jan["income"] == 0.0
    assert jan["net"] == -300.0
    mar = body["months"][2]
    assert mar["spending"] == 0.0
    assert mar["income"] == 1500.0
    assert mar["net"] == 1500.0
    feb = body["months"][1]  # zero-filled, not skipped
    assert feb["spending"] == 0.0 and feb["income"] == 0.0


def test_year_totals_and_average(client):
    _add(client, "2026-02-01", "Rent", -1200.0, "housing")
    _add(client, "2026-05-01", "Rent", -1200.0, "housing")
    _add(client, "2026-05-15", "Paycheque", 3000.0, "income")
    body = client.get("/api/summary/year", params={"year": 2026}).json()
    assert body["total_spending"] == 2400.0
    assert body["total_income"] == 3000.0
    assert body["net"] == 600.0
    assert body["avg_monthly_spending"] == 200.0  # 2400 / 12


def test_year_excludes_other_years(client):
    _add(client, "2025-12-25", "Gifts", -500.0)
    _add(client, "2026-01-02", "Groceries", -80.0)
    body = client.get("/api/summary/year", params={"year": 2026}).json()
    assert body["total_spending"] == 80.0
    body25 = client.get("/api/summary/year", params={"year": 2025}).json()
    assert body25["total_spending"] == 500.0
    assert [m["month"] for m in body25["months"]][0] == "2025-01"


def test_year_default_is_current_year(client):
    _add(client, date.today().isoformat(), "Coffee", -5.5)
    body = client.get("/api/summary/year").json()
    assert body["year"] == date.today().year
    assert body["total_spending"] == 5.5


def test_year_out_of_range_rejected(client):
    assert client.get("/api/summary/year", params={"year": 1999}).status_code == 422
    assert client.get("/api/summary/year", params={"year": 2101}).status_code == 422


def test_year_net_negative_when_spending_wins(client):
    _add(client, "2026-07-04", "Laptop", -1800.0, "electronics")
    _add(client, "2026-07-10", "Paycheque", 900.0, "income")
    body = client.get("/api/summary/year", params={"year": 2026}).json()
    assert body["net"] == -900.0
    july = body["months"][6]
    assert july["net"] == -900.0
