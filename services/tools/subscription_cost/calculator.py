"""Pure normalization math for recurring subscription costs. Frequency
strings match `services.subscription_service.FREQUENCIES` exactly."""
from decimal import Decimal

# Documented conversion assumptions: a month is treated as 1/12 of a
# year and a week as 1/52 of a year, matching how `Subscription.
# next_billing_date` cadences are commonly reasoned about elsewhere in
# the product. These are approximations (e.g. not every month is
# exactly 4.33 weeks) applied consistently across all subscriptions.
MONTHLY_MULTIPLIER = {
    "weekly": Decimal(52) / Decimal(12),
    "monthly": Decimal(1),
    "quarterly": Decimal(1) / Decimal(3),
    "semiannual": Decimal(1) / Decimal(6),
    "yearly": Decimal(1) / Decimal(12),
}

YEARLY_MULTIPLIER = {
    "weekly": Decimal(52),
    "monthly": Decimal(12),
    "quarterly": Decimal(4),
    "semiannual": Decimal(2),
    "yearly": Decimal(1),
}


def monthly_equivalent(amount, frequency):
    return amount * MONTHLY_MULTIPLIER[frequency]


def yearly_equivalent(amount, frequency):
    return amount * YEARLY_MULTIPLIER[frequency]
