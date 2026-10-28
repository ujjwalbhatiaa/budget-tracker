# budget-tracker

A full-stack personal budget tracker: a FastAPI + SQLite backend with a
vanilla-JS frontend. Add transactions, browse history, and see monthly
summaries with per-category spending breakdowns.

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 — the UI is served by the same app.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/transactions?limit=100` | List transactions, newest first |
| `GET` | `/api/transactions/{id}` | Fetch one transaction (404 if missing) |
| `POST` | `/api/transactions` | Create (`date`, `description`, `amount`, `category`) |
| `DELETE` | `/api/transactions/{id}` | Delete one |
| `PUT` | `/api/transactions/{id}` | Update (`date`, `description`, `amount`, `category` — all optional) |
| `GET` | `/api/summary` | Per-month spending / income / net + category shares |
| `GET` | `/api/categories` | All-time spending by category |

Amounts are negative for spending, positive for income (zero is rejected).
Validation is enforced with Pydantic: real dates, non-blank descriptions,
non-zero amounts.

## Project layout

```
app/
  main.py        # FastAPI app + routes, serves the frontend
  database.py    # SQLite setup (WAL-friendly single connection + lock)
  schemas.py     # Pydantic request/response models
static/
  index.html     # dashboard page
  app.js         # fetch-based UI: add/delete/render, no framework
  styles.css     # dark theme
tests/
  test_api.py    # 11 endpoint tests via FastAPI TestClient
```

## Deploy notes

The app reads `BUDGET_DB` for the SQLite path (defaults to `budget.db`
next to the code) and serves `static/` from `/`, so it deploys as-is on
Render, Railway, or Fly.io: install requirements, run
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`. For a multi-user
future, swap the SQLite module for Postgres — the route layer doesn't care.

## Tests

```bash
pytest
```

11 tests: create/list ordering, validation (zero amount, bad date, blank
description), delete + 404, monthly summary math, category breakdowns,
empty-state behavior, and category normalization.
