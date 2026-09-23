"""AI-tool adapters for reminders.

Delegates persistence and validation to `services.reminder_service` /
`models.Reminder` (FinAssist's own small reminder subsystem — there was
no pre-existing reminder infrastructure to reuse). This module only
translates tool-call arguments into that service's calls and enforces
that every read/delete is scoped to the authenticated `user_id`.
"""
from models import Reminder
from services.reminder_service import STATUSES
from services.reminder_service import create_reminder as _create_reminder
from services.reminder_service import delete_reminder as _delete_reminder
from services.reminder_service import list_reminders as _list_reminders
from services.reminder_service import reminder_to_dict
from utils import ValidationError, get_owned

from .common import require_positive_int_arg
from .errors import ToolError, from_validation_error


def create_reminder(user_id, arguments):
    data = {
        "title": arguments.get("title"),
        "remind_at": arguments.get("remind_at"),
        "description": arguments.get("description"),
    }
    try:
        reminder = _create_reminder(user_id, data)
    except ValidationError as exc:
        raise from_validation_error(exc)
    return {"reminder": reminder_to_dict(reminder)}


def list_reminders(user_id, arguments):
    status = arguments.get("status")
    if status is not None and status not in STATUSES:
        raise ToolError("INVALID_ARGUMENTS", f"status must be one of {sorted(STATUSES)}.")
    reminders = _list_reminders(user_id, status=status)
    return {"reminders": [reminder_to_dict(r) for r in reminders]}


def delete_reminder(user_id, arguments):
    reminder_id = require_positive_int_arg(arguments.get("reminder_id"), "reminder_id")
    reminder = get_owned(Reminder, reminder_id, user_id)
    if reminder is None:
        raise ToolError(
            "REMINDER_NOT_FOUND",
            "No reminder with that id was found for this user.",
        )
    deleted = reminder_to_dict(reminder)
    _delete_reminder(reminder)
    return {"deleted": True, "reminder": deleted}
