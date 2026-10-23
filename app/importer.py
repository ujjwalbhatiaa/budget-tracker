"""CSV import for the budget tracker.

POST /api/transactions/import -> accepts a multipart file upload of a CSV
with columns date, description, amount, category (the export format, with or
without the id column — ids are never reused). Each row is validated with
TransactionIn; valid rows are inserted, invalid rows are reported per-row so
a single bad line never kills the whole import.

Response: {"imported": n, "skipped": m,
            "errors": [{"row": <csv line number>, "error": <message>}]}

Register on the main app with: app.include_router(importer.router)
"""

from __future__ import annotations

import csv
import io
import os

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import ValidationError

from .database import get_db
from .schemas import ImportResult, ImportRowError, TransactionIn

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("BUDGET_DB", os.path.join(BASE_DIR, "budget.db"))

REQUIRED_COLUMNS = ("date", "description", "amount", "category")


def _normalize_header(name: str | None) -> str:
    return (name or "").strip().lower()


@router.post("/api/transactions/import", response_model=ImportResult)
async def import_transactions_csv(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # utf-8-sig also strips an Excel BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=400,
                            detail="file is not valid UTF-8 text")
    try:
        reader = csv.DictReader(io.StringIO(text))
    except csv.Error as exc:
        raise HTTPException(status_code=400,
                            detail=f"could not parse CSV: {exc}")
    headers = {_normalize_header(h) for h in (reader.fieldnames or [])}
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"csv is missing required columns: {', '.join(missing)} "
                   f"(need: {', '.join(REQUIRED_COLUMNS)})",
        )

    db = get_db(DB_PATH)
    imported = 0
    errors: list[ImportRowError] = []
    for lineno, row in enumerate(reader, start=2):  # line 1 = header
        values = {k: (v or "").strip()
                  for k, v in row.items() if k is not None}
        if not any(values.get(c) for c in REQUIRED_COLUMNS):
            continue  # fully blank line: skip silently, not an error
        payload = {c: values.get(c, "") for c in REQUIRED_COLUMNS}
        try:
            txn = TransactionIn(**payload)
        except ValidationError as exc:
            first = exc.errors()[0]
            errors.append(ImportRowError(
                row=lineno,
                error=f"{first['loc'][0]}: {first['msg']}",
            ))
            continue
        db.execute(
            "INSERT INTO transactions (date, description, amount, category)"
            " VALUES (?, ?, ?, ?)",
            (txn.date.isoformat(), txn.description.strip(), txn.amount,
             txn.category.strip().lower() or "other"),
        )
        imported += 1
    db.commit()
    return ImportResult(imported=imported, skipped=len(errors),
                        errors=errors)
