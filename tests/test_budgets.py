"""Tests for monthly budget caps. Run with: pytest."""

import os
from datetime import date

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


def test_set_and_list_budget(client):
    r = client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    assert r.status_code == 200, r.text
    assert r.json() == {"category": "groceries", "monthly_limit": 400}
    budgets = client.get("/api/budgets").json()
    assert budgets == [{"category": "groceries", "monthly_limit": 400}]


def test_update_existing_cap(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    r = client.put("/api/budgets/groceries", json={"monthly_limit": 550})
    assert r.status_code == 200
    assert r.json()["monthly_limit"] == 550
    assert len(client.get("/api/budgets").json()) == 1  # no duplicate row


def test_rejects_non_positive_limit(client):
    assert client.put("/api/budgets/groceries",
                      json={"monthly_limit": 0}).status_code == 422
    assert client.put("/api/budgets/groceries",
                      json={"monthly_limit": -10}).status_code == 422


def test_category_normalized(client):
    r = client.put("/api/budgets/  Groceries ", json={"monthly_limit": 300})
    assert r.status_code == 200
    assert r.json()["category"] == "groceries"


def test_delete_budget(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    assert client.delete("/api/budgets/groceries").status_code == 204
    assert client.get("/api/budgets").json() == []
    assert client.delete("/api/budgets/groceries").status_code == 404


def test_budget_status_math(client):
    _txn(client, -100, "groceries")
    _txn(client, -50, "groceries")
    _txn(client, -60, "dining")
    _txn(client, 2000, "income")          # income never counts as spending
    _txn(client, -900, "groceries", txn_date="2026-08-15")  # other month
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    client.put("/api/budgets/dining", json={"monthly_limit": 50})
    status = {b["category"]: b
              for b in client.get("/api/budget-status",
                                 params={"month": "2026-09"}).json()}
    g = status["groceries"]
    assert g["spent"] == 150 and g["remaining"] == 250
    assert g["pct_used"] == 37.5 and g["over"] is False
    assert g["month"] == "2026-09"
    d = status["dining"]
    assert d["spent"] == 60 and d["remaining"] == -10
    assert d["pct_used"] == 120.0 and d["over"] is True


def test_budget_status_defaults_to_current_month(client):
    client.put("/api/budgets/groceries", json={"monthly_limit": 400})
    rows = client.get("/api/budget-status").json()
    assert rows and rows[0]["month"] == date.today().strftime("%Y-%m")


def test_budget_status_rejects_bad_month(client):
    assert client.get("/api/budget-status",
                      params={"month": "2026-13"}).status_code == 422
    assert client.get("/api/budget-status",
                      params={"month": "september"}).status_code == 422
