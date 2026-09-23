import logging
import os
import uuid
from urllib.parse import urlparse

from extensions import db
from services.activity_service import log_activity
from spaces import delete_object, generate_signed_url, upload_object
from utils import (
    ValidationError,
    require_currency,
    require_enum,
    require_non_empty_string,
    require_number,
)

logger = logging.getLogger(__name__)

EMPLOYMENT_STATUSES = {
    "employed", "self_employed", "unemployed", "student", "retired", "other",
}
INCOME_FREQUENCIES = {"weekly", "biweekly", "monthly", "yearly"}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB

# Short-lived, matching the expiration used for financial-document
# signed URLs elsewhere in the app.
PROFILE_PICTURE_URL_EXPIRATION = 300


def _extract_object_key(stored_value):
    """`User.profile_picture_url` stores an R2 object key going forward
    (e.g. "profile-pictures/12/uuid.jpg"). Rows written before the R2
    bucket's public r2.dev access was disabled may still hold a full
    public URL from that era; recover the key from its path so those
    rows keep working without a data migration."""
    if stored_value.startswith("http://") or stored_value.startswith("https://"):
        return urlparse(stored_value).path.lstrip("/")
    return stored_value


def resolve_profile_picture_url(user):
    """Resolve the user's stored profile-picture reference into a
    short-lived signed URL, or None if they don't have one. Never
    returns the bare object key or a permanent URL."""
    if not user.profile_picture_url:
        return None

    key = _extract_object_key(user.profile_picture_url)

    try:
        return generate_signed_url(key, expires_in=PROFILE_PICTURE_URL_EXPIRATION)
    except Exception:
        logger.exception(
            "Failed to generate signed URL for profile picture user_id=%s",
            user.id,
        )
        return None


def profile_to_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "country": user.country,
        "currency": user.currency,
        "occupation": user.occupation,
        "employment_status": user.employment_status,
        "income": user.income,
        "income_frequency": user.income_frequency,
        "profile_picture_url": resolve_profile_picture_url(user),
        "onboarding_completed": user.onboarding_completed,
        "created_at": user.created_at.isoformat() + "Z",
        "updated_at": user.updated_at.isoformat() + "Z",
    }


def update_profile(user, data):
    changed_fields = []

    if "first_name" in data:
        user.first_name = require_non_empty_string(data["first_name"], "first_name", 80)
        changed_fields.append("first_name")

    if "last_name" in data:
        user.last_name = require_non_empty_string(data["last_name"], "last_name", 80)
        changed_fields.append("last_name")

    if "country" in data:
        value = data["country"]
        user.country = require_non_empty_string(value, "country", 80) if value else None
        changed_fields.append("country")

    if "currency" in data:
        user.currency = require_currency(data["currency"])
        changed_fields.append("currency")

    if "occupation" in data:
        value = data["occupation"]
        user.occupation = require_non_empty_string(value, "occupation", 120) if value else None
        changed_fields.append("occupation")

    if "employment_status" in data:
        value = data["employment_status"]
        user.employment_status = (
            require_enum(value, EMPLOYMENT_STATUSES, "employment_status") if value else None
        )
        changed_fields.append("employment_status")

    if "income" in data:
        user.income = require_number(data["income"], "income", minimum=0, allow_none=True)
        changed_fields.append("income")

    if "income_frequency" in data:
        value = data["income_frequency"]
        user.income_frequency = (
            require_enum(value, INCOME_FREQUENCIES, "income_frequency") if value else None
        )
        changed_fields.append("income_frequency")

    if "onboarding_completed" in data:
        value = data["onboarding_completed"]
        if not isinstance(value, bool):
            raise ValidationError(
                "onboarding_completed must be a boolean.",
                {"onboarding_completed": "invalid"},
            )
        user.onboarding_completed = value
        changed_fields.append("onboarding_completed")

    if changed_fields:
        log_activity(
            user.id,
            "profile_updated",
            "Profile updated",
            metadata={"fields": changed_fields},
        )

    db.session.commit()
    return user


def validate_profile_picture(content_type, content):
    """Raises ValidationError if the uploaded profile-picture content
    isn't an allowed image type or exceeds the size limit. Mirrors the
    validation previously inlined in profile_routes.upload_profile_picture."""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError(
            "Profile picture must be a JPEG, PNG, or WEBP image.",
            {"content_type": "unsupported"},
        )

    if len(content) > MAX_IMAGE_SIZE:
        raise ValidationError("Profile picture must be 5MB or smaller.")


def set_profile_picture(user, object_key):
    """Store the new profile-picture object key and clean up the
    previous R2 object, if any.

    The new key is committed first, then the old object is deleted.
    Cleanup runs after the commit: `delete_object` already swallows its
    own failures (see spaces.py), so an old, now-orphaned file in R2
    never causes a successful upload to be reported as failed.
    """
    previous_value = user.profile_picture_url

    user.profile_picture_url = object_key
    log_activity(user.id, "profile_updated", "Profile picture updated")
    db.session.commit()

    if previous_value:
        previous_key = _extract_object_key(previous_value)
        if previous_key != object_key:
            delete_object(previous_key)

    return user


def save_profile_picture(user, content, content_type, filename):
    """Uploads new profile-picture bytes to R2 under a fresh key, then
    stores that key on the user (see `set_profile_picture` for the
    old-object cleanup semantics). Raises whatever `spaces.upload_object`
    raises on a storage failure — the caller (profile_routes.py) maps
    that to its existing error response."""
    extension = os.path.splitext(filename)[1].lower()
    file_key = f"profile-pictures/{user.id}/{uuid.uuid4()}{extension}"

    upload_object(file_key, content, content_type)

    return set_profile_picture(user, file_key)
