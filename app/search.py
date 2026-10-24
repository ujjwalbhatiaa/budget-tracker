"""Transaction search for the budget tracker.

GET /api/transactions/search -> filtered transactions (newest first).
All filters are optional and combine with AND:
  ?q=        substring match on description, case-insensitive
  ?category= exact category match (case-insensitive, stored lowercase)
  ?from=     earliest date, YYYY-MM-DD (inclusive)
  ?to=       latest date, YYYY-MM-DD (inclusive)
  ?limit=    max rows (default 100)

Register on the main app with: app.include_router(search.router)
"""

from __future__ import annotations

import os
from datetime import date as date_type

from fastapi import APIRouter, Query

from .database import get_db
from .schemas import TransactionOut

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("BUDGET_DB", os.path.join(BASE_DIR, "budget.db"))


@router.get("/api/transactions/search", response_model=list[TransactionOut])
def search_transactions(
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=50),
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    limit: int = 100,
):
    conditions = []
    params: list = []
    if q:
        conditions.append("LOWER(description) LIKE ?")
        params.append(f"%{q.lower()}%")
    if category:
        conditions.append("category = ?")
        params.append(category.strip().lower())
    if from_date:
        conditions.append("date >= ?")
        params.append(from_date.isoformat())
    if to_date:
        conditions.append("date <= ?")
        params.append(to_date.isoformat())
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    db = get_db(DB_PATH)
    rows = db.execute(
        f"SELECT * FROM transactions {where}"
        " ORDER BY date DESC, id DESC LIMIT ?",
        (*params, max(limit, 1)),
    ).fetchall()
    return [TransactionOut(
        id=row["id"], date=row["date"], description=row["description"],
        amount=row["amount"], category=row["category"],
    ) for row in rows]
