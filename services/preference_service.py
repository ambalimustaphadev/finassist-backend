from sqlalchemy.exc import IntegrityError

from extensions import db
from models import UserPreference
from services.activity_service import log_activity
from utils import ValidationError, require_currency, require_enum

LANGUAGES = {"en", "fr", "es", "pt", "sw"}
BOOLEAN_FIELDS = (
    "notifications_enabled",
    "document_notifications",
    "proactive_suggestions",
)

# Personalization enums. Machine-readable values only — the Flutter app
# owns mapping these to display labels.
FINANCIAL_EXPERIENCE_LEVELS = {"beginner", "some_knowledge", "moderate", "advanced"}
RESPONSE_STYLES = {"simple", "balanced", "detailed"}
INTERESTS = {
    "general_money_questions",
    "understanding_documents",
    "planning_life_decisions",
    "financial_concepts",
    "comparing_options",
    "tax_questions",
    "other",
}


def get_or_create_preferences(user_id):
    """Return the user's preference row, creating it on first access.

    Not a safe check-then-insert on its own: two near-simultaneous first
    requests for the same user (e.g. two initial GETs) can both see no
    row here and both attempt the INSERT below. The `user_id` UNIQUE
    index on `UserPreference` (see models.py) is what actually prevents
    a duplicate row — one commit wins, and the other must recover by
    re-reading the row the winner just created rather than letting the
    resulting IntegrityError crash the request as an unhandled 500.
    """
    preferences = UserPreference.query.filter_by(user_id=user_id).first()
    if preferences:
        return preferences

    preferences = UserPreference(user_id=user_id)
    db.session.add(preferences)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        # Narrowed to the specific conflict this handles, so a genuinely
        # different integrity failure (e.g. a bad foreign key) still
        # surfaces instead of being misread as the expected race.
        if "user_preference.user_id" not in str(exc.orig):
            raise
        preferences = UserPreference.query.filter_by(user_id=user_id).first()
        if preferences is None:
            # The UNIQUE violation means a concurrent insert must have
            # committed first, so it should be visible now. If it isn't,
            # something other than the expected race is going on.
            raise

    return preferences


def preferences_to_dict(preferences):
    return {
        "currency": preferences.currency,
        "language": preferences.language,
        "notifications_enabled": preferences.notifications_enabled,
        "document_notifications": preferences.document_notifications,
        "financial_experience": preferences.financial_experience,
        "interests": preferences.interests,
        "response_style": preferences.response_style,
        "proactive_suggestions": preferences.proactive_suggestions,
        "updated_at": preferences.updated_at.isoformat() + "Z",
    }


def _require_interests(value):
    if not isinstance(value, list):
        raise ValidationError("interests must be an array.", {"interests": "must be an array"})

    unique = []
    for item in value:
        if not isinstance(item, str) or item not in INTERESTS:
            raise ValidationError(
                f"'{item}' is not a valid interest.",
                {"interests": f"must be one of {sorted(INTERESTS)}"},
            )
        if item not in unique:
            unique.append(item)
    return unique


def update_preferences(preferences, data):
    changed_fields = []

    if "currency" in data:
        preferences.currency = require_currency(data["currency"])
        changed_fields.append("currency")

    if "language" in data:
        preferences.language = require_enum(data["language"], LANGUAGES, "language")
        changed_fields.append("language")

    for field in BOOLEAN_FIELDS:
        if field in data:
            value = data[field]
            if not isinstance(value, bool):
                raise ValidationError(f"{field} must be a boolean.", {field: "invalid"})
            setattr(preferences, field, value)
            changed_fields.append(field)

    if "financial_experience" in data:
        value = data["financial_experience"]
        preferences.financial_experience = (
            require_enum(value, FINANCIAL_EXPERIENCE_LEVELS, "financial_experience")
            if value
            else None
        )
        changed_fields.append("financial_experience")

    if "response_style" in data:
        value = data["response_style"]
        preferences.response_style = (
            require_enum(value, RESPONSE_STYLES, "response_style") if value else None
        )
        changed_fields.append("response_style")

    if "interests" in data:
        value = data["interests"]
        preferences.interests = _require_interests(value) if value is not None else None
        changed_fields.append("interests")

    if changed_fields:
        log_activity(
            preferences.user_id,
            "preferences_updated",
            "Preferences updated",
            metadata={"fields": changed_fields},
        )

    db.session.commit()
    return preferences
