"""API tests for GET /api/transactions/{id}. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-get-txn.db"
os.environ["BUDGET_DB"] = TEST_DB

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _add(c, date="2026-09-05", description="Costco", amount=-84.2,
         category="groceries"):
    r = c.post("/api/transactions", json={
        "date": date, "description": description,
        "amount": amount, "category": category})
    assert r.status_code == 201, r.text
    return r.json()


def test_get_single_transaction(client):
    t = _add(client)
    r = client.get(f"/api/transactions/{t['id']}")
    assert r.status_code == 200
    got = r.json()
    assert got["id"] == t["id"]
    assert got["description"] == "Costco"
    assert got["amount"] == -84.2
    assert got["category"] == "groceries"


def test_get_missing_is_404(client):
    r = client.get("/api/transactions/999999")
    assert r.status_code == 404


def test_get_does_not_shadow_search(client):
    _add(client, description="Costco run")
    _add(client, description="Shell gas", category="transport")
    r = client.get("/api/transactions/search",
                   params={"q": "costco"})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["description"] == "Costco run"
