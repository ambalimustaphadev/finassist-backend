"""Pure debt-payoff simulation. Simulated month-by-month (rather than a
closed-form payoff-time formula) so the final, partial payment is
handled exactly and the totals are always internally consistent."""
from decimal import Decimal

# Safety bound so a pathological input can never loop indefinitely.
# Mathematically unreachable once the caller has verified the payment
# exceeds the first month's interest (see debt_payoff/service.py),
# since a payment that clears more than the current interest every
# month makes the balance strictly decrease.
MAX_MONTHS = 2400


def simulate_payoff(balance, monthly_rate, monthly_payment):
    months = 0
    total_interest = Decimal(0)
    total_paid = Decimal(0)
    remaining = balance

    while remaining > 0 and months < MAX_MONTHS:
        interest = remaining * monthly_rate
        payment = monthly_payment
        if payment > remaining + interest:
            payment = remaining + interest
        principal_payment = payment - interest

        remaining -= principal_payment
        total_interest += interest
        total_paid += payment
        months += 1

    return {
        "months": months,
        "total_interest": total_interest,
        "total_repayment": total_paid,
        "payoff_reached": remaining <= 0,
    }
