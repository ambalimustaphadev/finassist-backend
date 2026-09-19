from decimal import Decimal

from utils import ValidationError

from ..common import build_tool_result, decimal_str, require_currency_code, require_decimal
from .calculator import simulate_payoff

TOOL_NAME = "debt_payoff_calculator"


def calculate(data):
    current_debt = require_decimal(
        data.get("current_debt"), "current_debt", "INVALID_AMOUNT", exclusive_minimum=0
    )
    annual_interest_rate = require_decimal(
        data.get("annual_interest_rate"),
        "annual_interest_rate",
        "INVALID_INTEREST_RATE",
        minimum=0,
    )
    minimum_monthly_payment = require_decimal(
        data.get("minimum_monthly_payment"),
        "minimum_monthly_payment",
        "INVALID_AMOUNT",
        exclusive_minimum=0,
    )
    extra_monthly_payment = require_decimal(
        data.get("extra_monthly_payment"),
        "extra_monthly_payment",
        "INVALID_AMOUNT",
        minimum=0,
        allow_none=True,
    )
    if extra_monthly_payment is None:
        extra_monthly_payment = Decimal(0)
    currency = require_currency_code(data.get("currency"))

    monthly_rate = annual_interest_rate / Decimal(100) / Decimal(12)
    total_monthly_payment = minimum_monthly_payment + extra_monthly_payment

    first_month_interest = current_debt * monthly_rate
    if total_monthly_payment <= first_month_interest:
        raise ValidationError(
            "The supplied payment does not cover the monthly interest, "
            "so this debt would never be paid off.",
            {"minimum_monthly_payment": "DEBT_PAYMENT_TOO_LOW"},
        )

    payoff = simulate_payoff(current_debt, monthly_rate, total_monthly_payment)

    minimum_only = None
    interest_saved = None
    months_saved = None

    if minimum_monthly_payment > first_month_interest:
        baseline = simulate_payoff(current_debt, monthly_rate, minimum_monthly_payment)
        minimum_only = {
            "payable": True,
            "months_to_payoff": baseline["months"],
            "total_interest": decimal_str(baseline["total_interest"]),
            "total_repayment": decimal_str(baseline["total_repayment"]),
        }
        interest_saved = decimal_str(baseline["total_interest"] - payoff["total_interest"])
        months_saved = baseline["months"] - payoff["months"]
    else:
        minimum_only = {
            "payable": False,
            "months_to_payoff": None,
            "total_interest": None,
            "total_repayment": None,
        }

    inputs = {
        "current_debt": decimal_str(current_debt),
        "annual_interest_rate": decimal_str(annual_interest_rate, 4),
        "minimum_monthly_payment": decimal_str(minimum_monthly_payment),
        "extra_monthly_payment": decimal_str(extra_monthly_payment),
        "currency": currency,
    }
    result = {
        "months_to_payoff": payoff["months"],
        "total_interest": decimal_str(payoff["total_interest"]),
        "total_repayment": decimal_str(payoff["total_repayment"]),
        "minimum_only": minimum_only,
        "interest_saved": interest_saved,
        "months_saved": months_saved,
    }
    metadata = {
        "currency": currency,
        "is_estimate": True,
        "assumptions": (
            "Simulated month-by-month against a fixed payment and a "
            "fixed annual rate applied monthly. No lender fees, "
            "penalties, or rate changes are modeled."
        ),
    }

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
