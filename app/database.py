"""SQLite storage for the budget tracker."""

from __future__ import annotations

import sqlite3
import threading

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def get_db(path: str = "budget.db") -> sqlite3.Connection:
    global _db
    if _db is None:
        _db = sqlite3.connect(path, check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute(
            """CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, -- YYYY-MM-DD
            description TEXT NOT NULL,
            amount REAL NOT NULL, -- negative = spending
            category TEXT NOT NULL DEFAULT 'other'
        )"""
        )
        _db.execute(
            """CREATE TABLE IF NOT EXISTS budgets (
            category TEXT PRIMARY KEY, -- normalized (lowercase, trimmed)
            monthly_limit REAL NOT NULL -- positive spending cap
        )"""
        )
        _db.execute(
            "CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date)"
        )
        _db.commit()
    return _db


def reset_db(path: str = "budget.db") -> None:
    """Drop and recreate tables (used by tests)."""
    global _db
    with _lock:
        if _db is not None:
            _db.close()
        _db = None
    import os
    if os.path.exists(path):
        os.remove(path)
    get_db(path)
