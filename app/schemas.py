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
