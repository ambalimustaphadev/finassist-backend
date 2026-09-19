"""Shared building blocks for the deterministic Tools calculators
(currency, loan, savings, affordability, debt payoff, investment,
subscription cost).

Every tool's service module builds its response through
`build_tool_result` so the JSON envelope Flutter and the chat handoff
consume is identical across tools — only `result`/`metadata` differ.
Money is handled with `Decimal` throughout; results are rendered back
as fixed-precision strings so nothing round-trips through a binary
float on the wire.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from utils import CURRENCIES, ValidationError

TOOL_VERSION = "1"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_tool_result(tool, inputs, result, metadata=None):
    envelope_metadata = {"calculated_at": utc_now_iso()}
    if metadata:
        envelope_metadata.update(metadata)
    return {
        "tool": tool,
        "version": TOOL_VERSION,
        "inputs": inputs,
        "result": result,
        "metadata": envelope_metadata,
    }


def quantize(value, places=2):
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def decimal_str(value, places=2):
    """Render a Decimal as a fixed-precision string. This is the only
    place monetary rounding happens — calculators work at full Decimal
    precision internally and round only when building the response."""
    return format(quantize(value, places), f".{places}f")


def require_currency_code(value, field_name="currency", code="INVALID_CURRENCY"):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} is required.", {field_name: code})
    normalized = value.strip().upper()
    if normalized not in CURRENCIES:
        raise ValidationError(
            f"'{value}' is not a supported currency code.", {field_name: code}
        )
    return normalized


def require_decimal(
    value,
    field_name,
    code="INVALID_AMOUNT",
    minimum=None,
    exclusive_minimum=None,
    allow_none=False,
):
    if value is None:
        if allow_none:
            return None
        raise ValidationError(f"{field_name} is required.", {field_name: code})
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a number.", {field_name: code})
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f"{field_name} must be a number.", {field_name: code})
    if not number.is_finite():
        raise ValidationError(f"{field_name} must be a number.", {field_name: code})
    if exclusive_minimum is not None and number <= exclusive_minimum:
        raise ValidationError(
            f"{field_name} must be greater than {exclusive_minimum}.", {field_name: code}
        )
    if minimum is not None and number < minimum:
        raise ValidationError(
            f"{field_name} must be >= {minimum}.", {field_name: code}
        )
    return number


def require_positive_int(value, field_name, code="INVALID_DURATION"):
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a whole number.", {field_name: code})
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(
                f"{field_name} must be a whole number.", {field_name: code}
            )
        value = int(value)
    if not isinstance(value, int):
        raise ValidationError(f"{field_name} must be a whole number.", {field_name: code})
    if value <= 0:
        raise ValidationError(
            f"{field_name} must be greater than zero.", {field_name: code}
        )
    return value


def require_choice(value, allowed, field_name, code):
    if value not in allowed:
        raise ValidationError(
            f"'{value}' is not a valid value for {field_name}.",
            {field_name: code},
        )
    return value
