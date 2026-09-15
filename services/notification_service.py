import json

from extensions import db
from models import Notification


def notification_to_dict(notification):
    metadata = None
    if notification.notification_metadata:
        try:
            metadata = json.loads(notification.notification_metadata)
        except (TypeError, ValueError):
            metadata = None
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
    """Not exposed over the API — notifications are only ever created by
    backend logic that has a real event to report. No such trigger exists
    yet in this phase, so this exists for future use rather than being
    dead code: the model, serializer, and read/unread endpoints are ready
    for whichever service starts calling this first."""
    notification = Notification(
        user_id=user_id,
        type=type_,
        title=title,
        body=body,
        notification_metadata=json.dumps(metadata) if metadata is not None else None,
    )
    db.session.add(notification)
    return notification


def mark_read(notification):
    notification.read = True
    db.session.commit()
    return notification


def mark_all_read(user_id):
    Notification.query.filter_by(user_id=user_id, read=False).update({"read": True})
    db.session.commit()
