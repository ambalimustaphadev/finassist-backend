"""Shared building blocks for the deterministic Tools (the currency
converter, and the subscription-cost totals behind the
`get_monthly_spend` AI tool).

Every tool's service module builds its response through
`build_tool_result` so the JSON envelope Flutter and the chat handoff
consume is identical across tools — only `result`/`metadata` differ.
Money is handled with `Decimal` throughout; results are rendered back
as fixed-precision strings so nothing round-trips through a binary
float on the wire.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from utils import ValidationError

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

