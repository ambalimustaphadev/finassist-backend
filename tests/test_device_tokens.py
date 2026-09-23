"""Tests for the device-token registration API
(POST/DELETE /api/notifications/device-token) and
services/device_token_service.py."""
from models import DeviceToken
from tests.conftest import register_device_token


# --- AUTH ---

def test_register_requires_auth(client):
    response = client.post("/api/notifications/device-token", json={
        "token": "tok", "platform": "ios",
    })
    assert response.status_code == 401


def test_delete_requires_auth(client):
    response = client.delete("/api/notifications/device-token", json={"token": "tok"})
    assert response.status_code == 401


# --- REGISTRATION ---

def test_register_new_token_succeeds(client, auth_headers):
    response = register_device_token(client, auth_headers, token="tok-1", platform="ios")
    assert response.status_code == 200
    body = response.get_json()
    assert body["platform"] == "ios"
    assert "id" in body
    # The raw token is never echoed back.
    assert "token" not in body


def test_register_derives_user_id_from_jwt_not_body(client, auth_headers, user):
    """A user_id in the request body must be ignored — the JWT is the
    only source of truth."""
    user_id, _headers = user
    response = client.post("/api/notifications/device-token", headers=auth_headers, json={
        "token": "tok-1", "platform": "ios", "user_id": 999999,
    })
    assert response.status_code == 200
    token_row = DeviceToken.query.filter_by(token="tok-1").first()
    assert token_row.user_id == user_id


def test_reregistering_same_token_does_not_duplicate(client, auth_headers):
    register_device_token(client, auth_headers, token="tok-1", platform="ios")
    register_device_token(client, auth_headers, token="tok-1", platform="ios")

    assert DeviceToken.query.filter_by(token="tok-1").count() == 1


def test_reregistering_updates_platform_and_last_seen(client, auth_headers):
    register_device_token(client, auth_headers, token="tok-1", platform="ios")
    first = DeviceToken.query.filter_by(token="tok-1").first()
    first_last_seen = first.last_seen_at

    response = register_device_token(client, auth_headers, token="tok-1", platform="android")
    assert response.status_code == 200
    updated = DeviceToken.query.filter_by(token="tok-1").first()
    assert updated.platform == "android"
    assert updated.last_seen_at >= first_last_seen


def test_multiple_devices_per_user(client, auth_headers, user):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="iphone-token", platform="ios")
    register_device_token(client, auth_headers, token="android-token", platform="android")

    tokens = DeviceToken.query.filter_by(user_id=user_id).all()
    assert {t.token for t in tokens} == {"iphone-token", "android-token"}


def test_token_reassigned_when_a_different_user_registers_it(client, auth_headers, other_auth_headers, other_user):
    """A physical device can be logged into by a different account (log
    out / log back in as someone else). The token must follow the most
    recent registration, not stay attached to the original account —
    otherwise the wrong user keeps receiving that device's pushes."""
    other_id, _ = other_user
    register_device_token(client, auth_headers, token="shared-device-token", platform="ios")

    response = register_device_token(client, other_auth_headers, token="shared-device-token", platform="ios")
    assert response.status_code == 200

    rows = DeviceToken.query.filter_by(token="shared-device-token").all()
    assert len(rows) == 1
    assert rows[0].user_id == other_id


def test_register_rejects_invalid_platform(client, auth_headers):
    response = register_device_token(client, auth_headers, token="tok-1", platform="windows-phone")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_rejects_empty_token(client, auth_headers):
    response = register_device_token(client, auth_headers, token="", platform="ios")
    assert response.status_code == 400


def test_register_rejects_missing_token(client, auth_headers):
    response = client.post("/api/notifications/device-token", headers=auth_headers, json={"platform": "ios"})
    assert response.status_code == 400


def test_register_rejects_oversized_token(client, auth_headers):
    response = register_device_token(client, auth_headers, token="x" * 2000, platform="ios")
    assert response.status_code == 400


# --- DELETION ---

def test_delete_removes_own_token(client, auth_headers):
    register_device_token(client, auth_headers, token="tok-1", platform="ios")

    response = client.delete("/api/notifications/device-token", headers=auth_headers, json={"token": "tok-1"})
    assert response.status_code == 200
    assert DeviceToken.query.filter_by(token="tok-1").first() is None


def test_delete_missing_token_returns_404(client, auth_headers):
    response = client.delete("/api/notifications/device-token", headers=auth_headers, json={"token": "does-not-exist"})
    assert response.status_code == 404


def test_delete_rejects_missing_token_field(client, auth_headers):
    response = client.delete("/api/notifications/device-token", headers=auth_headers, json={})
    assert response.status_code == 400


def test_cannot_delete_another_users_token(client, auth_headers, other_auth_headers):
    register_device_token(client, other_auth_headers, token="theirs", platform="ios")

    response = client.delete("/api/notifications/device-token", headers=auth_headers, json={"token": "theirs"})
    assert response.status_code == 404

    still_there = DeviceToken.query.filter_by(token="theirs").first()
    assert still_there is not None


def test_deleting_one_token_does_not_remove_others(client, auth_headers, user):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-a", platform="ios")
    register_device_token(client, auth_headers, token="tok-b", platform="android")

    client.delete("/api/notifications/device-token", headers=auth_headers, json={"token": "tok-a"})

    remaining = DeviceToken.query.filter_by(user_id=user_id).all()
    assert [t.token for t in remaining] == ["tok-b"]
