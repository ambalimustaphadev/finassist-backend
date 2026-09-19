from decimal import Decimal

from models import Subscription
from utils import ValidationError

from ..common import build_tool_result, decimal_str
from .calculator import monthly_equivalent, yearly_equivalent

TOOL_NAME = "subscription_cost_calculator"


class SubscriptionNotFound(Exception):
    """Raised for missing ids AND ids owned by another user alike — the
    rest of the app already treats a foreign resource as 404, not 403
    (see subscription_routes.py), so this tool follows the same rule
    rather than leaking whether an id exists for someone else."""

    def __init__(self, missing_ids):
        self.missing_ids = missing_ids
        super().__init__(f"Subscriptions not found: {missing_ids}")


def _validate_subscription_ids(raw):
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise ValidationError(
            "subscription_ids must be a non-empty array of subscription ids.",
            {"subscription_ids": "INVALID_SUBSCRIPTION_ID"},
        )

    ids = []
    seen = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValidationError(
                "subscription_ids must contain positive integer ids.",
                {"subscription_ids": "INVALID_SUBSCRIPTION_ID"},
            )
        if item not in seen:
            seen.add(item)
            ids.append(item)
    return ids


def calculate(user_id, data):
    subscription_ids = _validate_subscription_ids(data.get("subscription_ids"))

    if subscription_ids is not None:
        owned = {
            s.id: s
            for s in Subscription.query.filter(
                Subscription.id.in_(subscription_ids),
                Subscription.user_id == user_id,
            ).all()
        }
        missing_ids = [i for i in subscription_ids if i not in owned]
        if missing_ids:
            raise SubscriptionNotFound(missing_ids)
        subscriptions = [owned[i] for i in subscription_ids]
    else:
        subscriptions = (
            Subscription.query.filter_by(user_id=user_id, status="active")
            .order_by(Subscription.id.asc())
            .all()
        )

    active_subscriptions = [s for s in subscriptions if s.status == "active"]
    excluded_subscriptions = [s for s in subscriptions if s.status != "active"]

    per_subscription = []
    totals_by_currency = {}

    for subscription in active_subscriptions:
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

    inputs = {"subscription_ids": subscription_ids}
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
        "subscription_count": len(active_subscriptions),
        "subscriptions": per_subscription,
        "totals_by_currency": [
            {
                "currency": currency,
                "total_monthly_cost": decimal_str(bucket["monthly_cost"]),
                "total_yearly_cost": decimal_str(bucket["yearly_cost"]),
            }
            for currency, bucket in totals_by_currency.items()
        ],
        "excluded_subscriptions": [
            {"id": s.id, "name": s.name, "status": s.status}
            for s in excluded_subscriptions
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
