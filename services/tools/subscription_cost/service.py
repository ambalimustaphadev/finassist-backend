from decimal import Decimal

from models import Subscription

from ..common import build_tool_result, decimal_str
from .calculator import monthly_equivalent, yearly_equivalent

TOOL_NAME = "subscription_cost_calculator"


def calculate(user_id):
    """Normalized monthly/yearly totals for all of the user's active
    subscriptions. Backs the `get_monthly_spend` AI tool
    (services/ai_tools/subscriptions.py)."""
    subscriptions = (
        Subscription.query.filter_by(user_id=user_id, status="active")
        .order_by(Subscription.id.asc())
        .all()
    )

    per_subscription = []
    totals_by_currency = {}

    for subscription in subscriptions:
        # Always the stored DB value — a client-supplied amount is never
        # trusted for a calculation based on tracked subscriptions.
        amount = Decimal(str(subscription.amount))
        monthly_cost = monthly_equivalent(amount, subscription.frequency)
        yearly_cost = yearly_equivalent(amount, subscription.frequency)

        per_subscription.append({
            "id": subscription.id,
            "name": subscription.name,
            "amount": decimal_str(amount),
            "currency": subscription.currency,
            "frequency": subscription.frequency,
            "monthly_cost": decimal_str(monthly_cost),
            "yearly_cost": decimal_str(yearly_cost),
        })

        bucket = totals_by_currency.setdefault(
            subscription.currency,
            {"monthly_cost": Decimal(0), "yearly_cost": Decimal(0)},
        )
        bucket["monthly_cost"] += monthly_cost
        bucket["yearly_cost"] += yearly_cost

    single_currency = next(iter(totals_by_currency)) if len(totals_by_currency) == 1 else None

    inputs = {}
    result = {
        "currency": single_currency,
        "total_monthly_cost": (
            decimal_str(totals_by_currency[single_currency]["monthly_cost"])
            if single_currency
            else None
        ),
        "total_yearly_cost": (
            decimal_str(totals_by_currency[single_currency]["yearly_cost"])
            if single_currency
            else None
        ),
        "subscription_count": len(subscriptions),
        "subscriptions": per_subscription,
        "totals_by_currency": [
            {
                "currency": currency,
                "total_monthly_cost": decimal_str(bucket["monthly_cost"]),
                "total_yearly_cost": decimal_str(bucket["yearly_cost"]),
            }
            for currency, bucket in totals_by_currency.items()
        ],
    }
    metadata = {
        "is_estimate": False,
        "assumptions": (
            "monthly_cost/yearly_cost normalize each subscription's "
            "billing frequency to monthly/annual equivalents (weekly "
            "×52/12, quarterly ÷3, semiannual ÷6, yearly "
            "÷12). Paused and cancelled subscriptions are excluded "
            "from totals. total_monthly_cost/total_yearly_cost are only "
            "populated when every included subscription shares the same "
            "currency; otherwise see totals_by_currency."
        ),
    }

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
