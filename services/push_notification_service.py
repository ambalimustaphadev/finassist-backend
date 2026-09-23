"""Firebase Cloud Messaging delivery.

This is the ONLY module in the codebase that imports `firebase_admin`.
Everything else that wants to push a notification to a user's devices
(the reminder delivery worker, notification_service.notify_user) calls
`send_push_notification()` here — never the Firebase SDK directly.

Firebase Admin is initialized at most once per process, lazily, on
first use — not on every send. If no credentials are configured (see
`config.Config.FIREBASE_CREDENTIALS_JSON` / `FIREBASE_CREDENTIALS_PATH`),
initialization is skipped entirely: push notifications are disabled,
not a crash, and every other feature (chat, subscriptions, reminders,
notification history) keeps working normally. Sending in that state
raises `PushNotificationUnavailable`, which callers convert into a safe
structured error rather than ever exposing a raw Firebase exception.

Tests never touch real Firebase: they monkeypatch `_send_multicast`
(see tests/conftest.py's `fake_push_notifications` fixture) rather than
mocking the SDK internals.
"""
import json
import logging
import threading

import firebase_admin
from firebase_admin import credentials, messaging
from firebase_admin.exceptions import FirebaseError

from config import Config
from services import device_token_service

logger = logging.getLogger(__name__)

_APP_NAME = "finassist-push"
_init_lock = threading.Lock()
_app = None
_init_attempted = False


class PushNotificationUnavailable(Exception):
    """Raised when a push send can't be attempted at all: Firebase
    Admin isn't configured, failed to initialize, or the whole request
    to FCM failed (auth/network) rather than one specific bad token.
    Never let the original cause reach an API response — see
    notification_routes.py / reminder_delivery_service.py for how this
    is converted into a safe structured error."""


def _load_credential():
    """Builds a Firebase credential from config, or returns None if
    nothing (or nothing valid) is configured. Never raises — a bad
    value here means push is disabled, not that the app fails to boot."""
    if Config.FIREBASE_CREDENTIALS_JSON:
        try:
            info = json.loads(Config.FIREBASE_CREDENTIALS_JSON)
        except (TypeError, ValueError):
            logger.error(
                "FIREBASE_CREDENTIALS_JSON is not valid JSON; push notifications disabled."
            )
            return None
        try:
            return credentials.Certificate(info)
        except ValueError:
            logger.exception(
                "FIREBASE_CREDENTIALS_JSON is not a valid service account; "
                "push notifications disabled."
            )
            return None

    if Config.FIREBASE_CREDENTIALS_PATH:
        try:
            return credentials.Certificate(Config.FIREBASE_CREDENTIALS_PATH)
        except (ValueError, IOError):
            logger.exception(
                "Could not load the Firebase credentials file at %s; "
                "push notifications disabled.",
                Config.FIREBASE_CREDENTIALS_PATH,
            )
            return None

    return None


def _get_app():
    """Returns the initialized Firebase app, or None if push isn't
    configured or failed to initialize. Initializes at most once per
    process: a skipped or failed attempt is not retried on every call,
    so a misconfigured deployment doesn't pay the cost (or spam the
    logs) once per notification."""
    global _app, _init_attempted

    if _app is not None:
        return _app
    if _init_attempted:
        return None

    with _init_lock:
        if _app is not None:
            return _app
        if _init_attempted:
            return None
        _init_attempted = True

        cred = _load_credential()
        if cred is None:
            logger.warning(
                "Firebase Admin credentials not configured; push notifications are disabled."
            )
            return None

        try:
            _app = firebase_admin.initialize_app(cred, name=_APP_NAME)
        except ValueError:
            # An app with this name already exists (e.g. re-initialized
            # within the same process) — reuse it rather than treating
            # that as a failure.
            _app = firebase_admin.get_app(name=_APP_NAME)
        except Exception:
            logger.exception("Failed to initialize Firebase Admin SDK.")
            _app = None

        return _app


def is_configured():
    """Whether push notification delivery is available in this process.
    Not required before calling send_push_notification (which already
    fails safely) — useful for diagnostics/health checks."""
    return _get_app() is not None


def _send_multicast(tokens, title, body, data):
    """The one place that actually calls the Firebase SDK. Kept
    separate from send_push_notification so tests can monkeypatch just
    this function with a fake, without needing to mock the SDK itself
    or the device-token lookup/cleanup around it."""
    app = _get_app()
    if app is None:
        raise PushNotificationUnavailable("Push notification delivery is not configured.")

    message = messaging.MulticastMessage(
        tokens=list(tokens),
        notification=messaging.Notification(title=title, body=body),
        data=data,
    )

    try:
        return messaging.send_each_for_multicast(message, app=app)
    except FirebaseError as exc:
        logger.exception("Firebase Admin SDK rejected the send request.")
        raise PushNotificationUnavailable("Push notification delivery failed.") from exc


def _is_invalid_token_error(exc):
    """True if `exc` (a SendResponse.exception from the SDK) means this
    specific token is permanently dead and should stop being used — as
    opposed to a transient failure that says nothing about the token's
    validity (e.g. a quota error, which should be retried later, not
    used to delete someone's device registration)."""
    if isinstance(exc, messaging.UnregisteredError):
        return True
    code = getattr(exc, "code", None)
    return code in {"UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND"}


def send_push_notification(user_id, title, body, data=None):
    """Sends one push notification to every device currently registered
    to `user_id`.

    Best-effort and multi-device: a dead token for one of the user's
    devices never blocks delivery to their other devices, and is
    removed automatically (see device_token_service.deactivate_tokens)
    so it stops being tried on every future notification.

    `data` becomes the FCM data payload; every value is coerced to a
    string (FCM requires string values). Keep it to small, non-
    sensitive identifiers (e.g. {"type": "reminder", "reminder_id":
    "123"}) — never put financial figures or free-text content into it
    that a notification-tray preview shouldn't reveal.

    Returns a summary dict: {"attempted", "delivered", "removed_tokens"}.
    Having zero registered devices, or some/all tokens being invalid,
    are normal outcomes and never raise. Raises
    PushNotificationUnavailable only when delivery couldn't be
    attempted at all (not configured, or the whole FCM request failed)
    — callers must catch this and convert it to a safe structured
    error, never let it propagate to an API response.
    """
    tokens = device_token_service.list_active_tokens(user_id)
    if not tokens:
        return {"attempted": 0, "delivered": 0, "removed_tokens": 0}

    string_data = {str(key): str(value) for key, value in (data or {}).items()}

    response = _send_multicast(tokens, title, body, string_data)

    invalid_tokens = []
    for token, result in zip(tokens, response.responses):
        if result.success:
            continue
        if _is_invalid_token_error(result.exception):
            invalid_tokens.append(token)
        else:
            logger.warning(
                "FCM send failed for a device token (kept — not an "
                "invalid-token error): %r",
                getattr(result.exception, "code", type(result.exception).__name__),
            )

    if invalid_tokens:
        device_token_service.deactivate_tokens(invalid_tokens)

    logger.info(
        "Push notification sent user_id=%s attempted=%s delivered=%s removed_tokens=%s",
        user_id, len(tokens), response.success_count, len(invalid_tokens),
    )

    return {
        "attempted": len(tokens),
        "delivered": response.success_count,
        "removed_tokens": len(invalid_tokens),
    }
