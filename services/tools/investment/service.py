from decimal import Decimal

from ..common import (
    build_tool_result,
    decimal_str,
    require_choice,
    require_currency_code,
    require_decimal,
    require_positive_int,
)
from .calculator import COMPOUNDING_PERIODS_PER_YEAR, effective_monthly_rate, future_value

TOOL_NAME = "investment_growth_calculator"


def calculate(data):
    initial_amount = require_decimal(
        data.get("initial_amount"), "initial_amount", "INVALID_AMOUNT", minimum=0
    )
    monthly_contribution = require_decimal(
        data.get("monthly_contribution"),
        "monthly_contribution",
        "INVALID_AMOUNT",
        minimum=0,
        allow_none=True,
    )
    if monthly_contribution is None:
        monthly_contribution = Decimal(0)
    expected_annual_return = require_decimal(
        data.get("expected_annual_return"),
        "expected_annual_return",
        "INVALID_INTEREST_RATE",
        minimum=0,
    )
    duration_years = require_positive_int(
        data.get("duration_years"), "duration_years", "INVALID_DURATION"
    )
    compounding_frequency = require_choice(
        data.get("compounding_frequency", "monthly"),
        COMPOUNDING_PERIODS_PER_YEAR.keys(),
        "compounding_frequency",
        "INVALID_FREQUENCY",
    )
    currency = require_currency_code(data.get("currency"))

    num_months = duration_years * 12
    monthly_rate = effective_monthly_rate(expected_annual_return, compounding_frequency)

    fv = future_value(initial_amount, monthly_contribution, monthly_rate, num_months)
    total_contributions = initial_amount + monthly_contribution * num_months
    estimated_growth = fv - total_contributions

    inputs = {
        "initial_amount": decimal_str(initial_amount),
        "monthly_contribution": decimal_str(monthly_contribution),
        "expected_annual_return": decimal_str(expected_annual_return, 4),
        "duration_years": duration_years,
        "compounding_frequency": compounding_frequency,
        "currency": currency,
    }
    result = {
        "future_value": decimal_str(fv),
        "total_contributions": decimal_str(total_contributions),
        "estimated_growth": decimal_str(estimated_growth),
        "initial_amount": decimal_str(initial_amount),
        "contribution_amount": decimal_str(monthly_contribution),
    }
    metadata = {
        "currency": currency,
        "is_estimate": True,
        "assumptions": (
            "Projection assumes a constant expected annual return "
            "compounded at the selected frequency and a fixed monthly "
            "contribution; actual investment returns are not guaranteed "
            "and will vary. This is not investment advice or a product "
            "recommendation."
        ),
    }

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
