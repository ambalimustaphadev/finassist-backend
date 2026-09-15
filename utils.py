"""Shared helpers for the non-chat API surface (profile, preferences,
activity, notifications). The existing auth/chat/conversation/file
endpoints keep their own flat `{"error": "..."}` shape since Flutter
already depends on it; every route added on top of this module uses
the structured shape instead so new endpoints are consistent with each
other.
"""
from datetime import date, datetime

from flask import jsonify

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
