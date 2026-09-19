"""Pure amortizing-loan math. No Flask, no validation — just the
formula, so it stays independently testable and reusable (e.g. by a
future AI tool-calling layer)."""
from decimal import ROUND_HALF_UP, Decimal

# Periods per year for each supported repayment cadence. Adding a new
# frequency later is a one-line change here — nothing else in the loan
# tool needs to know about it.
PERIODS_PER_YEAR = {
    "weekly": 52,
    "biweekly": 26,
    "monthly": 12,
    "quarterly": 4,
}


def calculate_amortizing_loan(principal, annual_rate_percent, duration_months, frequency):
    periods_per_year = PERIODS_PER_YEAR[frequency]
    duration_years = Decimal(duration_months) / Decimal(12)
    num_payments = int(
        (Decimal(periods_per_year) * duration_years).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    num_payments = max(num_payments, 1)

    periodic_rate = (annual_rate_percent / Decimal(100)) / Decimal(periods_per_year)

    if periodic_rate == 0:
        periodic_payment = principal / Decimal(num_payments)
    else:
        growth_factor = (1 + periodic_rate) ** num_payments
        periodic_payment = (
            principal * periodic_rate * growth_factor / (growth_factor - 1)
        )

    total_repayment = periodic_payment * num_payments
    total_interest = total_repayment - principal

    return {
        "periodic_payment": periodic_payment,
        "total_repayment": total_repayment,
        "total_interest": total_interest,
        "number_of_payments": num_payments,
    }
