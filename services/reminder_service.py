"""Business logic for reminders — FinAssist's own lightweight
subsystem (there was no existing reminder infrastructure to reuse; see
`models.Reminder`). Mirrors the shape of `subscription_service.py` so
the rest of the app stays consistent: validation + persistence live
here, callers (the AI tool adapter in `services/ai_tools/reminders.py`)
never touch the database directly.
"""
from datetime import datetime, timezone

from extensions import db
from models import Reminder
from utils import ValidationError, require_non_empty_string

STATUSES = {"active", "completed", "cancelled"}


def _require_remind_at(value):
    """Parses `remind_at` as an ISO-8601 datetime with an explicit UTC
    offset and returns it converted to a naive UTC datetime for storage.

    A bare local time (no offset) is deliberately rejected rather than
    silently treated as UTC — the caller (the AI) is expected to ask the
    user for their timezone/local time when it's ambiguous instead of
    guessing, per FinAssist's tool-use policy.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("remind_at is required.", {"remind_at": "required"})

    raw = value.strip()
    # datetime.fromisoformat accepts "+00:00" but not the "Z" shorthand
    # on all supported Python versions, so normalize it first.
    normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValidationError(
            "remind_at must be an ISO-8601 datetime with an explicit UTC "
            "offset, e.g. '2026-09-23T09:00:00+01:00' or "
            "'2026-09-23T08:00:00Z'.",
            {"remind_at": "invalid"},
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(
            "remind_at must include a UTC offset so the reminder time "
            "isn't ambiguous, e.g. '2026-09-23T09:00:00+01:00'.",
            {"remind_at": "missing_offset"},
        )

    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def reminder_to_dict(reminder):
    return {
        "id": reminder.id,
        "title": reminder.title,
        "description": reminder.description,
        "remind_at": reminder.remind_at.replace(tzinfo=timezone.utc).isoformat(),
        "status": reminder.status,
        "created_at": reminder.created_at.isoformat() + "Z",
        "updated_at": reminder.updated_at.isoformat() + "Z",
    }


def create_reminder(user_id, data):
    title = require_non_empty_string(data.get("title"), "title", 120)
    remind_at = _require_remind_at(data.get("remind_at"))

    description_value = data.get("description")
    description = (
        require_non_empty_string(description_value, "description", 500)
        if description_value
        else None
    )

    reminder = Reminder(
        user_id=user_id,
        title=title,
        description=description,
        remind_at=remind_at,
        status="active",
    )
    db.session.add(reminder)
    db.session.commit()
    return reminder


def list_reminders(user_id, status=None):
    query = Reminder.query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Reminder.remind_at.asc(), Reminder.id.asc()).all()


def delete_reminder(reminder):
    db.session.delete(reminder)
    db.session.commit()
