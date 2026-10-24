"""Tests for the budget tracker transaction search. Run with: pytest."""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-search.db"

os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
os.environ["BUDGET_DB"] = TEST_DB

from app import database  # noqa: E402
from app.search import router  # noqa: E402

app = FastAPI()
app.include_router(router)


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    db = database.get_db(TEST_DB)
    seed = [
        ("2026-10-01", "Rent payment", -1200.0, "housing"),
        ("2026-10-03", "Grocery run", -85.5, "groceries"),
        ("2026-10-05", "Paycheque", 2500.0, "income"),
        ("2026-10-20", "GROCERY delivery", -40.0, "groceries"),
        ("2026-11-02", "Gym membership", -45.0, "health"),
    ]
    for date, desc, amount, cat in seed:
        db.execute(
            "INSERT INTO transactions (date, description, amount, category)"
            " VALUES (?, ?, ?, ?)", (date, desc, amount, cat),
        )
    db.commit()
    with TestClient(app) as c:
        yield c


def test_no_filters_returns_all_newest_first(client):
    r = client.get("/api/transactions/search")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 5
    assert rows[0]["description"] == "Gym membership"
    assert rows[-1]["description"] == "Rent payment"


def test_q_matches_description_case_insensitively(client):
    rows = client.get("/api/transactions/search", params={"q": "grocery"}).json()
    assert [row["description"] for row in rows] == [
        "GROCERY delivery", "Grocery run"]


def test_category_filter(client):
    rows = client.get("/api/transactions/search",
                      params={"category": "Groceries"}).json()
    assert len(rows) == 2
    assert all(row["category"] == "groceries" for row in rows)


def test_date_range_inclusive(client):
    rows = client.get("/api/transactions/search",
                      params={"from": "2026-10-03", "to": "2026-10-20"}).json()
    assert [row["description"] for row in rows] == [
        "GROCERY delivery", "Paycheque", "Grocery run"]


def test_filters_combine_with_and(client):
    rows = client.get("/api/transactions/search",
                      params={"q": "grocery", "from": "2026-10-10"}).json()
    assert [row["description"] for row in rows] == ["GROCERY delivery"]


def test_no_match_returns_empty(client):
    assert client.get("/api/transactions/search",
                      params={"q": "airplane"}).json() == []


def test_limit_applies(client):
    rows = client.get("/api/transactions/search",
                      params={"limit": 2}).json()
    assert len(rows) == 2
    assert rows[0]["description"] == "Gym membership"


def test_invalid_date_rejected(client):
    r = client.get("/api/transactions/search", params={"from": "not-a-date"})
    assert r.status_code == 422
