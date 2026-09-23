"""Device token registration for push notifications (FCM).

Mirrors the shape of `subscription_service.py` / `reminder_service.py`:
validation and persistence live here, callers (notification_routes.py,
push_notification_service.py) never touch `DeviceToken` directly.

A token belongs to whichever user most recently registered it, not
permanently to whichever user registered it first — see
`register_device_token` below for why.
"""
from datetime import datetime

from extensions import db
from models import DeviceToken
from utils import ValidationError, require_non_empty_string

PLATFORMS = {"ios", "android"}
MAX_TOKEN_LENGTH = 1024


def _require_platform(value):
    if value not in PLATFORMS:
        raise ValidationError(
            f"'{value}' is not a valid platform.",
            {"platform": f"must be one of {sorted(PLATFORMS)}"},
        )
    return value


def device_token_to_dict(device_token):
    # Deliberately never includes the raw token: it's a write-only
    # secret the client already holds, and the API response is only
    # ever used to confirm registration succeeded.
    return {
        "id": device_token.id,
        "platform": device_token.platform,
        "created_at": device_token.created_at.isoformat() + "Z",
        "updated_at": device_token.updated_at.isoformat() + "Z",
        "last_seen_at": device_token.last_seen_at.isoformat() + "Z",
    }


def register_device_token(user_id, data):
    """Creates or reassigns a device token to `user_id`.

    FCM tokens are scoped to one app install on one device, not
    permanently to one account: if a different user logs into the same
    physical device (or the same user reinstalls and gets a token that,
    astronomically unlikely as it is, happens to already exist), the
    existing row is reassigned to the newly authenticated user rather
    than left pointing at whoever registered it first. `token` has a
    database-level UNIQUE constraint, so this is also what keeps a
    token from ever being duplicated across rows.
    """
    token = require_non_empty_string(data.get("token"), "token", MAX_TOKEN_LENGTH)
    platform = _require_platform(data.get("platform"))

    now = datetime.utcnow()
    existing = DeviceToken.query.filter_by(token=token).first()

    if existing is not None:
        existing.user_id = user_id
        existing.platform = platform
        existing.last_seen_at = now
        db.session.commit()
        return existing

    device_token = DeviceToken(
        user_id=user_id,
        token=token,
        platform=platform,
        last_seen_at=now,
    )
    db.session.add(device_token)
    db.session.commit()
    return device_token


def delete_device_token(user_id, token):
    """Removes one device token, scoped to `user_id` — a token belonging
    to another user is treated as not found, never deleted. Returns
    True if a row was removed, False if nothing matched."""
    device_token = DeviceToken.query.filter_by(user_id=user_id, token=token).first()
    if device_token is None:
        return False
    db.session.delete(device_token)
    db.session.commit()
    return True


def list_active_tokens(user_id):
    """Every registered device token for a user, newest-registered
    first. There's currently no separate "deactivated" state — a token
    Firebase reports as invalid is deleted outright (see
    push_notification_service.deactivate_tokens), so every row here is
    implicitly active."""
    return [
        dt.token
        for dt in DeviceToken.query.filter_by(user_id=user_id)
        .order_by(DeviceToken.created_at.desc())
        .all()
    ]


def deactivate_tokens(tokens):
    """Removes device tokens Firebase has reported as invalid/
    unregistered — called by push_notification_service after a send,
    never by an API route. Safe to call with tokens that don't belong
    to any single user's request context, since this only ever runs
    from the trusted server side with tokens FCM itself just rejected."""
    if not tokens:
        return
    DeviceToken.query.filter(DeviceToken.token.in_(list(tokens))).delete(
        synchronize_session=False
    )
    db.session.commit()
