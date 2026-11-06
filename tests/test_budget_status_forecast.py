"""Tests for GET /api/budget-status/forecast. Run with: pytest."""

import calendar
import os
from datetime import date

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


def test_forecast_past_month_projection_equals_spent(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    client.put("/api/budgets/dining", json={"monthly_limit": 50})
    client.put("/api/budgets/transport", json={"monthly_limit": 100})
    _txn(client, -450, "groceries", "2026-09-05")  # over its cap
    _txn(client, -20, "dining", "2026-09-10")
    _txn(client, -999, "housing", "2026-09-12")  # no cap -> excluded
    _txn(client, 200, "groceries", "2026-09-15")  # income: excluded
    r = client.get("/api/budget-status/forecast",
                   params={"month": "2026-09"})
    assert r.status_code == 200, r.text
    body = {b["category"]: b for b in r.json()}
    assert sorted(body) == ["dining", "groceries", "transport"]
    # September is over: projection equals what was actually spent.
    g = body["groceries"]
    assert g["spent"] == 450
    assert g["days_elapsed"] == 30 and g["days_in_month"] == 30
    assert g["projected_spent"] == 450
    assert g["projected_pct_used"] == 112.5
    assert g["projected_over"] is True
    d = body["dining"]
    assert d["projected_spent"] == 20
    assert d["projected_pct_used"] == 40.0
    assert d["projected_over"] is False
    # Capped but unspent: zero projection, not over.
    assert body["transport"]["projected_spent"] == 0
    assert body["transport"]["projected_over"] is False


def test_forecast_future_month_zero(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    r = client.get("/api/budget-status/forecast",
                   params={"month": "2099-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["days_elapsed"] == 0
    assert body[0]["days_in_month"] == 31
    assert body[0]["spent"] == 0
    assert body[0]["projected_spent"] == 0
    assert body[0]["projected_pct_used"] == 0.0
    assert body[0]["projected_over"] is False


def test_forecast_current_month_run_rate(client):
    today = date.today()
    month = today.strftime("%Y-%m")
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    client.put("/api/budgets/groceries", json={"monthly_limit": 300})
    _txn(client, -60, "groceries", today.isoformat())
    r = client.get("/api/budget-status/forecast", params={"month": month})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    row = body[0]
    assert row["spent"] == 60
    assert row["days_elapsed"] == today.day
    assert row["days_in_month"] == days_in_month
    assert row["projected_spent"] == round(60 / today.day * days_in_month, 2)
    assert row["projected_pct_used"] == round(
        row["projected_spent"] / 300 * 100, 1)
    assert row["projected_over"] is (row["projected_spent"] > 300)


def test_forecast_bad_month(client):
    assert client.get("/api/budget-status/forecast",
                      params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/budget-status/forecast",
                      params={"month": "2026-9"}).status_code == 422
    # "forecast" must not be swallowed by the /{category} route.
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    r = client.get("/api/budget-status/forecast",
                   params={"month": "2026-09"})
    assert r.status_code == 200, r.text
    assert r.json()[0]["category"] == "groceries"
