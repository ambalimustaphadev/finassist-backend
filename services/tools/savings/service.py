from decimal import Decimal

from utils import ValidationError

from ..common import (
    build_tool_result,
    decimal_str,
    require_currency_code,
    require_decimal,
    require_positive_int,
)
from .calculator import future_value_of_contributions, required_contribution_for_target

TOOL_NAME = "savings_calculator"


def calculate(data):
    duration_months = require_positive_int(
        data.get("duration_months"), "duration_months", "INVALID_DURATION"
    )
    annual_return_rate = require_decimal(
        data.get("annual_return_rate"),
        "annual_return_rate",
        "INVALID_INTEREST_RATE",
        minimum=0,
        allow_none=True,
    )
    if annual_return_rate is None:
        annual_return_rate = Decimal(0)
    currency = require_currency_code(data.get("currency"))

    monthly_rate = annual_return_rate / Decimal(100) / Decimal(12)

    target_amount_raw = data.get("target_amount")
    monthly_contribution_raw = data.get("monthly_contribution")

    if target_amount_raw is not None and monthly_contribution_raw is not None:
        raise ValidationError(
            "Provide either target_amount or monthly_contribution, not both.",
            {
                "target_amount": "INVALID_AMOUNT",
                "monthly_contribution": "INVALID_AMOUNT",
            },
        )
    if target_amount_raw is None and monthly_contribution_raw is None:
        raise ValidationError(
            "Provide either target_amount or monthly_contribution.",
            {
                "target_amount": "INVALID_AMOUNT",
                "monthly_contribution": "INVALID_AMOUNT",
            },
        )

    if target_amount_raw is not None:
        target_amount = require_decimal(
            target_amount_raw, "target_amount", "INVALID_AMOUNT", exclusive_minimum=0
        )
        required_contribution = required_contribution_for_target(
            target_amount, monthly_rate, duration_months
        )
        projected_amount = target_amount
        mode = "target_based"
    else:
        monthly_contribution = require_decimal(
            monthly_contribution_raw,
            "monthly_contribution",
            "INVALID_AMOUNT",
            exclusive_minimum=0,
        )
        required_contribution = monthly_contribution
        projected_amount = future_value_of_contributions(
            monthly_contribution, monthly_rate, duration_months
        )
        mode = "contribution_based"

    total_contributions = required_contribution * duration_months
    estimated_growth = projected_amount - total_contributions

    inputs = {
        "target_amount": decimal_str(target_amount) if target_amount_raw is not None else None,
        "monthly_contribution": (
            decimal_str(monthly_contribution) if monthly_contribution_raw is not None else None
        ),
        "duration_months": duration_months,
        "annual_return_rate": decimal_str(annual_return_rate, 4),
        "currency": currency,
    }
    result = {
        "required_monthly_contribution": decimal_str(required_contribution),
        "projected_amount": decimal_str(projected_amount),
        "total_contributions": decimal_str(total_contributions),
        "estimated_growth": decimal_str(estimated_growth),
    }
    metadata = {
        "currency": currency,
        "mode": mode,
        "is_estimate": True,
        "assumptions": (
            "Projection assumes a fixed monthly contribution and a fixed "
            "monthly-compounded annual return; if no annual_return_rate "
            "is supplied, no growth is assumed."
        ),
    }

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
