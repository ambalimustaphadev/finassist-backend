from decimal import Decimal

from ..common import (
    build_tool_result,
    decimal_str,
    require_choice,
    require_currency_code,
    require_decimal,
    require_positive_int,
)
from .calculator import estimate_monthly_payment

TOOL_NAME = "affordability_calculator"
PAYMENT_METHODS = {"cash", "installment"}

# A configurable guideline, not a universal truth — surfaced in
# metadata so callers (and the AI layer) present it as one lens on
# affordability, not an absolute verdict.
DEFAULT_COMMITMENT_RATIO_THRESHOLD = Decimal("0.40")


def calculate(data):
    monthly_income = require_decimal(
        data.get("monthly_income"), "monthly_income", "INVALID_AMOUNT", exclusive_minimum=0
    )
    existing_commitments = require_decimal(
        data.get("existing_commitments"),
        "existing_commitments",
        "INVALID_AMOUNT",
        minimum=0,
    )
    purchase_price = require_decimal(
        data.get("purchase_price"), "purchase_price", "INVALID_AMOUNT", exclusive_minimum=0
    )
    payment_method = require_choice(
        data.get("payment_method"), PAYMENT_METHODS, "payment_method", "INVALID_PAYMENT"
    )
    currency = require_currency_code(data.get("currency"))

    duration_months = None
    if payment_method == "installment":
        duration_months = require_positive_int(
            data.get("duration_months"), "duration_months", "INVALID_DURATION"
        )

    estimated_monthly_payment = estimate_monthly_payment(
        purchase_price, payment_method, duration_months
    )
    total_monthly_commitments = existing_commitments + estimated_monthly_payment
    commitment_ratio = (
        total_monthly_commitments / monthly_income if monthly_income else Decimal(0)
    )
    remaining_income = monthly_income - total_monthly_commitments

    inputs = {
        "monthly_income": decimal_str(monthly_income),
        "existing_commitments": decimal_str(existing_commitments),
        "purchase_price": decimal_str(purchase_price),
        "payment_method": payment_method,
        "duration_months": duration_months,
        "currency": currency,
    }
    result = {
        "estimated_monthly_payment": decimal_str(estimated_monthly_payment),
        "total_monthly_commitments": decimal_str(total_monthly_commitments),
        "commitment_ratio": decimal_str(commitment_ratio, 4),
        "remaining_income": decimal_str(remaining_income),
    }
    metadata = {
        "currency": currency,
        "is_estimate": True,
        "commitment_ratio_threshold": decimal_str(DEFAULT_COMMITMENT_RATIO_THRESHOLD, 2),
        "within_threshold": commitment_ratio <= DEFAULT_COMMITMENT_RATIO_THRESHOLD,
        "assumptions": (
            "commitment_ratio is total monthly commitments divided by "
            "monthly income. within_threshold compares it against a "
            "configurable guideline (commitment_ratio_threshold), not a "
            "universal affordability rule — treat it as one input among "
            "several, not a verdict."
        ),
    }

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
