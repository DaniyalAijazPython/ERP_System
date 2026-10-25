from tests.conftest import COMPANY


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_returns_tokens_and_me(client, owner_headers):
    me = client.get("/api/v1/me", headers=owner_headers)
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "owner@example.com"
    assert body["role"] == "owner"

    tenant = client.get("/api/v1/tenant", headers=owner_headers).json()
    assert tenant["name"] == "Karachi Steel Works"
    assert tenant["base_currency"] == "PKR"


def test_duplicate_email_rejected(client, owner_tokens):
    r = client.post("/api/v1/auth/register-company", json={**COMPANY, "company_name": "Other Co"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


def test_login_ok_and_wrong_password(client, owner_tokens):
    ok = client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": COMPANY["password"]})
    assert ok.status_code == 200
    assert "access_token" in ok.json()

    bad = client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_refresh_flow_and_token_type_checks(client, owner_tokens):
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": owner_tokens["refresh_token"]})
    assert r.status_code == 200

    # an access token must not work as a refresh token, and vice versa
    wrong = client.post("/api/v1/auth/refresh", json={"refresh_token": owner_tokens["access_token"]})
    assert wrong.status_code == 401
    as_access = client.get("/api/v1/me", headers={"Authorization": f"Bearer {owner_tokens['refresh_token']}"})
    assert as_access.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_owner_creates_user_and_role_limits(client, owner_headers):
    r = client.post(
        "/api/v1/create_users",
        headers=owner_headers,
        json={"full_name": "Bilal Store", "email": "bilal@example.com", "password": "store-pass-1", "role": "store"},
    )
    assert r.status_code == 201
    assert r.json()["role"] == "store"

    # the store keeper logs in but cannot manage users
    login = client.post("/api/v1/auth/login", json={"email": "bilal@example.com", "password": "store-pass-1"}).json()
    store_headers = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get("/api/v1/me", headers=store_headers).status_code == 200
    forbidden = client.get("/api/v1/users", headers=store_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"


def test_cannot_create_second_owner(client, owner_headers):
    r = client.post(
        "/api/v1/create_users",
        headers=owner_headers,
        json={"full_name": "Eve", "email": "eve@example.com", "password": "password-123", "role": "owner"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_ROLE"


def test_tenants_are_isolated(client, owner_headers):
    other = client.post(
        "/api/v1/auth/register-company",
        json={"company_name": "Lahore Plastics", "full_name": "Omar", "email": "omar@example.com", "password": "omar-pass-1"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    mine = client.get("/api/v1/users", headers=owner_headers).json()
    theirs = client.get("/api/v1/users", headers=other_headers).json()
    assert {u["email"] for u in mine} == {"owner@example.com"}
    assert {u["email"] for u in theirs} == {"omar@example.com"}
