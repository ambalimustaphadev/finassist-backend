from extensions import db
from services.notification_service import create_notification, notify_user
from tests.conftest import register_device_token


def test_empty_notifications_by_default(client, auth_headers):
    response = client.get("/api/notifications", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["items"] == []
    assert body["pagination"]["total"] == 0


def test_mark_notification_read(client, app, auth_headers, user):
    user_id, _ = user
    with app.app_context():
        notification = create_notification(user_id, "document_notification", "Test notification")
        db.session.commit()
        notification_id = notification.id

    response = client.patch(f"/api/notifications/{notification_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["read"] is True


def test_mark_all_read(client, app, auth_headers, user):
    user_id, _ = user
    with app.app_context():
        create_notification(user_id, "document_notification", "One")
        create_notification(user_id, "document_notification", "Two")
        db.session.commit()

    response = client.patch("/api/notifications/read-all", headers=auth_headers)
    assert response.status_code == 200

    list_response = client.get("/api/notifications", headers=auth_headers)
    assert all(item["read"] for item in list_response.get_json()["items"])


def test_notification_ownership_enforced(client, app, auth_headers, other_auth_headers, other_user):
    other_user_id, _ = other_user
    with app.app_context():
        notification = create_notification(other_user_id, "document_notification", "Not yours")
        db.session.commit()
        notification_id = notification.id

    response = client.patch(f"/api/notifications/{notification_id}", headers=auth_headers)
    assert response.status_code == 404


# --- notify_user: create-then-push orchestration ---

def test_notify_user_creates_notification_with_no_devices_registered(app, user, fake_push):
    user_id, _headers = user
    with app.app_context():
        notification = notify_user(user_id, "reminder", "Check your subscriptions")
        assert notification.id is not None
        assert notification.title == "Check your subscriptions"
    assert fake_push.calls == []


def test_notify_user_attempts_push_to_registered_devices(app, client, auth_headers, user, fake_push):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-1", platform="ios")

    with app.app_context():
        notify_user(
            user_id, "reminder", "Review subscriptions",
            body="Your monthly review is due.",
            push_data={"type": "reminder", "reminder_id": "42"},
        )

    assert len(fake_push.calls) == 1
    assert fake_push.calls[0]["title"] == "Review subscriptions"
    assert fake_push.calls[0]["data"] == {"type": "reminder", "reminder_id": "42"}


def test_notify_user_keeps_notification_record_when_push_is_unavailable(app, user, fake_push):
    """Push delivery failing must never erase notification history —
    the user must still see this on the FinAssist Notifications screen."""
    user_id, _headers = user
    fake_push.unavailable = True

    with app.app_context():
        notification = notify_user(user_id, "reminder", "Still recorded")
        notification_id = notification.id

    from models import Notification
    with app.app_context():
        assert Notification.query.get(notification_id) is not None


def test_notify_user_keeps_notification_record_even_on_unexpected_push_error(app, client, auth_headers, user, monkeypatch):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-1", platform="ios")

    def _boom(*args, **kwargs):
        raise RuntimeError("unexpected failure deep in the send path")

    monkeypatch.setattr("services.notification_service._send_push_notification", _boom)

    with app.app_context():
        notification = notify_user(user_id, "reminder", "Still recorded")
        notification_id = notification.id

    from models import Notification
    with app.app_context():
        assert Notification.query.get(notification_id) is not None


def test_notify_user_notification_appears_in_the_api(client, auth_headers, app, user, fake_push):
    user_id, _headers = user
    with app.app_context():
        notify_user(user_id, "reminder", "Api visible notification")

    response = client.get("/api/notifications", headers=auth_headers)
    titles = [item["title"] for item in response.get_json()["items"]]
    assert "Api visible notification" in titles
