"""Authentication flows: register, login, refresh rotation, profile, reset."""
from tests.conftest import AUTH, auth_headers, make_user


def test_register_login_me(client):
    tokens = make_user(client, "ali@example.com", name="Ali")
    r = client.get(f"{AUTH}/me", headers=auth_headers(tokens["access_token"]))
    assert r.status_code == 200
    assert r.json()["email"] == "ali@example.com"
    assert r.json()["full_name"] == "Ali"


def test_duplicate_email_rejected(client):
    make_user(client, "dup@example.com")
    r = client.post(f"{AUTH}/register", json={"email": "dup@example.com", "password": "Parol12345"})
    assert r.status_code == 409


def test_weak_password_rejected(client):
    r = client.post(f"{AUTH}/register", json={"email": "weak@example.com", "password": "123"})
    assert r.status_code == 422


def test_wrong_password(client):
    make_user(client, "vali@example.com")
    r = client.post(f"{AUTH}/login", json={"email": "vali@example.com", "password": "WrongPass1"})
    assert r.status_code == 401


def test_refresh_rotation_and_revocation(client):
    tokens = make_user(client, "rot@example.com")
    old_refresh = tokens["refresh_token"]
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != old_refresh
    # old refresh token must now be revoked (rotation)
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401
    # new one still works
    r = client.post(f"{AUTH}/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert r.status_code == 200


def test_access_token_required(client):
    r = client.get(f"{AUTH}/me")
    assert r.status_code == 401
    r = client.get(f"{AUTH}/me", headers=auth_headers("garbage.token.here"))
    assert r.status_code == 401


def test_profile_update(client):
    tokens = make_user(client, "prof@example.com")
    h = auth_headers(tokens["access_token"])
    r = client.patch(f"{AUTH}/me/profile", json={"theme": "dark", "daily_goal_minutes": 45}, headers=h)
    assert r.status_code == 200
    assert r.json()["theme"] == "dark"
    assert r.json()["daily_goal_minutes"] == 45


def test_change_password(client):
    tokens = make_user(client, "cp@example.com")
    h = auth_headers(tokens["access_token"])
    r = client.post(f"{AUTH}/change-password",
                    json={"current_password": "Parol12345", "new_password": "YangiParol99"}, headers=h)
    assert r.status_code == 200
    # old password no longer valid
    r = client.post(f"{AUTH}/login", json={"email": "cp@example.com", "password": "Parol12345"})
    assert r.status_code == 401
    r = client.post(f"{AUTH}/login", json={"email": "cp@example.com", "password": "YangiParol99"})
    assert r.status_code == 200


def test_forgot_reset_flow(client):
    make_user(client, "reset@example.com")
    r = client.post(f"{AUTH}/forgot-password", json={"email": "reset@example.com"})
    assert r.status_code == 200
    data = r.json()
    # dev mode: SMTP not configured -> link returned, delivery NOT faked
    assert data["delivered"] is False
    assert data["reset_link"] and "token=" in data["reset_link"]
    token = data["reset_link"].split("token=")[1]
    r = client.post(f"{AUTH}/reset-password", json={"token": token, "new_password": "TokParol77"})
    assert r.status_code == 200
    r = client.post(f"{AUTH}/login", json={"email": "reset@example.com", "password": "TokParol77"})
    assert r.status_code == 200
    # token is single-use
    r = client.post(f"{AUTH}/reset-password", json={"token": token, "new_password": "Another123"})
    assert r.status_code == 400


def test_forgot_password_no_enumeration(client):
    r = client.post(f"{AUTH}/forgot-password", json={"email": "nonexistent@example.com"})
    assert r.status_code == 200
    assert r.json()["reset_link"] is None
