"""Budget tracker API: FastAPI + SQLite.

Endpoints:
    GET    /api/transactions          list (newest first, ?limit=)
    POST   /api/transactions          create
    DELETE /api/transactions/{id}     delete
    PUT    /api/transactions/{id}     update (partial; any of date, description, amount, category)
    GET    /api/summary               per-month spending/income/net + categories
    GET    /api/categories            all-time category breakdown
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import get_db
from .schemas import (CategoryTotal, MonthSummary, TransactionIn,
                      TransactionOut, TransactionUpdate)

app = FastAPI(title="Budget Tracker")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.environ.get("BUDGET_DB", os.path.join(BASE_DIR, "budget.db"))


def _row_to_out(row) -> TransactionOut:
    return TransactionOut(
        id=row["id"],
        date=row["date"],
        description=row["description"],
        amount=row["amount"],
        category=row["category"],
    )


@app.get("/api/transactions", response_model=list[TransactionOut])
def list_transactions(limit: int = 100):
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT * FROM transactions ORDER BY date DESC, id DESC LIMIT ?",
        (max(limit, 1),),
    ).fetchall()
    return [_row_to_out(r) for r in rows]


@app.post("/api/transactions", response_model=TransactionOut, status_code=201)
def create_transaction(txn: TransactionIn):
    db = get_db(DB_PATH)
    cur = db.execute(
        "INSERT INTO transactions (date, description, amount, category)"
        " VALUES (?, ?, ?, ?)",
        (txn.date.isoformat(), txn.description.strip(), txn.amount,
         txn.category.strip().lower() or "other"),
    )
    db.commit()
    row = db.execute("SELECT * FROM transactions WHERE id = ?",
                     (cur.lastrowid,)).fetchone()
    return _row_to_out(row)


@app.delete("/api/transactions/{txn_id}", status_code=204)
def delete_transaction(txn_id: int):
    db = get_db(DB_PATH)
    cur = db.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="transaction not found")


@app.put("/api/transactions/{txn_id}", response_model=TransactionOut)
def update_transaction(txn_id: int, patch: TransactionUpdate):
    db = get_db(DB_PATH)
    row = db.execute("SELECT * FROM transactions WHERE id = ?",
                     (txn_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    updates = patch.model_dump(exclude_unset=True)
    if updates:
        current = dict(row)
        new = {**current, **{k: v for k, v in updates.items() if v is not None}}
        # Reuse the create normalization: strip + lowercase category.
        new["description"] = str(new["description"]).strip()
        new["category"] = str(new["category"]).strip().lower() or "other"
        date_val = new["date"]
        new["date"] = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
        db.execute(
            "UPDATE transactions SET date = ?, description = ?,"
            " amount = ?, category = ? WHERE id = ?",
            (new["date"], new["description"], new["amount"],
             new["category"], txn_id),
        )
        db.commit()
    row = db.execute("SELECT * FROM transactions WHERE id = ?",
                     (txn_id,)).fetchone()
    return _row_to_out(row)


@app.get("/api/summary", response_model=list[MonthSummary])
def monthly_summary():
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT substr(date, 1, 7) AS month, category,"
        "       SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS spending,"
        "       SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income"
        " FROM transactions GROUP BY month, category ORDER BY month DESC"
    ).fetchall()
    months: dict[str, dict] = {}
    for r in rows:
        m = months.setdefault(r["month"], {"spending": 0.0, "income": 0.0,
                                           "cats": {}})
        m["spending"] += r["spending"] or 0
        m["income"] += r["income"] or 0
        if r["spending"]:
            m["cats"][r["category"]] = m["cats"].get(r["category"], 0) + r["spending"]
    out = []
    for month, m in months.items():
        total = m["spending"] or 1
        cats = [CategoryTotal(category=c, total=round(v, 2),
                              share=round(v / total * 100, 1))
                for c, v in sorted(m["cats"].items(), key=lambda kv: -kv[1])]
        out.append(MonthSummary(month=month, spending=round(m["spending"], 2),
                                income=round(m["income"], 2),
                                net=round(m["income"] - m["spending"], 2),
                                by_category=cats))
    return out


@app.get("/api/categories", response_model=list[CategoryTotal])
def category_breakdown():
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT category, SUM(-amount) AS total FROM transactions"
        " WHERE amount < 0 GROUP BY category ORDER BY total DESC"
    ).fetchall()
    grand = sum(r["total"] for r in rows) or 1
    return [CategoryTotal(category=r["category"], total=round(r["total"], 2),
                          share=round(r["total"] / grand * 100, 1))
            for r in rows]


if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:  # pragma: no cover - local dev without static dir
    @app.get("/")
    def _root():
        return FileResponse(os.path.join(BASE_DIR, "README.md"))
