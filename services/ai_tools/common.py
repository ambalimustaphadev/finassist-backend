"""Small argument-coercion helpers shared by the AI-tool adapters.

This intentionally duplicates the *shape* (not the business logic) of
`utils.parse_positive_id`: a model-generated tool call routes JSON
through the same untrusted-input surface a Flutter client does (e.g. a
numeric id can arrive as 1, 1.0, or "1"), so the same tolerant coercion
is applied here. Kept separate rather than reused directly because the
two have different failure semantics: `utils.parse_positive_id` raises
ValueError for a route to turn into a 400, while `coerce_int` below
returns None for a tool adapter to turn into a ToolError.
"""
from .errors import ToolError


def coerce_int(value):
    """Best-effort coercion of a JSON-decoded value to a plain int.
    Returns None (never raises) when the value isn't unambiguously an
    integer — bools, non-integral numbers, and unparsable strings all
    return None so the caller can raise a tool-appropriate error."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(stripped)
        except ValueError:
            try:
                as_float = float(stripped)
            except ValueError:
                return None
            return int(as_float) if as_float.is_integer() else None
    return None


def require_positive_int_arg(value, field_name):
    coerced = coerce_int(value)
    if coerced is None or coerced <= 0:
        raise ToolError(
            "INVALID_ARGUMENTS", f"{field_name} must be a positive integer."
        )
    return coerced
