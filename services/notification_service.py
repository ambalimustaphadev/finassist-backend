import json
import logging

from extensions import db
from models import Notification
from services.push_notification_service import PushNotificationUnavailable
from services.push_notification_service import send_push_notification as _send_push_notification
from utils import safe_json_loads

logger = logging.getLogger(__name__)


def list_notifications(user_id):
    return Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc())


def notification_to_dict(notification):
    metadata = safe_json_loads(notification.notification_metadata)
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "read": notification.read,
        "metadata": metadata,
        "created_at": notification.created_at.isoformat() + "Z",
    }


def create_notification(user_id, type_, title, body=None, metadata=None):
    """Not exposed over the API directly — notifications are only ever
    created by backend logic that has a real event to report. Callers:
    `notify_user` below (create-then-push), and anything that wants
    in-app notification history without a push attempt. Does not
    commit — the caller controls the transaction."""
    notification = Notification(
        user_id=user_id,
        type=type_,
        title=title,
        body=body,
        notification_metadata=json.dumps(metadata) if metadata is not None else None,
    )
    db.session.add(notification)
    return notification


def notify_user(user_id, type_, title, body=None, metadata=None, push_data=None):
    """Records a Notification (in-app history) and then attempts an FCM
    push to the user's registered devices — in that order, and as two
    separate concerns.

    The Notification row is created and committed FIRST, unconditionally.
    Push delivery is attempted after and is fully best-effort: if
    Firebase isn't configured, if every device token is stale, or if
    the whole FCM request fails, the exception is caught here and only
    logged — it never propagates, and the Notification row this
    function just committed is never rolled back or removed. A user
    must always be able to see this notification on the FinAssist
    Notifications screen, whether or not the push itself was delivered.

    `push_data` becomes the FCM data payload (see
    push_notification_service.send_push_notification) — keep it to
    small, non-sensitive identifiers; it is independent of `metadata`,
    which is only ever returned through the in-app notifications API.

    Returns the created Notification (already committed).
    """
    notification = create_notification(user_id, type_, title, body=body, metadata=metadata)
    db.session.commit()

    try:
        _send_push_notification(user_id, title, body or "", data=push_data)
    except PushNotificationUnavailable:
        logger.warning(
            "Push delivery unavailable for notification_id=%s user_id=%s",
            notification.id, user_id,
        )
    except Exception:
        # Defense in depth: push delivery must never be able to take
        # down the caller (a reminder delivery run, a future
        # subscription-renewal notifier, etc.) or undo the notification
        # history record above, no matter what goes wrong underneath.
        logger.exception(
            "Unexpected error sending push for notification_id=%s user_id=%s",
            notification.id, user_id,
        )

    return notification


def mark_read(notification):
    notification.read = True
    db.session.commit()
    return notification


def mark_all_read(user_id):
    Notification.query.filter_by(user_id=user_id, read=False).update({"read": True})
    db.session.commit()
