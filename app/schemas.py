"""Pydantic schemas for the budget tracker API."""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, Field, field_validator


class TransactionIn(BaseModel):
    date: date_type
    description: str = Field(min_length=1, max_length=200)
    amount: float  # negative = spending, positive = income (never zero)
    category: str = Field(default="other", max_length=50)

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("description must not be blank")
        return v

    @field_validator("amount")
    @classmethod
    def amount_nonzero(cls, v: float) -> float:
        if v == 0:
            raise ValueError("amount must be non-zero")
        return v


class TransactionOut(TransactionIn):
    id: int


class TransactionUpdate(BaseModel):
    """Partial update for a transaction: every field optional."""

    date: date_type | None = None
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount: float | None = None  # negative = spending, positive = income (never zero)
    category: str | None = Field(default=None, max_length=50)

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("description must not be blank")
        return v

    @field_validator("amount")
    @classmethod
    def amount_nonzero(cls, v: float | None) -> float | None:
        if v is not None and v == 0:
            raise ValueError("amount must be non-zero")
        return v


class CategoryTotal(BaseModel):
    category: str
    total: float
    share: float


class MonthSummary(BaseModel):
    month: str  # YYYY-MM
    spending: float
    income: float
    net: float
    by_category: list[CategoryTotal]


class BudgetIn(BaseModel):
    """Set a monthly spending cap for a category (must be positive)."""

    monthly_limit: float = Field(gt=0)


class BudgetOut(BaseModel):
    category: str
    monthly_limit: float


class ImportRowError(BaseModel):
    """One rejected CSV row: the file's line number and why it failed."""

    row: int
    error: str


class ImportResult(BaseModel):
    """Outcome of POST /api/transactions/import."""

    imported: int
    skipped: int
    errors: list[ImportRowError]


class BudgetStatus(BaseModel):
    """Spend vs cap for one category in one month."""

    category: str
    month: str  # YYYY-MM
    monthly_limit: float
    spent: float
    remaining: float
    pct_used: float
    over: bool


class CategoryTrend(BaseModel):
    """One month of a category's spending trend."""

    month: str  # YYYY-MM
    spending: float  # positive total spent this month
    vs_prev_pct: float | None  # % change vs previous month; None when prev == 0


class YearMonth(BaseModel):
    """One month row of the annual summary (zero-filled for empty months)."""

    month: str  # YYYY-MM
    spending: float  # positive total spent this month
    income: float  # positive total income this month
    net: float  # income - spending


class YearSummary(BaseModel):
    """Full calendar-year overview: 12 month rows plus year totals."""

    year: int
    months: list[YearMonth]  # Jan..Dec, always 12 rows
    total_spending: float
    total_income: float
    net: float
    avg_monthly_spending: float  # total_spending / 12 (calendar-year average)


class TopCategoriesSummary(BaseModel):
    """Ranked top-spending categories for one calendar month."""

    year: int
    month: str  # YYYY-MM
    total_spending: float  # month's total spending (positive)
    categories: list[CategoryTotal]  # top N by spending, desc; empty when none


class RecurringTransaction(BaseModel):
    """A detected recurring transaction (subscription, rent, paycheck...)."""

    description: str  # most common original-cased description in the group
    amount: float  # per-occurrence amount (negative = spending)
    category: str  # most common category in the group
    occurrences: int  # how many times it repeated
    first_date: str  # YYYY-MM-DD of earliest occurrence
    last_date: str  # YYYY-MM-DD of latest occurrence
    cadence_days: int  # median gap between occurrences
    next_expected: str  # YYYY-MM-DD of the predicted next occurrence
