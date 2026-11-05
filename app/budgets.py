"""Monthly per-category budget caps and spend-vs-budget status.

Endpoints:
    GET    /api/budgets              list all caps
    GET    /api/budgets/{category}   one cap (404 when none set)
    PUT    /api/budgets/{category}   set/update a cap (body: {"monthly_limit": N})
    DELETE /api/budgets/{category}   remove a cap
    GET    /api/budget-status        spend vs cap per category (?month=YYYY-MM,
                                    defaults to the current month;
                                    ?over_only=true keeps only categories
                                    that exceeded their cap)
    GET    /api/budget-status/totals    aggregate caps/spend across all
                                    capped categories (?month=YYYY-MM)
    GET    /api/budget-status/alerts    categories at or above a usage
                                    threshold (?month=YYYY-MM,
                                    ?threshold=80, most-used first)
    GET    /api/budget-status/{category}  spend vs cap for one category
                                    (?month=YYYY-MM, 404 when no cap set)
    GET    /api/budget-status/{category}/history  same, over the last N
                                    months (?month=YYYY-MM, ?months=6)

Register on the main app with: app.include_router(budgets.router)
"""

from __future__ import annotations

import os
import re
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .database import get_db
from .schemas import (
    BudgetCompare,
    BudgetIn,
    BudgetOut,
    BudgetStatus,
    BudgetTotals,
)

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
def budget_status(month: str | None = None, over_only: bool = False):
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
    out = sorted(out, key=lambda b: b.category)
    if over_only:
        out = [b for b in out if b.over]
    return out


@router.get("/api/budget-status/totals", response_model=BudgetTotals)
def budget_status_totals(month: str | None = None):
    """Aggregate budget-status across every capped category.

    Defined before the /{category} route so "totals" is not captured
    as a category name. Same month validation and spend math as
    budget_status; categories with no spending count as spent 0.
    """
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
    total_limit = round(sum(c["monthly_limit"] for c in caps), 2)
    total_spent = round(sum(spent.get(c["category"], 0.0) for c in caps), 2)
    over_count = sum(
        1 for c in caps if spent.get(c["category"], 0.0) > c["monthly_limit"])
    return BudgetTotals(
        month=month,
        categories=len(caps),
        total_limit=total_limit,
        total_spent=total_spent,
        total_remaining=round(total_limit - total_spent, 2),
        pct_used=round(total_spent / total_limit * 100, 1)
        if total_limit else 0.0,
        over_count=over_count,
    )


@router.get("/api/budget-status/alerts", response_model=list[BudgetStatus])
def budget_status_alerts(
    month: str | None = None,
    threshold: float = Query(default=80, ge=0, le=100),
):
    """Categories at or above `threshold` percent of their cap, most-used first.

    Defined before the /{category} route so "alerts" is not captured as a
    category name. Reuses budget_status's month validation and spend math,
    so over-cap categories (pct_used > 100) always alert at any threshold.
    """
    rows = budget_status(month=month)
    alerted = [b for b in rows if b.pct_used >= threshold]
    return sorted(alerted, key=lambda b: b.pct_used, reverse=True)


@router.get("/api/budget-status/compare", response_model=list[BudgetCompare])
def budget_status_compare(
    month: str | None = None,
    prev_month: str | None = None,
):
    """Per-category spend in `month` vs `prev_month` (defaults to the
    calendar month before `month`, or before the current month).

    Defined before the /{category} route so "compare" is not captured
    as a category name. Reuses budget_status rows for both months, so
    month validation and spend math stay identical; categories with a
    cap but no spending in either month appear with zeros.
    """
    if month is None:
        month = date.today().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    if prev_month is None:
        year, mon = int(month[:4]), int(month[5:7])
        if mon == 1:
            year, mon = year - 1, 12
        else:
            mon -= 1
        prev_month = f"{year:04d}-{mon:02d}"
    if not _MONTH_RE.match(prev_month):
        raise HTTPException(status_code=422, detail="prev_month must be YYYY-MM")
    current = {b.category: b for b in budget_status(month=month)}
    previous = {b.category: b for b in budget_status(month=prev_month)}
    out = []
    for cat in sorted(set(current) | set(previous)):
        cur = current.get(cat)
        prev = previous.get(cat)
        limit = (cur or prev).monthly_limit
        spent = cur.spent if cur else 0.0
        prev_spent = prev.spent if prev else 0.0
        out.append(BudgetCompare(
            category=cat,
            month=month,
            prev_month=prev_month,
            monthly_limit=limit,
            spent=spent,
            prev_spent=prev_spent,
            delta_spent=round(spent - prev_spent, 2),
            pct_used=cur.pct_used if cur else 0.0,
            prev_pct_used=prev.pct_used if prev else 0.0,
        ))
    return out


@router.get("/api/budget-status/{category}/history",
            response_model=list[BudgetStatus])
def budget_status_history(
    category: str,
    month: str | None = None,
    months: int = Query(default=6, ge=1, le=12),
):
    """Spend vs cap for one category over the last `months` months,
    ending at `month` (defaults to the current month), oldest first.

    Defined before the /{category} route so the extra path segment is
    never captured as a category. Reuses budget_status_for_category
    for each month, so validation and spend math stay identical; a
    month with no spending appears with spent 0. 404 when no cap set.
    """
    if month is None:
        month = date.today().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    # 404 early, before building the month list.
    budget_status_for_category(category, month=month)
    year, mon = int(month[:4]), int(month[5:7])
    seq = []
    for _ in range(months):
        seq.append(f"{year:04d}-{mon:02d}")
        if mon == 1:
            year, mon = year - 1, 12
        else:
            mon -= 1
    seq.reverse()
    return [budget_status_for_category(category, month=m) for m in seq]


@router.get("/api/budget-status/{category}", response_model=BudgetStatus)
def budget_status_for_category(category: str, month: str | None = None):
    if month is None:
        month = date.today().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    cat = _norm_category(category)
    db = get_db(DB_PATH)
    row = db.execute(
        "SELECT category, monthly_limit FROM budgets WHERE category = ?",
        (cat,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no budget for category")
    spent_row = db.execute(
        "SELECT SUM(-amount) AS spent FROM transactions"
        " WHERE category = ? AND substr(date, 1, 7) = ? AND amount < 0",
        (cat, month),
    ).fetchone()
    spent = round(spent_row["spent"] or 0.0, 2)
    limit = row["monthly_limit"]
    return BudgetStatus(
        category=cat,
        month=month,
        monthly_limit=limit,
        spent=spent,
        remaining=round(limit - spent, 2),
        pct_used=round(spent / limit * 100, 1),
        over=spent > limit,
    )
