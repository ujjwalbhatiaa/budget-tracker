"""Budget tracker API: FastAPI + SQLite.

Endpoints:
    GET    /api/transactions          list (newest first, ?limit=)
    POST   /api/transactions          create
    DELETE /api/transactions/{id}     delete
    PUT    /api/transactions/{id}     update (partial; any of date, description, amount, category)
    GET    /api/summary               per-month spending/income/net + categories
    GET    /api/summary/trend           per-month spending trend for one category
    GET    /api/summary/year            full calendar-year overview (12 month rows + totals)
    GET    /api/summary/top-categories  top-N spending categories for one month (ranked, with share)
    GET    /api/categories            all-time category breakdown
    GET    /api/recurring             detected recurring transactions (subscriptions etc.)
    GET    /api/transactions/export   download all transactions as CSV
    POST   /api/transactions/import   upload a CSV of transactions (per-row validation)
"""

from __future__ import annotations

import os
from datetime import date as date_type, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import get_db
from .schemas import (CategoryTotal, CategoryTrend, MonthSummary,
                      RecurringTransaction,
                      TransactionIn, TransactionOut, TransactionUpdate,
                      TopCategoriesSummary, YearMonth, YearSummary)

from .budgets import router as budgets_router
from .export import router as export_router
from .importer import router as importer_router

app = FastAPI(title="Budget Tracker")
app.include_router(budgets_router)
app.include_router(export_router)
app.include_router(importer_router)

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


@app.get("/api/summary/trend", response_model=list[CategoryTrend])
def category_trend(category: str = Query(..., min_length=1),
                   months: int = Query(default=6, ge=1, le=24)):
    """Monthly spending trend for one category.

    Returns the last `months` calendar months (oldest first), including the
    current month, with each month's spending and the % change vs the previous
    month (None when the previous month had no spending to compare against).
    """
    cat = category.strip().lower() or "other"
    today = date_type.today()
    month_keys = []
    y, m = today.year, today.month
    for _ in range(months):
        month_keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_keys.reverse()
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT substr(date, 1, 7) AS month, SUM(-amount) AS spending"
        " FROM transactions"
        " WHERE amount < 0 AND category = ? AND substr(date, 1, 7) >= ?"
        " GROUP BY month",
        (cat, month_keys[0]),
    ).fetchall()
    spend = {r["month"]: round(r["spending"] or 0, 2) for r in rows}
    out = []
    prev = None
    for key in month_keys:
        cur = spend.get(key, 0.0)
        if prev is None:
            vs = None  # no previous month in the window
        elif prev == 0:
            vs = 0.0 if cur == 0 else None  # nothing to compare against
        else:
            vs = round((cur - prev) / prev * 100, 1)
        out.append(CategoryTrend(month=key, spending=cur, vs_prev_pct=vs))
        prev = cur
    return out


@app.get("/api/summary/year", response_model=YearSummary)
def annual_summary(year: int = Query(default=date_type.today().year,
                                     ge=2000, le=2100)):
    """Full calendar-year overview.

    Returns all 12 months (Jan..Dec, zero-filled for months with no
    transactions) with per-month spending/income/net, plus year totals and
    the average monthly spending across the calendar year.
    """
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT substr(date, 1, 7) AS month,"
        "       SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS spending,"
        "       SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income"
        " FROM transactions WHERE substr(date, 1, 4) = ?"
        " GROUP BY month ORDER BY month",
        (f"{year:04d}",),
    ).fetchall()
    by_month = {r["month"]: (r["spending"] or 0.0, r["income"] or 0.0)
                for r in rows}
    months = []
    total_spending = 0.0
    total_income = 0.0
    for m in range(1, 13):
        label = f"{year:04d}-{m:02d}"
        spending, income = by_month.get(label, (0.0, 0.0))
        total_spending += spending
        total_income += income
        months.append(YearMonth(month=label, spending=round(spending, 2),
                                income=round(income, 2),
                                net=round(income - spending, 2)))
    total_spending = round(total_spending, 2)
    total_income = round(total_income, 2)
    return YearSummary(
        year=year,
        months=months,
        total_spending=total_spending,
        total_income=total_income,
        net=round(total_income - total_spending, 2),
        avg_monthly_spending=round(total_spending / 12, 2),
    )


@app.get("/api/summary/top-categories", response_model=TopCategoriesSummary)
def top_categories(year: int = Query(default=date_type.today().year,
                                     ge=2000, le=2100),
                   month: int = Query(default=date_type.today().month,
                                      ge=1, le=12),
                   limit: int = Query(default=5, ge=1, le=50)):
    """Top-N spending categories for one calendar month.

    Ranks categories by spending (descending) for the given YYYY-MM, each
    with its share of the month's total spending. Only spending counts
    (negative amounts); income is excluded.
    """
    label = f"{year:04d}-{month:02d}"
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT category, SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END)"
        " AS spending FROM transactions WHERE substr(date, 1, 7) = ?"
        " GROUP BY category HAVING spending > 0"
        " ORDER BY spending DESC LIMIT ?",
        (label, limit),
    ).fetchall()
    totals = [(r["category"], r["spending"] or 0.0) for r in rows]
    month_total = round(sum(t for _, t in totals), 2)
    categories = [
        CategoryTotal(
            category=cat,
            total=round(spending, 2),
            share=round(spending / month_total, 4) if month_total else 0.0,
        )
        for cat, spending in totals
    ]
    return TopCategoriesSummary(year=year, month=label,
                                total_spending=month_total,
                                categories=categories)


def _norm_desc(desc: str) -> str:
    return " ".join(desc.lower().split())


@app.get("/api/recurring", response_model=list[RecurringTransaction])
def recurring_transactions(min_occurrences: int = Query(default=3,
                                                        ge=2, le=12)):
    """Detect recurring transactions (subscriptions, rent, paychecks).

    Groups transactions by normalized description + exact amount; a group
    counts as recurring when it has >= min_occurrences hits with every gap
    between consecutive hits inside the 25-35 day monthly window. Reports
    the median gap as the cadence and predicts the next expected date.
    """
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT date, description, amount, category FROM transactions"
        " ORDER BY date"
    ).fetchall()
    groups: dict[tuple[str, float], list] = {}
    for r in rows:
        key = (_norm_desc(r["description"]), round(r["amount"], 2))
        groups.setdefault(key, []).append(r)
    out = []
    for (_desc_key, amount), txns in groups.items():
        if len(txns) < min_occurrences:
            continue
        dates = sorted(date_type.fromisoformat(t["date"]) for t in txns)
        gaps = [(dates[i + 1] - dates[i]).days
                for i in range(len(dates) - 1)]
        if not gaps or any(g < 25 or g > 35 for g in gaps):
            continue
        cadence = int(round(sorted(gaps)[len(gaps) // 2]))
        descs = [t["description"] for t in txns]
        cats = [t["category"] for t in txns]
        out.append(RecurringTransaction(
            description=max(set(descs), key=descs.count),
            amount=round(amount, 2),
            category=max(set(cats), key=cats.count),
            occurrences=len(txns),
            first_date=dates[0].isoformat(),
            last_date=dates[-1].isoformat(),
            cadence_days=cadence,
            next_expected=(dates[-1] + timedelta(days=cadence)).isoformat(),
        ))
    out.sort(key=lambda r: (-r.occurrences, r.description.lower()))
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
