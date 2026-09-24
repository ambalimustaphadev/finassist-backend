import json

from extensions import db
from models import Activity
from utils import ValidationError, require_non_empty_string, safe_json_loads

# Types services are allowed to log automatically. Kept explicit so a
# typo in a `type` string doesn't silently create a garbage activity row.
INTERNAL_TYPES = {
    "document_uploaded",
    "document_deleted",
    "profile_updated",
    "preferences_updated",
}

# Types the client itself may log directly. The currency convert
# endpoint doesn't write activity itself, so the app logs a completed
# conversion here. Historical rows of any older type stay readable —
# only new writes are restricted to this set.
CLIENT_LOGGABLE_TYPES = {
    "currency_conversion",
}

ALL_TYPES = INTERNAL_TYPES | CLIENT_LOGGABLE_TYPES


def log_activity(user_id, type_, title, description=None, metadata=None):
    activity = Activity(
        user_id=user_id,
        type=type_,
        title=title,
        description=description,
        activity_metadata=json.dumps(metadata) if metadata is not None else None,
    )
    db.session.add(activity)
    return activity


def record_client_activity(user_id, type_, title, description=None, metadata=None):
    """Logs and commits an activity reported directly by the client
    (a completed currency conversion, etc). Only the
    client-loggable types are accepted, so this can never be used to
    forge a server-side event like `goal_created`."""
    if type_ not in CLIENT_LOGGABLE_TYPES:
        raise ValidationError(
            f"'{type_}' is not a loggable activity type.",
            {"type": f"must be one of {sorted(CLIENT_LOGGABLE_TYPES)}"},
        )

    title = require_non_empty_string(title, "title", 120)

    activity = log_activity(user_id, type_, title, description, metadata)
    db.session.commit()
    return activity


def list_activity(user_id):
    return Activity.query.filter_by(user_id=user_id).order_by(Activity.created_at.desc())


def activity_to_dict(activity):
    metadata = safe_json_loads(activity.activity_metadata)
    return {
        "id": activity.id,
        "type": activity.type,
        "title": activity.title,
        "description": activity.description,
        "metadata": metadata,
        "created_at": activity.created_at.isoformat() + "Z",
        "read_at": activity.read_at.isoformat() + "Z" if activity.read_at else None,
    }
