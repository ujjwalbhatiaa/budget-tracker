"""Tests for GET /api/budget-status/compare. Run with: pytest."""

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


def test_compare_explicit_months_and_delta(client):
    _cap(client, "groceries", 100)
    _cap(client, "dining", 100)
    _cap(client, "transit", 100)
    _txn(client, -80, "groceries", "2026-09-05")
    _txn(client, -40, "groceries", "2026-08-05")
    _txn(client, -50, "dining", "2026-09-05")
    _txn(client, -60, "dining", "2026-08-05")
    r = client.get("/api/budget-status/compare?month=2026-09&prev_month=2026-08")
    assert r.status_code == 200, r.text
    rows = {row["category"]: row for row in r.json()}
    assert rows["groceries"]["spent"] == 80.0
    assert rows["groceries"]["prev_spent"] == 40.0
    assert rows["groceries"]["delta_spent"] == 40.0
    assert rows["groceries"]["pct_used"] == 80.0
    assert rows["groceries"]["prev_pct_used"] == 40.0
    assert rows["dining"]["delta_spent"] == -10.0
    # Capped but unspent in both months still appears, with zeros.
    assert rows["transit"]["spent"] == 0.0
    assert rows["transit"]["prev_spent"] == 0.0
    assert rows["transit"]["delta_spent"] == 0.0


def test_compare_default_prev_month_and_bad_month(client):
    _cap(client, "groceries", 100)
    _txn(client, -80, "groceries", "2026-09-05")
    _txn(client, -40, "groceries", "2026-08-05")
    r = client.get("/api/budget-status/compare?month=2026-09")
    assert r.status_code == 200, r.text
    row = r.json()[0]
    assert row["prev_month"] == "2026-08"
    assert row["delta_spent"] == 40.0
    assert client.get("/api/budget-status/compare?month=2026-13").status_code == 422
    assert client.get(
        "/api/budget-status/compare?month=2026-09&prev_month=2026-13"
    ).status_code == 422
