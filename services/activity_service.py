import json

from extensions import db
from models import Activity

# Types services are allowed to log automatically. Kept explicit so a
# typo in a `type` string doesn't silently create a garbage activity row.
INTERNAL_TYPES = {
    "document_uploaded",
    "document_deleted",
    "profile_updated",
    "preferences_updated",
}

# Types the client itself may log directly (calculators run entirely on
# the frontend, so the backend has no other way to know they happened).
CLIENT_LOGGABLE_TYPES = {
    "currency_conversion",
    "loan_calculation",
    "savings_calculation",
    "affordability_calculation",
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


def activity_to_dict(activity):
    metadata = None
    if activity.activity_metadata:
        try:
            metadata = json.loads(activity.activity_metadata)
        except (TypeError, ValueError):
            metadata = None
    return {
        "id": activity.id,
        "type": activity.type,
        "title": activity.title,
        "description": activity.description,
        "metadata": metadata,
        "created_at": activity.created_at.isoformat() + "Z",
        "read_at": activity.read_at.isoformat() + "Z" if activity.read_at else None,
    }
