#!/usr/bin/env python
"""DEVELOPMENT ONLY — a simple polling loop for local testing of
reminder delivery, so you don't have to manually run `flask
deliver-due-reminders` (or wait for a real cron entry) every time you
want to see a reminder fire while working on this locally.

Run it as its own separate OS process:

    .venv/bin/python scripts/dev_reminder_worker.py

Do NOT deploy this script, run it inside the Flask app/web process, or
rely on it in production — a real deployment schedules
`flask deliver-due-reminders` externally (cron / a platform scheduled
job / a Kubernetes CronJob). See services/reminder_delivery_service.py
and server/_register_cli_commands for the production path, and the
project's final push-notification report for the exact cron line.

This script is intentionally the only `while True: sleep(...)` in this
codebase, and it is not imported by anything — app.py and server/
never import this module, so it can never end up running inside a
Flask request worker.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POLL_INTERVAL_SECONDS = int(os.environ.get("DEV_REMINDER_WORKER_INTERVAL", "30"))


def main():
    from server import create_app
    from services.reminder_delivery_service import deliver_due_reminders

    app = create_app()

    print(
        f"[dev_reminder_worker] DEVELOPMENT ONLY. Polling every "
        f"{POLL_INTERVAL_SECONDS}s. Press Ctrl+C to stop.",
        flush=True,
    )

    with app.app_context():
        while True:
            try:
                summary = deliver_due_reminders()
                if summary["due"]:
                    print(
                        f"[dev_reminder_worker] due={summary['due']} "
                        f"delivered={summary['delivered']}",
                        flush=True,
                    )
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # pragma: no cover - dev convenience only
                print(f"[dev_reminder_worker] error: {exc}", flush=True)

            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[dev_reminder_worker] stopped.", flush=True)
