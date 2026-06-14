# Expense Tracker API 💸

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

A JSON-only REST API for personal expense tracking — built with Flask and SQLite. Token-based auth, full CRUD, filterable queries, spending summary, and CSV export. Designed to serve a mobile app or any frontend.

> **Related:** [SpendWise](https://github.com/jonatakuzi/spendwise) is a full-stack web app built on top of this same domain. This repo is the headless API layer.

---

## Endpoints

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| `GET` | `/` | No | API info and endpoint map |
| `POST` | `/auth/register` | No | Create account |
| `POST` | `/auth/token` | No | Get Bearer token |
| `DELETE` | `/auth/token` | Yes | Revoke current token |
| `GET` | `/expenses` | Yes | List expenses (filterable) |
| `POST` | `/expenses` | Yes | Create expense |
| `GET` | `/expenses/<id>` | Yes | Get single expense |
| `PUT` | `/expenses/<id>` | Yes | Update expense |
| `DELETE` | `/expenses/<id>` | Yes | Delete expense |
| `GET` | `/expenses/summary` | Yes | Spending summary by category + monthly |
| `GET` | `/expenses/export` | Yes | Download expenses as CSV |

Auth endpoints accept/return JSON. All protected endpoints require `Authorization: Bearer <token>`.

---

## Getting Started

```bash
git clone https://github.com/jonatakuzi/expense-tracker-api.git
cd expense-tracker-api
pip install -r requirements.txt
python app.py
```

Server starts at `http://localhost:5000`. SQLite database is created automatically.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-change-in-prod` | Flask secret key |
| `DATABASE` | `expenses.db` | SQLite file path |
| `TOKEN_TTL_HOURS` | `72` | Token lifetime in hours |
| `PORT` | `5000` | Server port |

---

## Usage Examples

```bash
# Register
curl -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"jon","email":"jon@example.com","password":"MyPass123","confirm":"MyPass123"}'

# Get token
curl -X POST http://localhost:5000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"jon@example.com","password":"MyPass123"}'

export TOKEN="<token-from-above>"

# Create expense
curl -X POST http://localhost:5000/expenses \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount":42.50,"category":"Food","description":"Lunch","date":"2024-03-15"}'

# Spending summary
curl http://localhost:5000/expenses/summary -H "Authorization: Bearer $TOKEN"

# CSV export
curl http://localhost:5000/expenses/export -H "Authorization: Bearer $TOKEN" -o expenses.csv
```

---

## Running Tests

```bash
pip install pytest
pytest test_app.py -v
```

## Expense Categories

`Food` · `Transport` · `Housing` · `Entertainment` · `Healthcare` · `Shopping` · `Utilities` · `Other`

## License

MIT
