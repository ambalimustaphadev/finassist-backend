from ..common import (
    build_tool_result,
    decimal_str,
    require_choice,
    require_currency_code,
    require_decimal,
    require_positive_int,
)
from .calculator import PERIODS_PER_YEAR, calculate_amortizing_loan

TOOL_NAME = "loan_calculator"
DURATION_UNITS = {"months", "years"}


def calculate(data):
    loan_amount = require_decimal(
        data.get("loan_amount"), "loan_amount", "INVALID_AMOUNT", exclusive_minimum=0
    )
    annual_interest_rate = require_decimal(
        data.get("annual_interest_rate"),
        "annual_interest_rate",
        "INVALID_INTEREST_RATE",
        minimum=0,
    )
    duration = require_positive_int(data.get("duration"), "duration", "INVALID_DURATION")
    duration_unit = require_choice(
        data.get("duration_unit", "months"), DURATION_UNITS, "duration_unit", "INVALID_DURATION"
    )
    frequency = require_choice(
        data.get("repayment_frequency", "monthly"),
        PERIODS_PER_YEAR.keys(),
        "repayment_frequency",
        "INVALID_FREQUENCY",
    )
    currency = require_currency_code(data.get("currency"))

    duration_months = duration * 12 if duration_unit == "years" else duration

    calc = calculate_amortizing_loan(
        loan_amount, annual_interest_rate, duration_months, frequency
    )

    inputs = {
        "loan_amount": decimal_str(loan_amount),
        "annual_interest_rate": decimal_str(annual_interest_rate, 4),
        "duration": duration,
        "duration_unit": duration_unit,
        "repayment_frequency": frequency,
        "currency": currency,
    }
    result = {
        "periodic_payment": decimal_str(calc["periodic_payment"]),
        "total_repayment": decimal_str(calc["total_repayment"]),
        "total_interest": decimal_str(calc["total_interest"]),
        "number_of_payments": calc["number_of_payments"],
    }
    metadata = {
        "currency": currency,
        "is_estimate": True,
        "assumptions": (
            "Estimate based on a standard fixed-payment amortizing loan "
            "with the supplied rate, duration, and frequency. Actual "
            "lender terms, fees, and rounding policies may differ."
        ),
    }

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
