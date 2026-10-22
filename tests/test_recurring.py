"""Tests for the recurring-transaction detection endpoint (/api/recurring).

Also covers the drive-by fix: the `budgets` table must exist on a fresh
database (GET/PUT /api/budgets previously raised
"no such table: budgets" on fresh DBs).
"""

import os

import pytest
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-recurring.db"
os.environ["BUDGET_DB"] = TEST_DB
os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)

from app import database  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _add(c, txn_date, description, amount, category="subscriptions"):
    r = c.post("/api/transactions", json={
        "date": txn_date, "description": description,
        "amount": amount, "category": category})
    assert r.status_code == 201, r.text


def _get(c, **params):
    r = c.get("/api/recurring", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_detects_monthly_subscription(client):
    for d in ("2026-01-15", "2026-02-14", "2026-03-16", "2026-04-15"):
        _add(client, d, "Netflix", -15.99)
    body = _get(client)
    assert len(body) == 1
    r = body[0]
    assert r["description"] == "Netflix"
    assert r["amount"] == -15.99
    assert r["category"] == "subscriptions"
    assert r["occurrences"] == 4
    assert r["first_date"] == "2026-01-15"
    assert r["last_date"] == "2026-04-15"
    assert r["cadence_days"] == 30
    assert r["next_expected"] == "2026-05-15"


def test_groups_case_insensitively_and_prefers_common_casing(client):
    _add(client, "2026-01-10", "Netflix", -15.99)
    _add(client, "2026-02-09", "NETFLIX", -15.99)
    _add(client, "2026-03-11", "Netflix", -15.99)
    body = _get(client)
    assert len(body) == 1
    assert body[0]["occurrences"] == 3
    assert body[0]["description"] == "Netflix"


def test_differing_amounts_are_not_grouped(client):
    _add(client, "2026-01-10", "Uber", -12.50, "transport")
    _add(client, "2026-02-09", "Uber", -31.75, "transport")
    _add(client, "2026-03-11", "Uber", -8.20, "transport")
    assert _get(client) == []


def test_min_occurrences_default_ignores_pairs(client):
    _add(client, "2026-01-10", "Spotify", -10.99)
    _add(client, "2026-02-09", "Spotify", -10.99)
    assert _get(client) == []
    body = _get(client, min_occurrences=2)
    assert len(body) == 1
    assert body[0]["occurrences"] == 2


def test_min_occurrences_validated(client):
    r = client.get("/api/recurring", params={"min_occurrences": 1})
    assert r.status_code == 422


def test_weekly_cadence_is_not_monthly_recurring(client):
    for d in ("2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"):
        _add(client, d, "Gym day pass", -5.00, "health")
    assert _get(client) == []


def test_recurring_income_detected_too(client):
    for d in ("2026-01-31", "2026-03-02", "2026-04-01"):
        _add(client, d, "TA payroll", 950.00, "income")
    body = _get(client)
    assert len(body) == 1
    assert body[0]["amount"] == 950.00
    assert body[0]["category"] == "income"
    assert body[0]["occurrences"] == 3


def test_sorted_by_occurrences_desc(client):
    for d in ("2026-01-10", "2026-02-09", "2026-03-11"):
        _add(client, d, "Netflix", -15.99)
    for d in ("2026-01-05", "2026-02-04", "2026-03-06", "2026-04-05",
              "2026-05-05"):
        _add(client, d, "Rent", -900.00, "housing")
    body = _get(client)
    assert [r["description"] for r in body] == ["Rent", "Netflix"]


def test_budgets_table_exists_on_fresh_db(client):
    # Drive-by fix: these endpoints used to 500 with
    # "no such table: budgets" on a fresh database.
    r = client.get("/api/budgets")
    assert r.status_code == 200, r.text
    assert r.json() == []
    r = client.put("/api/budgets/groceries", json={"monthly_limit": 500})
    assert r.status_code == 200, r.text
    assert r.json() == {"category": "groceries", "monthly_limit": 500.0}
    r = client.get("/api/budgets")
    assert r.status_code == 200
    assert len(r.json()) == 1
