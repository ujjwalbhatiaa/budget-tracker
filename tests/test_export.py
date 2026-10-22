"""Tests for the budget tracker CSV export. Run with: pytest."""

import csv
import io
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-export.db"

os.environ["BUDGET_DB"] = TEST_DB

from app import database  # noqa: E402
from app.export import router, transactions_csv  # noqa: E402

app = FastAPI()
app.include_router(router)


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _add(date="2026-09-05", description="Costco", amount=-84.2,
         category="groceries"):
    db = database.get_db(TEST_DB)
    db.execute(
        "INSERT INTO transactions (date, description, amount, category)"
        " VALUES (?, ?, ?, ?)",
        (date, description, amount, category),
    )
    db.commit()


def _parse_csv(text):
    return list(csv.reader(io.StringIO(text)))


def test_export_returns_csv_download(client):
    _add(date="2026-09-01", description="Rent", amount=-900, category="housing")
    _add(date="2026-09-10", description="Paycheque", amount=2000, category="income")
    r = client.get("/api/transactions/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "transactions.csv" in r.headers["content-disposition"]
    rows = _parse_csv(r.text)
    assert rows[0] == ["id", "date", "description", "amount", "category"]
    # newest first, same ordering as the list endpoint
    assert [row[1] for row in rows[1:]] == ["2026-09-10", "2026-09-01"]
    assert rows[1][2] == "Paycheque"
    assert rows[1][3] == "2000.0"
    assert rows[2][3] == "-900.0"


def test_export_empty_db_is_header_only(client):
    r = client.get("/api/transactions/export")
    assert r.status_code == 200
    assert _parse_csv(r.text) == [["id", "date", "description", "amount",
                                   "category"]]


def test_export_limit(client):
    _add(date="2026-09-01")
    _add(date="2026-09-02")
    _add(date="2026-09-03")
    rows = _parse_csv(client.get("/api/transactions/export?limit=2").text)
    assert len(rows) == 3  # header + 2 newest
    assert [row[1] for row in rows[1:]] == ["2026-09-03", "2026-09-02"]


def test_export_quotes_commas_and_quotes(client):
    _add(description='Dinner at "Joe\'s", downtown', amount=-45.5)
    rows = _parse_csv(client.get("/api/transactions/export").text)
    assert rows[1][2] == 'Dinner at "Joe\'s", downtown'


def test_transactions_csv_helper_sorts_newest_first(client):
    _add(date="2026-08-15", description="old")
    _add(date="2026-09-20", description="new")
    rows = _parse_csv(transactions_csv())
    assert [row[2] for row in rows[1:]] == ["new", "old"]
