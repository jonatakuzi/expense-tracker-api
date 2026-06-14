"""
test_app.py — Expense Tracker API tests
Run:  pytest test_app.py -v
"""
import pytest
from app import app, init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE", db_file)
    import app as app_mod
    app_mod.DB_PATH = db_file
    app.config["TESTING"] = True
    with app.test_client() as client:
        init_db()
        yield client


def _register(client, username="alice", email="alice@test.com",
               password="SecurePass1"):
    return client.post("/auth/register", json={
        "username": username, "email": email,
        "password": password, "confirm": password,
    })


def _token(client, email="alice@test.com", password="SecurePass1"):
    rv = client.post("/auth/token", json={"email": email, "password": password})
    return rv.get_json()["token"]


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── registration ──────────────────────────────────────────────────────────────

def test_register_success(client):
    rv = _register(client)
    assert rv.status_code == 201
    data = rv.get_json()
    assert data["username"] == "alice"


def test_register_duplicate_email(client):
    _register(client)
    rv = _register(client, username="bob")
    assert rv.status_code == 409
    assert "email" in rv.get_json()["error"]


def test_register_password_mismatch(client):
    rv = client.post("/auth/register", json={
        "username": "bob", "email": "bob@test.com",
        "password": "SecurePass1", "confirm": "Different1",
    })
    assert rv.status_code == 400


def test_register_short_password(client):
    rv = client.post("/auth/register", json={
        "username": "bob", "email": "bob@test.com",
        "password": "short", "confirm": "short",
    })
    assert rv.status_code == 400


# ── token auth ────────────────────────────────────────────────────────────────

def test_get_token_success(client):
    _register(client)
    rv = client.post("/auth/token", json={
        "email": "alice@test.com", "password": "SecurePass1",
    })
    assert rv.status_code == 200
    assert "token" in rv.get_json()


def test_get_token_wrong_password(client):
    _register(client)
    rv = client.post("/auth/token", json={
        "email": "alice@test.com", "password": "wrongpass",
    })
    assert rv.status_code == 401


def test_protected_endpoint_no_token(client):
    rv = client.get("/expenses")
    assert rv.status_code == 401


# ── expense CRUD ──────────────────────────────────────────────────────────────

def test_create_expense(client):
    _register(client)
    token = _token(client)
    rv = client.post("/expenses", json={
        "amount": 42.50, "category": "Food",
        "description": "Lunch", "date": "2024-03-15",
    }, headers=_auth_headers(token))
    assert rv.status_code == 201
    data = rv.get_json()
    assert data["amount"] == 42.50
    assert data["category"] == "Food"


def test_create_invalid_category(client):
    _register(client)
    token = _token(client)
    rv = client.post("/expenses", json={
        "amount": 10, "category": "InvalidCat", "date": "2024-03-15",
    }, headers=_auth_headers(token))
    assert rv.status_code == 400


def test_create_negative_amount(client):
    _register(client)
    token = _token(client)
    rv = client.post("/expenses", json={
        "amount": -5, "category": "Food", "date": "2024-03-15",
    }, headers=_auth_headers(token))
    assert rv.status_code == 400


def test_list_expenses(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    client.post("/expenses", json={
        "amount": 20, "category": "Transport", "date": "2024-03-10",
    }, headers=hdrs)
    client.post("/expenses", json={
        "amount": 50, "category": "Food", "date": "2024-03-11",
    }, headers=hdrs)
    rv = client.get("/expenses", headers=hdrs)
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["total"] == 2
    assert len(data["expenses"]) == 2


def test_filter_by_category(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    client.post("/expenses", json={"amount": 20, "category": "Food", "date": "2024-03-10"}, headers=hdrs)
    client.post("/expenses", json={"amount": 30, "category": "Transport", "date": "2024-03-11"}, headers=hdrs)
    rv = client.get("/expenses?category=Food", headers=hdrs)
    assert rv.status_code == 200
    expenses = rv.get_json()["expenses"]
    assert all(e["category"] == "Food" for e in expenses)


def test_get_expense(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    rv = client.post("/expenses", json={
        "amount": 15, "category": "Shopping", "date": "2024-03-12",
    }, headers=hdrs)
    exp_id = rv.get_json()["id"]
    rv2 = client.get(f"/expenses/{exp_id}", headers=hdrs)
    assert rv2.status_code == 200
    assert rv2.get_json()["id"] == exp_id


def test_update_expense(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    rv = client.post("/expenses", json={
        "amount": 15, "category": "Shopping", "date": "2024-03-12",
    }, headers=hdrs)
    exp_id = rv.get_json()["id"]
    rv2 = client.put(f"/expenses/{exp_id}", json={"amount": 25}, headers=hdrs)
    assert rv2.status_code == 200
    assert rv2.get_json()["amount"] == 25


def test_delete_expense(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    rv = client.post("/expenses", json={
        "amount": 15, "category": "Food", "date": "2024-03-12",
    }, headers=hdrs)
    exp_id = rv.get_json()["id"]
    rv2 = client.delete(f"/expenses/{exp_id}", headers=hdrs)
    assert rv2.status_code == 204
    rv3 = client.get(f"/expenses/{exp_id}", headers=hdrs)
    assert rv3.status_code == 404


def test_cannot_access_other_users_expense(client):
    _register(client, "alice", "alice@test.com")
    _register(client, "bob", "bob@test.com")
    token_a = _token(client, "alice@test.com")
    token_b = _token(client, "bob@test.com")

    rv = client.post("/expenses", json={
        "amount": 99, "category": "Other", "date": "2024-03-01",
    }, headers=_auth_headers(token_a))
    exp_id = rv.get_json()["id"]

    rv2 = client.get(f"/expenses/{exp_id}", headers=_auth_headers(token_b))
    assert rv2.status_code == 404


# ── summary & export ──────────────────────────────────────────────────────────

def test_summary(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    client.post("/expenses", json={"amount": 30, "category": "Food", "date": "2024-03-01"}, headers=hdrs)
    client.post("/expenses", json={"amount": 20, "category": "Transport", "date": "2024-03-02"}, headers=hdrs)
    rv = client.get("/expenses/summary", headers=hdrs)
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["transaction_count"] == 2
    assert data["total_spent"] == 50.0


def test_export_csv(client):
    _register(client)
    token = _token(client)
    hdrs = _auth_headers(token)
    client.post("/expenses", json={"amount": 12, "category": "Food", "date": "2024-03-01"}, headers=hdrs)
    rv = client.get("/expenses/export", headers=hdrs)
    assert rv.status_code == 200
    assert "text/csv" in rv.content_type
    assert b"Food" in rv.data
