"""
app.py — Expense Tracker REST API
A JSON-only REST API for managing personal expenses.
Auth: token-based (register → /auth/token → use Bearer token in header)
"""
import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, Response, g, jsonify, request

# ── config ────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
DB_PATH = os.environ.get("DATABASE", "expenses.db")
TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", "72"))

CATEGORIES = [
    "Food", "Transport", "Housing", "Entertainment",
    "Healthcare", "Shopping", "Utilities", "Other",
]

# ── database ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT    UNIQUE NOT NULL,
                email    TEXT    UNIQUE NOT NULL,
                password TEXT    NOT NULL,
                created  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token      TEXT    UNIQUE NOT NULL,
                expires_at TEXT    NOT NULL,
                created    TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount      REAL    NOT NULL CHECK(amount > 0),
                category    TEXT    NOT NULL,
                description TEXT,
                date        TEXT    NOT NULL,
                created     TEXT    DEFAULT (datetime('now')),
                updated     TEXT    DEFAULT (datetime('now'))
            );
        """)
        db.commit()


# ── auth helpers ──────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password)


def _check_password(stored: str, supplied: str) -> bool:
    from werkzeug.security import check_password_hash
    return check_password_hash(stored, supplied)


def _generate_token() -> str:
    return secrets.token_hex(32)


def _get_token_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    db = get_db()
    row = db.execute(
        "SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id "
        "WHERE t.token = ? AND t.expires_at > datetime('now')",
        (token,),
    ).fetchone()
    return row


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _get_token_user()
        if not user:
            return jsonify({"error": "Unauthorized — provide a valid Bearer token"}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


# ── error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405


# ── utility ───────────────────────────────────────────────────────────────────

def _row_to_expense(row: sqlite3.Row) -> dict:
    return {
        "id":          row["id"],
        "amount":      row["amount"],
        "category":    row["category"],
        "description": row["description"],
        "date":        row["date"],
        "created":     row["created"],
        "updated":     row["updated"],
    }


def _validate_expense_payload(data: dict):
    """Returns (cleaned_data, error_message)."""
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return None, "amount must be a positive number"
    if amount <= 0:
        return None, "amount must be greater than zero"

    category = data.get("category", "").strip()
    if category not in CATEGORIES:
        return None, f"category must be one of: {', '.join(CATEGORIES)}"

    date_str = data.get("date", "").strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None, "date must be in YYYY-MM-DD format"

    description = (data.get("description") or "").strip()[:300]
    return {
        "amount":      round(amount, 2),
        "category":    category,
        "date":        date_str,
        "description": description or None,
    }, None


# ── routes: info ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "name":       "Expense Tracker API",
        "version":    "1.0.0",
        "categories": CATEGORIES,
        "endpoints": {
            "POST /auth/register":    "Create account",
            "POST /auth/token":       "Get auth token",
            "DELETE /auth/token":     "Revoke current token",
            "GET /expenses":          "List expenses (filterable)",
            "POST /expenses":         "Create expense",
            "GET /expenses/<id>":     "Get expense",
            "PUT /expenses/<id>":     "Update expense",
            "DELETE /expenses/<id>":  "Delete expense",
            "GET /expenses/summary":  "Spending summary",
            "GET /expenses/export":   "Export expenses as CSV",
        },
    })


# ── routes: auth ──────────────────────────────────────────────────────────────

@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()
    confirm  = (data.get("confirm")  or "").strip()

    if not all([username, email, password]):
        return jsonify({"error": "username, email, and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400
    if password != confirm:
        return jsonify({"error": "passwords do not match"}), 400

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "username already taken"}), 409
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify({"error": "email already in use"}), 409

    pw_hash = _hash_password(password)
    cur = db.execute(
        "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
        (username, email, pw_hash),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid, "username": username, "email": email}), 201


@app.route("/auth/token", methods=["POST"])
def get_token():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not _check_password(user["password"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    token      = _generate_token()
    expires_at = (datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    db.execute(
        "INSERT INTO tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires_at),
    )
    db.commit()
    return jsonify({
        "token":      token,
        "expires_at": expires_at,
        "token_type": "Bearer",
    }), 200


@app.route("/auth/token", methods=["DELETE"])
@require_auth
def revoke_token():
    header = request.headers.get("Authorization", "")[7:].strip()
    get_db().execute("DELETE FROM tokens WHERE token = ?", (header,))
    get_db().commit()
    return "", 204


# ── routes: expenses ──────────────────────────────────────────────────────────

@app.route("/expenses", methods=["GET"])
@require_auth
def list_expenses():
    uid       = g.current_user["id"]
    category  = request.args.get("category")
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    limit     = min(int(request.args.get("limit", 100)), 500)
    offset    = int(request.args.get("offset", 0))

    sql    = "SELECT * FROM expenses WHERE user_id = ?"
    params = [uid]

    if category and category in CATEGORIES:
        sql += " AND category = ?"
        params.append(category)
    if date_from:
        sql += " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        params.append(date_to)

    sql += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    db    = get_db()
    rows  = db.execute(sql, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (uid,)
    ).fetchone()[0]

    return jsonify({
        "expenses": [_row_to_expense(r) for r in rows],
        "total":    total,
        "limit":    limit,
        "offset":   offset,
    })


@app.route("/expenses", methods=["POST"])
@require_auth
def create_expense():
    data, err = _validate_expense_payload(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400

    db  = get_db()
    cur = db.execute(
        "INSERT INTO expenses (user_id, amount, category, description, date) "
        "VALUES (?, ?, ?, ?, ?)",
        (g.current_user["id"], data["amount"], data["category"],
         data["description"], data["date"]),
    )
    db.commit()
    row = db.execute("SELECT * FROM expenses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(_row_to_expense(row)), 201


@app.route("/expenses/summary", methods=["GET"])
@require_auth
def summary():
    uid = g.current_user["id"]
    db  = get_db()

    by_cat = db.execute(
        "SELECT category, COUNT(*) count, ROUND(SUM(amount),2) total "
        "FROM expenses WHERE user_id = ? GROUP BY category ORDER BY total DESC",
        (uid,),
    ).fetchall()

    monthly = db.execute(
        "SELECT strftime('%Y-%m', date) month, ROUND(SUM(amount),2) total "
        "FROM expenses WHERE user_id = ? "
        "GROUP BY month ORDER BY month DESC LIMIT 12",
        (uid,),
    ).fetchall()

    totals = db.execute(
        "SELECT COUNT(*) count, ROUND(SUM(amount),2) total, ROUND(AVG(amount),2) avg "
        "FROM expenses WHERE user_id = ?",
        (uid,),
    ).fetchone()

    this_month = db.execute(
        "SELECT ROUND(SUM(amount),2) total FROM expenses "
        "WHERE user_id = ? AND strftime('%Y-%m', date) = strftime('%Y-%m', 'now')",
        (uid,),
    ).fetchone()

    return jsonify({
        "total_spent":       totals["total"] or 0,
        "transaction_count": totals["count"],
        "average_per_entry": totals["avg"] or 0,
        "this_month":        this_month["total"] or 0,
        "by_category":       [dict(r) for r in by_cat],
        "monthly":           [dict(r) for r in monthly],
    })


@app.route("/expenses/export", methods=["GET"])
@require_auth
def export_csv():
    uid  = g.current_user["id"]
    rows = get_db().execute(
        "SELECT amount, category, description, date, created "
        "FROM expenses WHERE user_id = ? ORDER BY date DESC",
        (uid,),
    ).fetchall()

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["amount", "category", "description", "date", "created"])
    w.writerows(rows)

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


@app.route("/expenses/<int:expense_id>", methods=["GET"])
@require_auth
def get_expense(expense_id: int):
    row = get_db().execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, g.current_user["id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "Expense not found"}), 404
    return jsonify(_row_to_expense(row))


@app.route("/expenses/<int:expense_id>", methods=["PUT"])
@require_auth
def update_expense(expense_id: int):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, g.current_user["id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "Expense not found"}), 404

    current = dict(row)
    payload = request.get_json(silent=True) or {}
    merged  = {
        "amount":      payload.get("amount",      current["amount"]),
        "category":    payload.get("category",    current["category"]),
        "date":        payload.get("date",         current["date"]),
        "description": payload.get("description", current["description"]),
    }

    data, err = _validate_expense_payload(merged)
    if err:
        return jsonify({"error": err}), 400

    db.execute(
        "UPDATE expenses SET amount=?, category=?, description=?, date=?, "
        "updated=datetime('now') WHERE id=?",
        (data["amount"], data["category"], data["description"],
         data["date"], expense_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return jsonify(_row_to_expense(updated))


@app.route("/expenses/<int:expense_id>", methods=["DELETE"])
@require_auth
def delete_expense(expense_id: int):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, g.current_user["id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "Expense not found"}), 404
    db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    return "", 204


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=port)
