"""Monthly per-category budget caps and spend-vs-budget status.

Endpoints:
    GET    /api/budgets              list all caps
    GET    /api/budgets/{category}   one cap (404 when none set)
    PUT    /api/budgets/{category}   set/update a cap (body: {"monthly_limit": N})
    DELETE /api/budgets/{category}   remove a cap
    GET    /api/budget-status        spend vs cap per category (?month=YYYY-MM,
                                    defaults to the current month)

Register on the main app with: app.include_router(budgets.router)
"""

from __future__ import annotations

import os
import re
from datetime import date

from fastapi import APIRouter, HTTPException

from .database import get_db
from .schemas import BudgetIn, BudgetOut, BudgetStatus

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("BUDGET_DB", os.path.join(BASE_DIR, "budget.db"))

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _norm_category(raw: str) -> str:
    return raw.strip().lower()


@router.get("/api/budgets", response_model=list[BudgetOut])
def list_budgets():
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT category, monthly_limit FROM budgets ORDER BY category"
    ).fetchall()
    return [
        BudgetOut(category=r["category"], monthly_limit=r["monthly_limit"])
        for r in rows
    ]


@router.get("/api/budgets/{category}", response_model=BudgetOut)
def get_budget(category: str):
    db = get_db(DB_PATH)
    row = db.execute(
        "SELECT category, monthly_limit FROM budgets WHERE category = ?",
        (_norm_category(category),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no budget for category")
    return BudgetOut(category=row["category"],
                     monthly_limit=row["monthly_limit"])


@router.put("/api/budgets/{category}", response_model=BudgetOut)
def set_budget(category: str, body: BudgetIn):
    cat = _norm_category(category)
    if not cat:
        raise HTTPException(status_code=422,
                            detail="category must not be blank")
    db = get_db(DB_PATH)
    db.execute(
        "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?)"
        " ON CONFLICT(category) DO UPDATE"
        " SET monthly_limit = excluded.monthly_limit",
        (cat, body.monthly_limit),
    )
    db.commit()
    return BudgetOut(category=cat, monthly_limit=body.monthly_limit)


@router.delete("/api/budgets/{category}", status_code=204)
def delete_budget(category: str):
    db = get_db(DB_PATH)
    cur = db.execute("DELETE FROM budgets WHERE category = ?",
                     (_norm_category(category),))
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="no budget for category")


@router.get("/api/budget-status", response_model=list[BudgetStatus])
def budget_status(month: str | None = None):
    if month is None:
        month = date.today().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    db = get_db(DB_PATH)
    caps = db.execute("SELECT category, monthly_limit FROM budgets").fetchall()
    spent_rows = db.execute(
        "SELECT category, SUM(-amount) AS spent FROM transactions"
        " WHERE substr(date, 1, 7) = ? AND amount < 0 GROUP BY category",
        (month,),
    ).fetchall()
    spent = {r["category"]: (r["spent"] or 0.0) for r in spent_rows}
    out = []
    for c in caps:
        cat = c["category"]
        limit = c["monthly_limit"]
        s = round(spent.get(cat, 0.0), 2)
        out.append(BudgetStatus(
            category=cat,
            month=month,
            monthly_limit=limit,
            spent=s,
            remaining=round(limit - s, 2),
            pct_used=round(s / limit * 100, 1),
            over=s > limit,
        ))
    return sorted(out, key=lambda b: b.category)
