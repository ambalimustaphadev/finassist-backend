"""Tests for services/reminder_delivery_service.py — the reminder
"scheduler" business logic: which reminders are due, that a reminder is
never delivered twice, and that Notification history survives a push
failure. Never touches a real scheduler/cron — deliver_due_reminders()
is called directly, exactly as the `flask deliver-due-reminders` CLI
command and scripts/dev_reminder_worker.py both do.
"""
from datetime import datetime, timedelta

from models import Notification, Reminder
from services.reminder_delivery_service import deliver_due_reminders
from tests.conftest import register_device_token


def _create_reminder(app, user_id, remind_at, title="Test reminder", status="active"):
    with app.app_context():
        reminder = Reminder(
            user_id=user_id, title=title, remind_at=remind_at, status=status,
        )
        from extensions import db
        db.session.add(reminder)
        db.session.commit()
        return reminder.id


def test_due_reminder_is_delivered(app, user, fake_push):
    user_id, _headers = user
    past = datetime.utcnow() - timedelta(minutes=5)
    reminder_id = _create_reminder(app, user_id, past)

    with app.app_context():
        summary = deliver_due_reminders(now=datetime.utcnow())
        assert summary == {"due": 1, "delivered": 1}

        reminder = Reminder.query.get(reminder_id)
        assert reminder.status == "completed"
        assert reminder.notified_at is not None

        notifications = Notification.query.filter_by(user_id=user_id).all()
        assert len(notifications) == 1
        assert notifications[0].type == "reminder"


def test_future_reminder_is_not_delivered(app, user, fake_push):
    user_id, _headers = user
    future = datetime.utcnow() + timedelta(days=1)
    reminder_id = _create_reminder(app, user_id, future)

    with app.app_context():
        summary = deliver_due_reminders(now=datetime.utcnow())
        assert summary == {"due": 0, "delivered": 0}

        reminder = Reminder.query.get(reminder_id)
        assert reminder.status == "active"
        assert reminder.notified_at is None
        assert Notification.query.filter_by(user_id=user_id).count() == 0


def test_cancelled_reminder_is_not_delivered(app, user, fake_push):
    user_id, _headers = user
    past = datetime.utcnow() - timedelta(minutes=5)
    _create_reminder(app, user_id, past, status="cancelled")

    with app.app_context():
        summary = deliver_due_reminders(now=datetime.utcnow())
        assert summary == {"due": 0, "delivered": 0}
        assert Notification.query.filter_by(user_id=user_id).count() == 0


def test_reminder_is_never_delivered_twice(app, user, fake_push):
    """The central guarantee: running the delivery job twice (e.g. an
    overlapping cron tick) must not send the same reminder's
    notification/push a second time."""
    user_id, _headers = user
    past = datetime.utcnow() - timedelta(minutes=5)
    _create_reminder(app, user_id, past)

    with app.app_context():
        first = deliver_due_reminders(now=datetime.utcnow())
        second = deliver_due_reminders(now=datetime.utcnow())

    assert first == {"due": 1, "delivered": 1}
    assert second == {"due": 0, "delivered": 0}

    with app.app_context():
        assert Notification.query.filter_by(user_id=user_id).count() == 1
    assert len(fake_push.calls) == 0  # no devices registered in this test — see push test below


def test_reminder_is_never_delivered_twice_including_push(app, client, auth_headers, user, fake_push):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-1", platform="ios")
    past = datetime.utcnow() - timedelta(minutes=5)
    _create_reminder(app, user_id, past)

    with app.app_context():
        deliver_due_reminders(now=datetime.utcnow())
        deliver_due_reminders(now=datetime.utcnow())

    assert len(fake_push.calls) == 1


def test_notification_record_created_even_when_push_unavailable(app, user, fake_push):
    """FCM failure must not erase notification history — the reminder
    must still show up on the FinAssist Notifications screen."""
    user_id, _headers = user
    fake_push.unavailable = True
    past = datetime.utcnow() - timedelta(minutes=5)
    reminder_id = _create_reminder(app, user_id, past)

    with app.app_context():
        summary = deliver_due_reminders(now=datetime.utcnow())
        assert summary == {"due": 1, "delivered": 1}

        assert Notification.query.filter_by(user_id=user_id).count() == 1
        reminder = Reminder.query.get(reminder_id)
        assert reminder.status == "completed"


def test_multiple_due_reminders_each_get_their_own_notification(app, user, fake_push):
    user_id, _headers = user
    past = datetime.utcnow() - timedelta(minutes=5)
    _create_reminder(app, user_id, past, title="First")
    _create_reminder(app, user_id, past, title="Second")

    with app.app_context():
        summary = deliver_due_reminders(now=datetime.utcnow())
        assert summary == {"due": 2, "delivered": 2}
        titles = {n.title for n in Notification.query.filter_by(user_id=user_id).all()}
        assert titles == {"First", "Second"}


def test_reminder_notification_includes_reminder_id_in_push_data(app, client, auth_headers, user, fake_push):
    user_id, _headers = user
    register_device_token(client, auth_headers, token="tok-1", platform="ios")
    past = datetime.utcnow() - timedelta(minutes=5)
    reminder_id = _create_reminder(app, user_id, past)

    with app.app_context():
        deliver_due_reminders(now=datetime.utcnow())

    assert fake_push.calls[0]["data"] == {"type": "reminder", "reminder_id": str(reminder_id)}


def test_delivery_is_scoped_to_the_reminders_own_user(app, user, other_user, fake_push):
    user_id, _headers = user
    other_id, _other_headers = other_user
    past = datetime.utcnow() - timedelta(minutes=5)
    _create_reminder(app, other_id, past, title="Theirs")

    with app.app_context():
        deliver_due_reminders(now=datetime.utcnow())
        assert Notification.query.filter_by(user_id=user_id).count() == 0
        assert Notification.query.filter_by(user_id=other_id).count() == 1
