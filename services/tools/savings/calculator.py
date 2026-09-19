"""Pure savings math: future value of a monthly contribution stream,
and its inverse (the contribution required to reach a target)."""


def future_value_of_contributions(monthly_contribution, monthly_rate, num_months):
    if monthly_rate == 0:
        return monthly_contribution * num_months
    growth_factor = (1 + monthly_rate) ** num_months
    return monthly_contribution * (growth_factor - 1) / monthly_rate


def required_contribution_for_target(target_amount, monthly_rate, num_months):
    if monthly_rate == 0:
        return target_amount / num_months
    growth_factor = (1 + monthly_rate) ** num_months
    return target_amount * monthly_rate / (growth_factor - 1)
