"""AI-tool adapters for subscriptions.

Every one of these functions is thin orchestration on top of the
existing subscription business logic:

- reads go straight through the `Subscription` model, scoped to
  `user_id`, using `subscription_to_dict` from
  `services.subscription_service` for serialization (same function the
  REST API in subscription_routes.py uses);
- writes go through `services.subscription_service.create_subscription`
  / `update_subscription` (same functions the REST API uses);
- `get_monthly_spend` reuses the existing subscription-cost calculator
  (`services.tools.subscription_cost.service.calculate`) rather than
  re-deriving monthly totals here.

No subscription calculation or persistence rule is duplicated in this
file. Every function signature is `(user_id, arguments) -> dict`, where
`user_id` always comes from the dispatcher's trusted server context
(see tools.py) and `arguments` is the (already-parsed) JSON object the
model supplied — never including `user_id`.
"""
from datetime import date, timedelta

from extensions import db
from models import Subscription, User
from services.subscription_service import STATUSES, infer_category, normalize_category
from services.subscription_service import create_subscription as _create_subscription
from services.subscription_service import subscription_to_dict
from services.subscription_service import update_subscription as _update_subscription
from services.tools.subscription_cost.service import calculate as _calculate_subscription_cost
from utils import ValidationError, get_owned

from .common import require_positive_int_arg
from .errors import ToolError, from_validation_error

MAX_WITHIN_DAYS = 365
DEFAULT_WITHIN_DAYS = 30

# The tool's `billing_cycle` is a curated subset of the underlying
# service's full FREQUENCIES enum (weekly/monthly/quarterly/
# semiannual/yearly): the product only wants the AI offering the three
# cadences people actually describe in conversation. Existing
# quarterly/semiannual subscriptions are unaffected and still show up
# normally in reads; the model just never creates or sets them.
BILLING_CYCLES = {"weekly", "monthly", "yearly"}

# Tool-facing field name -> Subscription/service field name. Deliberately
# excludes `plan`: the existing Subscription model has no such column,
# so there is no existing service behavior to adapt (adding one would
# mean inventing new business logic here, which this layer must not
# do). It also permanently excludes `user_id`, `id`, `status`,
# `created_at`, `cancelled_at` — none of those are reachable through
# update_subscription's tool-facing arguments at all.
_UPDATABLE_FIELDS = {
    "service_name": "name",
    "price": "amount",
    "renewal_date": "next_billing_date",
    "currency": "currency",
    "billing_cycle": "frequency",
    "category": "category",
}


def _get_owned_subscription(user_id, subscription_id):
    subscription_id = require_positive_int_arg(subscription_id, "subscription_id")
    subscription = get_owned(Subscription, subscription_id, user_id)
    if subscription is None:
        # Deliberately the same "not found" answer whether the id
        # doesn't exist at all or belongs to another user — never leak
        # which case it was.
        raise ToolError(
            "SUBSCRIPTION_NOT_FOUND",
            "No subscription with that id was found for this user.",
        )
    return subscription


def _default_currency(user_id):
    """Falls back to the user's own stored currency preference (real,
    already-known account data — never a fabricated guess) when the
    model doesn't supply one."""
    user = User.query.get(user_id)
    return user.currency if user and user.currency else "NGN"


def _resolve_category(value, service_name):
    """Explicit category (normalized) wins; with none given, infer one
    from the service name. A category that can't be interpreted becomes
    "other" — never free model text written to the database."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return infer_category(service_name)
    return normalize_category(value) or "other"


def list_subscriptions(user_id, arguments):
    status = arguments.get("status")
    if status is not None and status not in STATUSES:
        raise ToolError("INVALID_ARGUMENTS", f"status must be one of {sorted(STATUSES)}.")

    query = Subscription.query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status)
    subscriptions = query.order_by(Subscription.next_billing_date.asc(), Subscription.id.asc()).all()

    return {"subscriptions": [subscription_to_dict(s) for s in subscriptions]}


def find_subscription_by_service(user_id, arguments):
    service_name = arguments.get("service_name")
    if not isinstance(service_name, str) or not service_name.strip():
        raise ToolError("INVALID_ARGUMENTS", "service_name is required.")

    pattern = f"%{service_name.strip()}%"
    subscriptions = (
        Subscription.query.filter(
            Subscription.user_id == user_id,
            Subscription.name.ilike(pattern),
        )
        .order_by(Subscription.next_billing_date.asc(), Subscription.id.asc())
        .all()
    )

    return {"subscriptions": [subscription_to_dict(s) for s in subscriptions]}


def get_upcoming_renewals(user_id, arguments):
    within_days = arguments.get("within_days", DEFAULT_WITHIN_DAYS)
    if within_days is None:
        within_days = DEFAULT_WITHIN_DAYS
    within_days = require_positive_int_arg(within_days, "within_days")
    if within_days > MAX_WITHIN_DAYS:
        raise ToolError(
            "INVALID_ARGUMENTS",
            f"within_days must be at most {MAX_WITHIN_DAYS}.",
        )

    today = date.today()
    horizon = today + timedelta(days=within_days)
    subscriptions = (
        Subscription.query.filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            Subscription.next_billing_date >= today,
            Subscription.next_billing_date <= horizon,
        )
        .order_by(Subscription.next_billing_date.asc(), Subscription.id.asc())
        .all()
    )

    return {
        "within_days": within_days,
        "subscriptions": [subscription_to_dict(s) for s in subscriptions],
    }


def get_monthly_spend(user_id, arguments):
    # The subscription-cost calculator is the existing, authoritative
    # source for normalized monthly/yearly totals.
    return _calculate_subscription_cost(user_id)


def get_subscription_details(user_id, arguments):
    subscription = _get_owned_subscription(user_id, arguments.get("subscription_id"))
    return {"subscription": subscription_to_dict(subscription)}


def add_subscription(user_id, arguments):
    billing_cycle = arguments.get("billing_cycle") or "monthly"
    if billing_cycle not in BILLING_CYCLES:
        raise ToolError(
            "INVALID_ARGUMENTS", f"billing_cycle must be one of {sorted(BILLING_CYCLES)}."
        )

    data = {
        "name": arguments.get("service_name"),
        "amount": arguments.get("price"),
        "next_billing_date": arguments.get("renewal_date"),
        "currency": arguments.get("currency") or _default_currency(user_id),
        "frequency": billing_cycle,
        "category": _resolve_category(
            arguments.get("category"), arguments.get("service_name")
        ),
    }

    try:
        subscription = _create_subscription(user_id, data)
    except ValidationError as exc:
        raise from_validation_error(exc)

    return {"subscription": subscription_to_dict(subscription)}


def update_subscription(user_id, arguments):
    subscription = _get_owned_subscription(user_id, arguments.get("subscription_id"))

    data = {}
    for tool_field, model_field in _UPDATABLE_FIELDS.items():
        if tool_field not in arguments or arguments[tool_field] is None:
            continue
        value = arguments[tool_field]
        if tool_field == "billing_cycle" and value not in BILLING_CYCLES:
            raise ToolError(
                "INVALID_ARGUMENTS",
                f"billing_cycle must be one of {sorted(BILLING_CYCLES)}.",
            )
        if tool_field == "category":
            value = normalize_category(value) or "other"
        data[model_field] = value

    if not data:
        raise ToolError(
            "INVALID_ARGUMENTS",
            "At least one field to update (service_name, price, renewal_date, "
            "currency, billing_cycle, or category) must be provided.",
        )

    try:
        _update_subscription(subscription, data)
    except ValidationError as exc:
        raise from_validation_error(exc)

    return {"subscription": subscription_to_dict(subscription)}


def _set_status(user_id, arguments, new_status):
    subscription = _get_owned_subscription(user_id, arguments.get("subscription_id"))
    try:
        _update_subscription(subscription, {"status": new_status})
    except ValidationError as exc:
        raise from_validation_error(exc)
    return {"subscription": subscription_to_dict(subscription)}


def pause_subscription(user_id, arguments):
    return _set_status(user_id, arguments, "paused")


def resume_subscription(user_id, arguments):
    return _set_status(user_id, arguments, "active")


def cancel_subscription(user_id, arguments):
    # Cancellation, not deletion: `update_subscription`'s existing
    # status-transition logic sets `cancelled_at` and keeps the row —
    # exactly the same behavior the DELETE-free REST cancellation path
    # (PATCH status=cancelled) already provides. See delete_subscription
    # below for the separate, permanent-removal tool.
    return _set_status(user_id, arguments, "cancelled")


def delete_subscription(user_id, arguments):
    subscription = _get_owned_subscription(user_id, arguments.get("subscription_id"))
    deleted = subscription_to_dict(subscription)
    db.session.delete(subscription)
    db.session.commit()
    return {"deleted": True, "subscription": deleted}
