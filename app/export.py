"""CSV export for the budget tracker.

GET /api/transactions/export -> downloads every transaction as a CSV file
(newest first, same ordering as the list endpoint). Accepts ?limit= like
the list endpoint (default 1000).

Register on the main app with: app.include_router(export.router)
"""

from __future__ import annotations

import csv
import io
import os

from fastapi import APIRouter
from fastapi.responses import Response

from .database import get_db

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("BUDGET_DB", os.path.join(BASE_DIR, "budget.db"))

CSV_COLUMNS = ["id", "date", "description", "amount", "category"]


def transactions_csv(limit: int = 1000) -> str:
    """Render all transactions as a CSV string (newest first)."""
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT id, date, description, amount, category FROM transactions"
        " ORDER BY date DESC, id DESC LIMIT ?",
        (max(limit, 1),),
    ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow([r["id"], r["date"], r["description"],
                         r["amount"], r["category"]])
    return buf.getvalue()


@router.get("/api/transactions/export")
def export_transactions_csv(limit: int = 1000):
    return Response(
        content=transactions_csv(limit),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )
