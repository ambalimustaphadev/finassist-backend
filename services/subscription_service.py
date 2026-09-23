from datetime import datetime

from extensions import db
from models import Subscription
from utils import (
    ValidationError,
    iso_date,
    iso_datetime,
    parse_date,
    require_currency,
    require_enum,
    require_non_empty_string,
    require_number,
)

FREQUENCIES = {"weekly", "monthly", "quarterly", "semiannual", "yearly"}
CATEGORIES = {
    "entertainment",
    "software",
    "cloud_storage",
    "education",
    "fitness",
    "news_media",
    "productivity",
    "shopping",
    "gaming",
    "other",
}
PAYMENT_METHODS = {
    "debit_card",
    "credit_card",
    "bank_account",
    "mobile_wallet",
    "direct_debit",
    "cash",
    "other",
}
STATUSES = {"active", "paused", "cancelled"}


def _require_positive_amount(value):
    number = require_number(value, "amount")
    if number <= 0:
        raise ValidationError(
            "amount must be greater than zero.", {"amount": "must be greater than zero"}
        )
    return number


def _require_billing_date(value):
    if not value:
        raise ValidationError(
            "next_billing_date is required.", {"next_billing_date": "required"}
        )
    return parse_date(value, "next_billing_date")


def list_subscriptions(user_id):
    return (
        Subscription.query.filter_by(user_id=user_id)
        .order_by(Subscription.next_billing_date.asc(), Subscription.id.asc())
        .all()
    )


def delete_subscription(subscription):
    db.session.delete(subscription)
    db.session.commit()


def subscription_to_dict(subscription):
    return {
        "id": subscription.id,
        "user_id": subscription.user_id,
        "name": subscription.name,
        "amount": subscription.amount,
        "currency": subscription.currency,
        "frequency": subscription.frequency,
        "next_billing_date": iso_date(subscription.next_billing_date),
        "category": subscription.category,
        "payment_method": subscription.payment_method,
        "website": subscription.website,
        "notes": subscription.notes,
        "status": subscription.status,
        "created_at": iso_datetime(subscription.created_at),
        "updated_at": iso_datetime(subscription.updated_at),
        "cancelled_at": iso_datetime(subscription.cancelled_at),
    }


def create_subscription(user_id, data):
    name = require_non_empty_string(data.get("name"), "name", 120)
    amount = _require_positive_amount(data.get("amount"))
    currency = require_currency(data.get("currency"))
    frequency = require_enum(data.get("frequency"), FREQUENCIES, "frequency")
    next_billing_date = _require_billing_date(data.get("next_billing_date"))

    category_value = data.get("category")
    category = require_enum(category_value, CATEGORIES, "category") if category_value else None

    payment_method_value = data.get("payment_method")
    payment_method = (
        require_enum(payment_method_value, PAYMENT_METHODS, "payment_method")
        if payment_method_value
        else None
    )

    website_value = data.get("website")
    website = require_non_empty_string(website_value, "website", 512) if website_value else None

    notes_value = data.get("notes")
    notes = require_non_empty_string(notes_value, "notes", 2000) if notes_value else None

    subscription = Subscription(
        user_id=user_id,
        name=name,
        amount=amount,
        currency=currency,
        frequency=frequency,
        next_billing_date=next_billing_date,
        category=category,
        payment_method=payment_method,
        website=website,
        notes=notes,
        status="active",
        cancelled_at=None,
    )
    db.session.add(subscription)
    db.session.commit()
    return subscription


def update_subscription(subscription, data):
    if "name" in data:
        subscription.name = require_non_empty_string(data["name"], "name", 120)

    if "amount" in data:
        subscription.amount = _require_positive_amount(data["amount"])

    if "currency" in data:
        subscription.currency = require_currency(data["currency"])

    if "frequency" in data:
        subscription.frequency = require_enum(data["frequency"], FREQUENCIES, "frequency")

    if "next_billing_date" in data:
        subscription.next_billing_date = _require_billing_date(data["next_billing_date"])

    if "category" in data:
        value = data["category"]
        subscription.category = require_enum(value, CATEGORIES, "category") if value else None

    if "payment_method" in data:
        value = data["payment_method"]
        subscription.payment_method = (
            require_enum(value, PAYMENT_METHODS, "payment_method") if value else None
        )

    if "website" in data:
        value = data["website"]
        subscription.website = require_non_empty_string(value, "website", 512) if value else None

    if "notes" in data:
        value = data["notes"]
        subscription.notes = require_non_empty_string(value, "notes", 2000) if value else None

    if "status" in data:
        new_status = require_enum(data["status"], STATUSES, "status")
        subscription.status = new_status
        if new_status == "cancelled":
            subscription.cancelled_at = datetime.utcnow()
        else:
            subscription.cancelled_at = None

    db.session.commit()
    return subscription
