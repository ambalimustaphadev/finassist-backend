"""Pure compound-growth math: a lump sum plus a monthly contribution
stream, both compounding at an effective monthly rate derived from the
nominal annual return and its compounding frequency."""
from decimal import Decimal

COMPOUNDING_PERIODS_PER_YEAR = {
    "monthly": 12,
    "quarterly": 4,
    "annually": 1,
}


def effective_monthly_rate(annual_rate, compounding_frequency):
    """Converts a nominal annual rate compounded `compounding_frequency`
    times a year into an equivalent effective monthly rate, so lump-sum
    growth and monthly contributions can be compounded consistently
    regardless of which nominal frequency was requested."""
    periods = Decimal(COMPOUNDING_PERIODS_PER_YEAR[compounding_frequency])
    if annual_rate == 0:
        return annual_rate
    periodic_rate = annual_rate / Decimal(100) / periods
    return (1 + periodic_rate) ** (periods / Decimal(12)) - 1


def future_value(initial_amount, monthly_contribution, monthly_rate, num_months):
    if monthly_rate == 0:
        growth_of_initial = initial_amount
        growth_of_contributions = monthly_contribution * num_months
    else:
        growth_factor = (1 + monthly_rate) ** num_months
        growth_of_initial = initial_amount * growth_factor
        growth_of_contributions = (
            monthly_contribution * (growth_factor - 1) / monthly_rate
        )
    return growth_of_initial + growth_of_contributions
