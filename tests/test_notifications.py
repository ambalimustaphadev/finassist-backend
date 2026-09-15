from extensions import db
from services.notification_service import create_notification


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
