"""Shared helpers used across the API surface: request/JWT-identity
access, ownership-scoped lookups, and the structured error-response
convention. The original auth/chat/conversation/file endpoints keep
their own flat `{"error": "..."}` shape since Flutter already depends
on it; every route built on top of this module since uses the
structured shape instead so those endpoints are consistent with each
other. `current_user_id`/`get_owned` below are convention-agnostic —
both shapes' routes use them the same way.
"""
import json
from datetime import date, datetime

from flask import jsonify
from flask_jwt_extended import get_jwt_identity

def current_user_id():
    """The authenticated user's id from the current request's JWT.
    Centralizes the `int(get_jwt_identity())` call repeated across
    every route module — the JWT is always the source of truth for
    identity, never anything from request JSON/query params.

    A handful of routes (chat, file uploads) deliberately guard this
    conversion themselves to return a specific error response on a
    malformed identity; they call `get_jwt_identity()` directly instead
    of this helper so that existing behavior is untouched.
    """
    return int(get_jwt_identity())


def get_owned(model, obj_id, user_id):
    """The `model` row with id `obj_id` if (and only if) it belongs to
    `user_id`, else None. Centralizes the
    `Model.query.filter_by(id=obj_id, user_id=user_id).first()`
    ownership-check pattern duplicated across route modules — callers
    still build their own 404/error response from a None result, so
    this changes no response shape, only removes the repeated query.
    """
    return model.query.filter_by(id=obj_id, user_id=user_id).first()


def authenticated_user_id_or_none():
    """`int(get_jwt_identity())`, or None if the identity is malformed.
    A handful of routes (chat, file uploads) need this None-on-failure
    form rather than `current_user_id()`'s bare conversion, so they can
    build their own specific 401 response from the None result. Shared
    here to remove the duplicated try/except across those routes."""
    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError):
        return None


def current_user():
    """The authenticated request's User row, or None. Centralizes
    `User.query.get(current_user_id())`, duplicated identically across
    route modules that need the full user row rather than just the id."""
    from models import User
    return User.query.get(current_user_id())


def parse_positive_id(value):
    """A positive int id from `value`, tolerating the shapes real
    clients actually send: a Dart `num`/`double` round-trip commonly
    produces "1.0" instead of "1" for the same id, and a plain numeric
    string ("1") is also legitimate. Both are accepted. Anything that
    isn't unambiguously an integer value (bools, nested objects/lists,
    non-integral numbers, empty/garbage strings) raises ValueError so
    the caller can reject it with a 400.
    """
    if isinstance(value, bool):
        raise ValueError("must be an integer")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError("must be an integer")
        parsed = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = int(stripped)
        except ValueError:
            as_float = float(stripped)  # raises ValueError for non-numeric strings
            if not as_float.is_integer():
                raise ValueError("must be an integer")
            parsed = int(as_float)
    else:
        raise ValueError("must be an integer")

    if parsed <= 0:
        raise ValueError("must be positive")

    return parsed


def safe_json_loads(value):
    """`json.loads(value)`, or None if `value` is empty/falsy or not
    valid JSON. Centralizes the parse-with-guard pattern duplicated
    across model-metadata serializers."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


CURRENCIES = {
    "NGN", "USD", "EUR", "GBP", "CAD", "AUD", "ZAR", "GHS", "KES",
    "INR", "JPY", "CNY", "CHF", "SEK", "NOK", "DKK", "AED", "SAR",
    "EGP", "XOF", "XAF", "BRL", "MXN", "SGD", "HKD", "NZD",
}


class ValidationError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


def error_response(code, message, status=400, details=None):
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def validation_error_response(exc):
    return error_response("VALIDATION_ERROR", exc.message, 400, exc.details)


def not_found_response(message="Resource not found"):
    return error_response("NOT_FOUND", message, 404)


def paginate_query(query, args, default_per_page=20, max_per_page=100):
    try:
        page = max(1, int(args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    per_page = max(1, min(per_page, max_per_page))

    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return items, {"page": page, "per_page": per_page, "total": total}


def require_currency(value, field_name="currency"):
    if value is None:
        return None
    code = str(value).strip().upper()
    if code not in CURRENCIES:
        raise ValidationError(
            f"'{value}' is not a supported currency code.",
            {field_name: "unsupported currency"},
        )
    return code


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise ValidationError(
            f"'{value}' is not a valid value for {field_name}.",
            {field_name: f"must be one of {sorted(allowed)}"},
        )
    return value


def require_non_empty_string(value, field_name, max_length=None):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} is required.", {field_name: "required"})
    value = value.strip()
    if max_length and len(value) > max_length:
        raise ValidationError(
            f"{field_name} must be at most {max_length} characters.",
            {field_name: "too long"},
        )
    return value


def require_number(value, field_name, minimum=None, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise ValidationError(f"{field_name} is required.", {field_name: "required"})
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field_name} must be a number.", {field_name: "invalid"})
    if minimum is not None and number < minimum:
        raise ValidationError(
            f"{field_name} must be >= {minimum}.", {field_name: "out of range"}
        )
    return number


def parse_date(value, field_name):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(
            f"{field_name} must be an ISO date (YYYY-MM-DD).", {field_name: "invalid"}
        )


def iso_date(value):
    return value.isoformat() if value else None


def iso_datetime(value):
    return value.isoformat() + "Z" if value else None
