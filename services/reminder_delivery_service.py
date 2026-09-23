"""Reminder -> notification delivery: the "reminder scheduler" business
logic in this architecture:

    Reminder database
        v
    Reminder scheduler/worker        (this module: deliver_due_reminders)
        v
    NotificationService               (services.notification_service.notify_user)
        v
    Notification database record + Firebase Cloud Messaging

This module never decides WHEN to run — it has no loop, no timer, and
is not imported by app.py. Something outside the Flask
request-handling process triggers `deliver_due_reminders()` on a
schedule:

- production: the `flask deliver-due-reminders` CLI command (see
  server/__init__.py) invoked periodically by an external scheduler —
  OS cron, a platform "scheduled job" (Heroku Scheduler, Render/Railway
  cron, a Kubernetes CronJob, etc.). This is the supported production
  path; see the final report for the exact cron line.
- local development only: scripts/dev_reminder_worker.py, a standalone
  process (never run inside the Flask app/web workers) that just calls
  the same CLI command in a loop.

Reuses `services.reminder_service` for nothing but the `Reminder`
model's schema (it doesn't touch that module's create/list/delete
functions — those stay exactly as the AI tool layer uses them) and
`services.notification_service.notify_user` for the create-then-push
step, so this module owns no notification/FCM logic of its own.
"""
import logging
from datetime import datetime, timezone

from extensions import db
from models import Reminder
from services.notification_service import notify_user

logger = logging.getLogger(__name__)


def _due_reminder_ids(now):
    """Ids of reminders that are due and not yet claimed. Read-only —
    the actual claim happens per-row in `_claim`, so two overlapping
    runs that both see the same id here can still never both process
    it (see `_claim`)."""
    rows = (
        Reminder.query
        .filter(
            Reminder.status == "active",
            Reminder.remind_at <= now,
            Reminder.notified_at.is_(None),
        )
        .order_by(Reminder.remind_at.asc(), Reminder.id.asc())
        .with_entities(Reminder.id)
        .all()
    )
    return [row.id for row in rows]


def _claim(reminder_id, now):
    """Atomically claims one reminder for delivery via a single
    conditional UPDATE that only matches if `notified_at` is still
    NULL. This — not `status` — is what makes delivery idempotent: if
    `deliver_due_reminders` runs twice (overlapping cron ticks, a
    retried job, two worker processes), only one run's UPDATE can ever
    match the WHERE clause, so a reminder is claimed, and therefore
    notified, at most once no matter how many processes race on it.

    Returns the claimed Reminder, or None if some other run claimed it
    first between `_due_reminder_ids` listing it and this call.
    """
    claimed = (
        db.session.query(Reminder)
        .filter(Reminder.id == reminder_id, Reminder.notified_at.is_(None))
        .update({"notified_at": now}, synchronize_session=False)
    )
    db.session.commit()
    if claimed == 0:
        return None
    return Reminder.query.get(reminder_id)


def deliver_due_reminders(now=None):
    """Delivers every reminder currently due and not yet notified.

    Safe to call repeatedly, and safe under concurrent/overlapping
    calls (see `_claim`) — this is the single function a scheduler
    should invoke on a tick.

    For each due reminder: claim it, then create its Notification
    history row and attempt an FCM push via
    `services.notification_service.notify_user` (which already
    guarantees a push failure never loses the notification history),
    then mark the reminder `completed`. If creating that notification
    itself raises (a genuine unexpected failure, not a push failure —
    notify_user already isolates those), the reminder is deliberately
    left claimed but NOT marked completed: it will never be retried
    automatically (the claim already prevents that), trading a very
    rare silent miss for the guarantee that a reminder is never
    delivered twice, which is the stated priority for this system.

    `now`, if given, must be a naive datetime representing UTC —
    matching `Reminder.remind_at`'s storage convention (see
    services.reminder_service) — never a timezone-aware datetime; the
    two are never compared against each other. Defaults to the current
    time in UTC.

    Returns {"due": <found>, "delivered": <successfully processed>}.
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

    due_ids = _due_reminder_ids(now)
    delivered = 0

    for reminder_id in due_ids:
        reminder = _claim(reminder_id, now)
        if reminder is None:
            continue  # claimed by a concurrent run

        try:
            notify_user(
                reminder.user_id,
                "reminder",
                reminder.title,
                body=reminder.description,
                metadata={"reminder_id": reminder.id},
                push_data={"type": "reminder", "reminder_id": str(reminder.id)},
            )
        except Exception:
            logger.exception(
                "Failed to record notification for reminder_id=%s — left "
                "claimed but not completed; will not be retried "
                "automatically to avoid duplicate delivery.",
                reminder.id,
            )
            continue

        reminder.status = "completed"
        db.session.commit()
        delivered += 1

    logger.info("Reminder delivery run: due=%s delivered=%s", len(due_ids), delivered)
    return {"due": len(due_ids), "delivered": delivered}
