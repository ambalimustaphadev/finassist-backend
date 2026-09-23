"""Tests for services/push_notification_service.py: Firebase Admin
initialization and send_push_notification. Real Firebase is never
touched — initialization tests mock the SDK's own entry points
(credentials.Certificate / firebase_admin.initialize_app), and send
tests monkeypatch `_send_multicast` (see conftest.fake_push).
"""
import pytest

import services.push_notification_service as push_notification_service
from models import DeviceToken
from services.push_notification_service import (
    PushNotificationUnavailable,
    is_configured,
    send_push_notification,
)
from tests.conftest import register_device_token


@pytest.fixture(autouse=True)
def _reset_firebase_process_state():
    """The module caches its initialized Firebase app at process/module
    scope (deliberately — see the module docstring on why init happens
    at most once). Tests must not leak that cache between each other,
    so it's reset before and after every test in this file."""
    push_notification_service._app = None
    push_notification_service._init_attempted = False
    yield
    push_notification_service._app = None
    push_notification_service._init_attempted = False


# --- initialization / configuration ---

def test_not_configured_when_no_credentials_set(client, monkeypatch):
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_JSON", None)
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_PATH", None)
    assert is_configured() is False


def test_malformed_credentials_json_disables_push_without_raising(client, monkeypatch):
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_JSON", "{not valid json")
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_PATH", None)
    assert is_configured() is False


def test_credentials_path_pointing_nowhere_disables_push_without_raising(client, monkeypatch):
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_JSON", None)
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_PATH", "/no/such/file.json")
    assert is_configured() is False


def test_initialization_succeeds_with_mocked_sdk_entry_points(client, monkeypatch):
    """Firebase Admin's own credential parsing/initialization is never
    exercised with real crypto — the SDK's entry points themselves are
    mocked, per the module's own testing contract."""
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_JSON", '{"type": "service_account"}')
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_PATH", None)

    fake_cred = object()
    fake_app = object()
    monkeypatch.setattr(
        "services.push_notification_service.credentials.Certificate",
        lambda info: fake_cred,
    )
    init_calls = []
    monkeypatch.setattr(
        "services.push_notification_service.firebase_admin.initialize_app",
        lambda cred, name=None: init_calls.append((cred, name)) or fake_app,
    )

    assert is_configured() is True
    assert init_calls == [(fake_cred, "finassist-push")]


def test_initialization_happens_at_most_once_per_process(client, monkeypatch):
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_JSON", '{"type": "service_account"}')
    monkeypatch.setattr("config.Config.FIREBASE_CREDENTIALS_PATH", None)

    fake_app = object()
    monkeypatch.setattr(
        "services.push_notification_service.credentials.Certificate", lambda info: object()
    )
    init_calls = []
    monkeypatch.setattr(
        "services.push_notification_service.firebase_admin.initialize_app",
        lambda cred, name=None: init_calls.append(1) or fake_app,
    )

    is_configured()
    is_configured()
    is_configured()

    assert len(init_calls) == 1


# --- send_push_notification ---

def test_send_with_no_registered_devices_is_a_safe_no_op(client, user, fake_push):
    user_id, _headers = user
    result = send_push_notification(user_id, "Title", "Body")
    assert result == {"attempted": 0, "delivered": 0, "removed_tokens": 0}
    assert fake_push.calls == []


def test_send_delivers_to_all_registered_devices(client, auth_headers, user, fake_push):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-a", platform="ios")
    register_device_token(client, auth_headers, token="tok-b", platform="android")

    result = send_push_notification(user_id, "Reminder", "Check your subscriptions", data={"type": "reminder", "reminder_id": 5})
    assert result == {"attempted": 2, "delivered": 2, "removed_tokens": 0}

    assert len(fake_push.calls) == 1
    call = fake_push.calls[0]
    assert set(call["tokens"]) == {"tok-a", "tok-b"}
    assert call["title"] == "Reminder"
    assert call["body"] == "Check your subscriptions"
    # FCM data payload values are always strings.
    assert call["data"] == {"type": "reminder", "reminder_id": "5"}


def test_send_removes_invalid_tokens_but_still_delivers_to_valid_ones(client, auth_headers, user, fake_push):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="dead-token", platform="ios")
    register_device_token(client, auth_headers, token="good-token", platform="android")
    fake_push.invalid_tokens = {"dead-token"}

    result = send_push_notification(user_id, "Title", "Body")
    assert result == {"attempted": 2, "delivered": 1, "removed_tokens": 1}

    remaining = DeviceToken.query.filter_by(user_id=user_id).all()
    assert [t.token for t in remaining] == ["good-token"]


def test_send_raises_push_unavailable_when_fcm_request_fails_entirely(client, auth_headers, user, fake_push):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-a", platform="ios")
    fake_push.unavailable = True

    with pytest.raises(PushNotificationUnavailable):
        send_push_notification(user_id, "Title", "Body")

    # The token is untouched — a whole-request failure says nothing
    # about whether any individual token is invalid.
    assert DeviceToken.query.filter_by(token="tok-a").first() is not None


def test_send_multicast_never_exposes_a_raw_firebase_exception(client, monkeypatch):
    """Exercises the real `_send_multicast` (not the fake_push double)
    to confirm it wraps a genuine FirebaseError from the SDK into a
    safe PushNotificationUnavailable, rather than letting the original
    message/details reach the caller."""
    from firebase_admin.exceptions import FirebaseError

    monkeypatch.setattr(push_notification_service, "_get_app", lambda: object())

    def _raise(*args, **kwargs):
        raise FirebaseError("INTERNAL", "raw internal detail: project=secret-project-123")

    monkeypatch.setattr(
        push_notification_service.messaging, "send_each_for_multicast", _raise
    )

    try:
        push_notification_service._send_multicast(["tok"], "Title", "Body", {})
        assert False, "expected PushNotificationUnavailable"
    except PushNotificationUnavailable as exc:
        assert "secret-project-123" not in str(exc)
