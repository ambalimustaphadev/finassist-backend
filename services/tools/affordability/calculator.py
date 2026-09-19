"""Pure affordability math. No interest is modeled here (the tool
doesn't collect a rate) — an installment purchase is spread evenly
across its duration, and callers are told this is a simplifying
assumption, not a lender quote."""
from decimal import Decimal


def estimate_monthly_payment(purchase_price, payment_method, duration_months):
    if payment_method == "cash":
        return Decimal(0)
    return purchase_price / duration_months
