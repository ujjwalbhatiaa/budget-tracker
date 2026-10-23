"""Tests for the budget tracker CSV import. Run with: pytest."""

import io
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_DB = "/tmp/budget-tracker/test-import.db"

os.makedirs(os.path.dirname(TEST_DB), exist_ok=True)
os.environ["BUDGET_DB"] = TEST_DB

from app import database  # noqa: E402
from app.importer import router  # noqa: E402
from app.export import transactions_csv  # noqa: E402

app = FastAPI()
app.include_router(router)


@pytest.fixture()
def client():
    database.reset_db(TEST_DB)
    with TestClient(app) as c:
        yield c


def _upload(client, text, filename="transactions.csv"):
    return client.post(
        "/api/transactions/import",
        files={"file": (filename, text, "text/csv")},
    )


def _all_rows():
    db = database.get_db(TEST_DB)
    return db.execute(
        "SELECT date, description, amount, category FROM transactions"
        " ORDER BY id"
    ).fetchall()


def test_import_export_format_with_id_column(client):
    csv_text = (
        "id,date,description,amount,category\n"
        "1,2026-10-01,Rent,-1200,housing\n"
        "2,2026-10-05,Paycheque,2500,Income\n"
    )
    r = _upload(client, csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["errors"] == []
    rows = _all_rows()
    assert len(rows) == 2
    # ids are never reused; category is normalized to lowercase
    assert rows[0]["description"] == "Rent"
    assert rows[1]["category"] == "income"


def test_import_without_id_column_and_blank_lines(client):
    csv_text = (
        "date,description,amount,category\n"
        "2026-10-02,Coffee,-4.5,Food\n"
        "\n"
        "2026-10-03,Bus pass,-100,transport\n"
    )
    r = _upload(client, csv_text)
    assert r.status_code == 200
    assert r.json()["imported"] == 2
    assert len(_all_rows()) == 2


def test_import_reports_bad_rows_without_aborting(client):
    csv_text = (
        "date,description,amount,category\n"
        "2026-10-01,Good row,-10,food\n"
        "not-a-date,Bad date,-5,food\n"
        "2026-10-02,Zero amount,0,food\n"
        "2026-10-03,, -7,food\n"
        "2026-10-04,Another good,25,income\n"
    )
    r = _upload(client, csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 2
    assert body["skipped"] == 3
    assert [e["row"] for e in body["errors"]] == [3, 4, 5]
    assert len(_all_rows()) == 2


def test_import_missing_columns_rejected(client):
    r = _upload(client, "date,description\n2026-10-01,X\n")
    assert r.status_code == 400
    assert "amount" in r.json()["detail"]


def test_import_header_only_imports_nothing(client):
    r = _upload(client, "date,description,amount,category\n")
    assert r.status_code == 200
    assert r.json() == {"imported": 0, "skipped": 0, "errors": []}


def test_import_non_utf8_rejected(client):
    r = client.post(
        "/api/transactions/import",
        files={"file": ("t.csv", b"\xff\xfe\x00bad", "text/csv")},
    )
    assert r.status_code == 400


def test_round_trip_export_then_import(client):
    original = (
        "id,date,description,amount,category\n"
        "7,2026-09-01,Rent,-1200,housing\n"
        "8,2026-09-10,Paycheque,2000,income\n"
    )
    assert _upload(client, original).json()["imported"] == 2
    exported = transactions_csv()
    database.reset_db(TEST_DB)
    r = _upload(client, exported)
    assert r.status_code == 200
    assert r.json()["imported"] == 2
    rows = _all_rows()
    # export is newest-first; the re-import preserves the file's row order
    assert [r_["description"] for r_ in rows] == ["Paycheque", "Rent"]
