"""API tests for the budget tracker. Run with: pytest."""

import os

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test.db"
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


def test_create_and_list(client):
    t = _add(client)
    assert t["id"] > 0
    assert t["description"] == "Costco"
    txns = client.get("/api/transactions").json()
    assert len(txns) == 1
    assert txns[0]["amount"] == -84.2


def test_list_newest_first(client):
    _add(client, date="2026-09-01")
    _add(client, date="2026-09-10")
    txns = client.get("/api/transactions").json()
    assert [t["date"] for t in txns] == ["2026-09-10", "2026-09-01"]


def test_rejects_zero_amount(client):
    r = client.post("/api/transactions", json={
        "date": "2026-09-05", "description": "x", "amount": 0})
    assert r.status_code == 422


def test_rejects_bad_date(client):
    r = client.post("/api/transactions", json={
        "date": "not-a-date", "description": "x", "amount": -5})
    assert r.status_code == 422


def test_rejects_empty_description(client):
    r = client.post("/api/transactions", json={
        "date": "2026-09-05", "description": "  ", "amount": -5})
    assert r.status_code == 422


def test_delete(client):
    t = _add(client)
    r = client.delete(f"/api/transactions/{t['id']}")
    assert r.status_code == 204
    assert client.get("/api/transactions").json() == []


def test_delete_missing_is_404(client):
    assert client.delete("/api/transactions/9999").status_code == 404


def test_monthly_summary(client):
    _add(client, date="2026-09-05", amount=-100, category="groceries")
    _add(client, date="2026-09-06", amount=-50, category="dining")
    _add(client, date="2026-09-01", amount=2000, category="income")
    _add(client, date="2026-08-15", amount=-900, category="housing")
    summary = client.get("/api/summary").json()
    assert [m["month"] for m in summary] == ["2026-09", "2026-08"]
    sept = summary[0]
    assert sept["spending"] == 150.0
    assert sept["income"] == 2000.0
    assert sept["net"] == 1850.0
    cats = {c["category"]: c for c in sept["by_category"]}
    assert cats["groceries"]["total"] == 100.0
    assert abs(sum(c["share"] for c in sept["by_category"]) - 100.0) < 0.2


def test_category_breakdown(client):
    _add(client, amount=-100, category="groceries")
    _add(client, amount=-300, category="dining")
    _add(client, amount=2000, category="income")  # income excluded
    bd = client.get("/api/categories").json()
    assert [c["category"] for c in bd] == ["dining", "groceries"]
    assert bd[0]["total"] == 300.0


def test_summary_empty(client):
    assert client.get("/api/summary").json() == []
    assert client.get("/api/categories").json() == []


def test_category_normalized_lowercase(client):
    t = _add(client, category="Groceries")
    assert t["category"] == "groceries"


def test_update_full(client):
    t = _add(client, description="Costco", amount=-84.2, category="groceries")
    r = client.put(f"/api/transactions/{t['id']}", json={
        "date": "2026-09-06", "description": "Safeway", "amount": -51.0,
        "category": "groceries"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["id"] == t["id"]
    assert updated["date"] == "2026-09-06"
    assert updated["description"] == "Safeway"
    assert updated["amount"] == -51.0


def test_update_partial_keeps_other_fields(client):
    t = _add(client, description="Costco", amount=-84.2, category="groceries")
    r = client.put(f"/api/transactions/{t['id']}",
                   json={"description": "Costco Wholesale"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["description"] == "Costco Wholesale"
    assert updated["amount"] == -84.2  # untouched
    assert updated["category"] == "groceries"  # untouched


def test_update_normalizes_category_lowercase(client):
    t = _add(client)
    r = client.put(f"/api/transactions/{t['id']}", json={"category": "DINING"})
    assert r.status_code == 200
    assert r.json()["category"] == "dining"


def test_update_missing_is_404(client):
    assert client.put("/api/transactions/9999",
                      json={"description": "x"}).status_code == 404


def test_update_rejects_zero_amount(client):
    t = _add(client)
    r = client.put(f"/api/transactions/{t['id']}", json={"amount": 0})
    assert r.status_code == 422


def test_update_rejects_blank_description(client):
    t = _add(client)
    r = client.put(f"/api/transactions/{t['id']}",
                   json={"description": "   "})
    assert r.status_code == 422


def test_update_empty_patch_is_noop(client):
    t = _add(client, description="Costco", amount=-84.2)
    r = client.put(f"/api/transactions/{t['id']}", json={})
    assert r.status_code == 200
    assert r.json()["description"] == "Costco"
    assert r.json()["amount"] == -84.2
