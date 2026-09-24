"""Tests for the subscription AI tools (services/ai_tools/subscriptions.py),
exercised through tools.dispatch_tool_call exactly as chat_routes.py
would call them. Subscriptions are created/read back through the
existing REST API (subscription_routes.py) so these tests also confirm
the AI tools stay consistent with it, not a separate parallel model."""
import datetime

import pytest

from models import Subscription
from services.subscription_service import CATEGORIES, infer_category, normalize_category
from services.tools.subscription_cost.service import calculate as _calculate_subscription_cost
from tools import TOOLS, dispatch_tool_call


def _create_subscription(client, headers, **overrides):
    payload = {
        "name": "Netflix",
        "amount": 7000,
        "currency": "NGN",
        "frequency": "monthly",
        "next_billing_date": "2026-10-15",
    }
    payload.update(overrides)
    return client.post("/api/subscriptions", headers=headers, json=payload).get_json()


def _call(name, arguments, user_id):
    return dispatch_tool_call(name, arguments, user_id)


# --- list_subscriptions ---

def test_list_subscriptions_only_returns_own(client, user, other_user):
    user_id, headers = user
    _other_id, other_headers = other_user
    _create_subscription(client, headers, name="Mine")
    _create_subscription(client, other_headers, name="Theirs")

    result = _call("list_subscriptions", {}, user_id)
    names = {s["name"] for s in result["result"]["subscriptions"]}
    assert names == {"Mine"}


def test_list_subscriptions_filters_by_status(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers, name="Netflix")
    client.patch(f"/api/subscriptions/{created['id']}", headers=headers, json={"status": "paused"})
    _create_subscription(client, headers, name="Spotify")

    result = _call("list_subscriptions", {"status": "paused"}, user_id)
    names = {s["name"] for s in result["result"]["subscriptions"]}
    assert names == {"Netflix"}


def test_list_subscriptions_rejects_invalid_status(client, user):
    user_id, _headers = user
    result = _call("list_subscriptions", {"status": "deleted"}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


# --- find_subscription_by_service ---

def test_find_subscription_by_service_partial_case_insensitive_match(client, user):
    user_id, headers = user
    _create_subscription(client, headers, name="Netflix")
    _create_subscription(client, headers, name="Spotify")

    result = _call("find_subscription_by_service", {"service_name": "net"}, user_id)
    names = {s["name"] for s in result["result"]["subscriptions"]}
    assert names == {"Netflix"}


def test_find_subscription_by_service_requires_service_name(client, user):
    user_id, _headers = user
    result = _call("find_subscription_by_service", {}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_find_subscription_by_service_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    _create_subscription(client, other_headers, name="Netflix")

    result = _call("find_subscription_by_service", {"service_name": "netflix"}, user_id)
    assert result["result"]["subscriptions"] == []


# --- get_upcoming_renewals ---

def test_upcoming_renewals_returns_only_within_window(client, user):
    user_id, headers = user
    soon = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    far = (datetime.date.today() + datetime.timedelta(days=200)).isoformat()
    _create_subscription(client, headers, name="Soon", next_billing_date=soon)
    _create_subscription(client, headers, name="Far", next_billing_date=far)

    result = _call("get_upcoming_renewals", {"within_days": 30}, user_id)
    names = {s["name"] for s in result["result"]["subscriptions"]}
    assert names == {"Soon"}


def test_upcoming_renewals_defaults_to_30_days(client, user):
    user_id, _headers = user
    result = _call("get_upcoming_renewals", {}, user_id)
    assert result["result"]["within_days"] == 30


def test_upcoming_renewals_rejects_absurd_values(client, user):
    user_id, _headers = user
    result = _call("get_upcoming_renewals", {"within_days": 10_000}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_upcoming_renewals_rejects_non_positive(client, user):
    user_id, _headers = user
    result = _call("get_upcoming_renewals", {"within_days": 0}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_upcoming_renewals_excludes_paused_and_cancelled(client, user):
    user_id, headers = user
    soon = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    created = _create_subscription(client, headers, name="Paused", next_billing_date=soon)
    client.patch(f"/api/subscriptions/{created['id']}", headers=headers, json={"status": "paused"})

    result = _call("get_upcoming_renewals", {"within_days": 30}, user_id)
    assert result["result"]["subscriptions"] == []


# --- get_monthly_spend ---

def test_monthly_spend_reuses_existing_subscription_cost_calculator(client, user):
    user_id, headers = user
    _create_subscription(client, headers, name="Netflix", amount=7000, frequency="monthly")

    result = _call("get_monthly_spend", {}, user_id)
    assert result["result"]["tool"] == "subscription_cost_calculator"
    assert result["result"]["result"]["total_monthly_cost"] == "7000.00"


def test_monthly_spend_normalizes_each_frequency(client, user):
    user_id, headers = user
    _create_subscription(client, headers, name="Weekly", amount=1000, frequency="weekly")
    _create_subscription(client, headers, name="Monthly", amount=7000, frequency="monthly")
    _create_subscription(client, headers, name="Quarterly", amount=60000, frequency="quarterly")
    _create_subscription(client, headers, name="Semiannual", amount=30000, frequency="semiannual")
    _create_subscription(client, headers, name="Yearly", amount=120000, frequency="yearly")

    result = _call("get_monthly_spend", {}, user_id)["result"]["result"]
    by_name = {s["name"]: s for s in result["subscriptions"]}
    assert (by_name["Weekly"]["monthly_cost"], by_name["Weekly"]["yearly_cost"]) == ("4333.33", "52000.00")
    assert (by_name["Monthly"]["monthly_cost"], by_name["Monthly"]["yearly_cost"]) == ("7000.00", "84000.00")
    assert (by_name["Quarterly"]["monthly_cost"], by_name["Quarterly"]["yearly_cost"]) == ("20000.00", "240000.00")
    assert (by_name["Semiannual"]["monthly_cost"], by_name["Semiannual"]["yearly_cost"]) == ("5000.00", "60000.00")
    assert (by_name["Yearly"]["monthly_cost"], by_name["Yearly"]["yearly_cost"]) == ("10000.00", "120000.00")
    assert result["subscription_count"] == 5
    assert result["currency"] == "NGN"
    assert result["total_monthly_cost"] == "46333.33"
    assert result["total_yearly_cost"] == "556000.00"


def test_monthly_spend_excludes_paused_and_cancelled(client, user):
    user_id, headers = user
    paused = _create_subscription(client, headers, name="Paused", amount=7000)
    cancelled = _create_subscription(client, headers, name="Cancelled", amount=7000)
    client.patch(f"/api/subscriptions/{paused['id']}", headers=headers, json={"status": "paused"})
    client.patch(f"/api/subscriptions/{cancelled['id']}", headers=headers, json={"status": "cancelled"})
    _create_subscription(client, headers, name="Spotify", amount=10000)

    result = _call("get_monthly_spend", {}, user_id)["result"]["result"]
    assert result["subscription_count"] == 1
    assert result["subscriptions"][0]["name"] == "Spotify"
    assert result["total_monthly_cost"] == "10000.00"


def test_monthly_spend_with_no_subscriptions_is_empty(client, user):
    user_id, _headers = user
    result = _call("get_monthly_spend", {}, user_id)["result"]["result"]
    assert result["subscription_count"] == 0
    assert result["subscriptions"] == []
    assert result["total_monthly_cost"] is None
    assert result["total_yearly_cost"] is None


def test_monthly_spend_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    _create_subscription(client, other_headers, name="Theirs", amount=5000)

    result = _call("get_monthly_spend", {}, user_id)["result"]["result"]
    assert result["subscription_count"] == 0


def test_monthly_spend_does_not_sum_mixed_currencies(client, user):
    user_id, headers = user
    _create_subscription(client, headers, name="Netflix", amount=7000, currency="NGN")
    _create_subscription(client, headers, name="Spotify", amount=10, currency="USD")

    result = _call("get_monthly_spend", {}, user_id)["result"]["result"]
    assert result["currency"] is None
    assert result["total_monthly_cost"] is None
    assert result["total_yearly_cost"] is None
    assert {b["currency"] for b in result["totals_by_currency"]} == {"NGN", "USD"}


def test_monthly_spend_ignores_model_supplied_arguments(client, user):
    user_id, headers = user
    _create_subscription(client, headers, name="Netflix", amount=7000)

    # get_monthly_spend takes no parameters; anything the model sends is
    # ignored and the stored DB amount is always what's totaled.
    result = _call("get_monthly_spend", {"amount": 1, "subscription_ids": [999]}, user_id)
    assert result["result"]["result"]["subscriptions"][0]["amount"] == "7000.00"


# --- get_subscription_details ---

def test_get_subscription_details_returns_owned_subscription(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers, name="Netflix")

    result = _call("get_subscription_details", {"subscription_id": created["id"]}, user_id)
    assert result["result"]["subscription"]["name"] == "Netflix"


def test_get_subscription_details_missing_id_is_safe_error(client, user):
    user_id, _headers = user
    result = _call("get_subscription_details", {"subscription_id": 999999}, user_id)
    assert result["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


def test_get_subscription_details_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    theirs = _create_subscription(client, other_headers, name="Theirs")

    result = _call("get_subscription_details", {"subscription_id": theirs["id"]}, user_id)
    assert result["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


def test_get_subscription_details_rejects_non_integer_id(client, user):
    user_id, _headers = user
    result = _call("get_subscription_details", {"subscription_id": "not-an-id"}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


# --- add_subscription ---

def test_add_subscription_creates_with_given_fields(client, user):
    user_id, _headers = user
    result = _call("add_subscription", {
        "service_name": "Netflix", "price": 7000, "renewal_date": "2026-10-15",
        "currency": "NGN", "billing_cycle": "monthly",
    }, user_id)
    subscription = result["result"]["subscription"]
    assert subscription["name"] == "Netflix"
    assert subscription["amount"] == 7000
    assert subscription["frequency"] == "monthly"
    assert subscription["currency"] == "NGN"
    assert subscription["status"] == "active"


def test_add_subscription_defaults_billing_cycle_to_monthly(client, user):
    user_id, _headers = user
    result = _call("add_subscription", {
        "service_name": "Netflix", "price": 7000, "renewal_date": "2026-10-15",
    }, user_id)
    assert result["result"]["subscription"]["frequency"] == "monthly"


def test_add_subscription_defaults_currency_to_user_profile_currency(client, user):
    user_id, _headers = user
    # models.User.currency defaults to "NGN" for a freshly registered user.
    result = _call("add_subscription", {
        "service_name": "Netflix", "price": 7000, "renewal_date": "2026-10-15",
    }, user_id)
    assert result["result"]["subscription"]["currency"] == "NGN"


def test_add_subscription_rejects_missing_price_rather_than_inventing_one(client, user):
    user_id, _headers = user
    result = _call("add_subscription", {
        "service_name": "Netflix", "renewal_date": "2026-10-15",
    }, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_add_subscription_rejects_invalid_date(client, user):
    user_id, _headers = user
    result = _call("add_subscription", {
        "service_name": "Netflix", "price": 7000, "renewal_date": "not-a-date",
    }, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_add_subscription_rejects_invalid_billing_cycle(client, user):
    user_id, _headers = user
    result = _call("add_subscription", {
        "service_name": "Netflix", "price": 7000, "renewal_date": "2026-10-15",
        "billing_cycle": "biweekly",
    }, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_add_subscription_is_scoped_to_authenticated_user(client, user):
    user_id, headers = user
    _call("add_subscription", {
        "service_name": "Netflix", "price": 7000, "renewal_date": "2026-10-15",
    }, user_id)
    listed = client.get("/api/subscriptions", headers=headers).get_json()
    assert len(listed) == 1
    assert listed[0]["user_id"] == user_id


# --- update_subscription ---

def test_update_subscription_changes_only_given_fields(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers, name="Netflix", amount=7000)

    result = _call("update_subscription", {"subscription_id": created["id"], "price": 9000}, user_id)
    updated = result["result"]["subscription"]
    assert updated["amount"] == 9000
    assert updated["name"] == "Netflix"


def test_update_subscription_requires_at_least_one_field(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers)
    result = _call("update_subscription", {"subscription_id": created["id"]}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_update_subscription_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    theirs = _create_subscription(client, other_headers, name="Theirs")

    result = _call("update_subscription", {"subscription_id": theirs["id"], "price": 1}, user_id)
    assert result["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"

    unchanged = client.get(f"/api/subscriptions/{theirs['id']}", headers=other_headers).get_json()
    assert unchanged["amount"] == theirs["amount"]


def test_update_subscription_cannot_touch_user_id_or_status(client, user):
    """user_id and status aren't tool-facing fields on update_subscription
    at all (status has its own pause/resume/cancel tools) — any attempt
    to slip them through the arguments is simply ignored."""
    user_id, headers = user
    created = _create_subscription(client, headers)

    result = _call("update_subscription", {
        "subscription_id": created["id"], "price": 1, "user_id": 999999, "status": "cancelled",
    }, user_id)
    updated = result["result"]["subscription"]
    assert updated["user_id"] == user_id
    assert updated["status"] == "active"


# --- pause / resume / cancel ---

def test_pause_subscription(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers)
    result = _call("pause_subscription", {"subscription_id": created["id"]}, user_id)
    assert result["result"]["subscription"]["status"] == "paused"


def test_resume_subscription(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers)
    _call("pause_subscription", {"subscription_id": created["id"]}, user_id)

    result = _call("resume_subscription", {"subscription_id": created["id"]}, user_id)
    assert result["result"]["subscription"]["status"] == "active"
    assert result["result"]["subscription"]["cancelled_at"] is None


def test_cancel_subscription_marks_cancelled_but_keeps_the_record(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers)

    result = _call("cancel_subscription", {"subscription_id": created["id"]}, user_id)
    assert result["result"]["subscription"]["status"] == "cancelled"
    assert result["result"]["subscription"]["cancelled_at"] is not None

    still_there = client.get(f"/api/subscriptions/{created['id']}", headers=headers)
    assert still_there.status_code == 200


def test_pause_resume_cancel_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    theirs = _create_subscription(client, other_headers)

    for tool_name in ("pause_subscription", "resume_subscription", "cancel_subscription"):
        result = _call(tool_name, {"subscription_id": theirs["id"]}, user_id)
        assert result["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


# --- delete_subscription ---

def test_delete_subscription_removes_the_record(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers)

    result = _call("delete_subscription", {"subscription_id": created["id"]}, user_id)
    assert result["result"]["deleted"] is True

    gone = client.get(f"/api/subscriptions/{created['id']}", headers=headers)
    assert gone.status_code == 404


def test_cancel_and_delete_are_not_interchangeable(client, user):
    """cancel_subscription must never delete the row, and
    delete_subscription must never merely mark it cancelled."""
    user_id, headers = user
    created = _create_subscription(client, headers)

    _call("cancel_subscription", {"subscription_id": created["id"]}, user_id)
    still_there = client.get(f"/api/subscriptions/{created['id']}", headers=headers)
    assert still_there.status_code == 200
    assert still_there.get_json()["status"] == "cancelled"

    _call("delete_subscription", {"subscription_id": created["id"]}, user_id)
    gone = client.get(f"/api/subscriptions/{created['id']}", headers=headers)
    assert gone.status_code == 404


def test_delete_subscription_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    theirs = _create_subscription(client, other_headers)

    result = _call("delete_subscription", {"subscription_id": theirs["id"]}, user_id)
    assert result["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"

    still_there = client.get(f"/api/subscriptions/{theirs['id']}", headers=other_headers)
    assert still_there.status_code == 200


# --- subscription categories ---

def _add(authenticated_user_id, **arguments):
    base = {"service_name": "ABC", "price": 5000, "renewal_date": "2026-10-15"}
    base.update(arguments)
    return _call("add_subscription", base, authenticated_user_id)


@pytest.mark.parametrize("requested, expected", [
    ("entertainment", "entertainment"),
    ("Entertainment", "entertainment"),
    ("music", "entertainment"),
    ("streaming", "entertainment"),
    ("cloud storage", "cloud_storage"),
    ("Cloud & Storage", "cloud_storage"),
    ("cloud", "cloud_storage"),
    ("learning", "education"),
    ("gym", "fitness"),
    ("news", "news_media"),
    ("news&media", "news_media"),
    ("work tools", "productivity"),
    ("ecommerce", "shopping"),
    ("e-commerce", "shopping"),
    ("games", "gaming"),
    ("SaaS", "software"),
    ("misc", "other"),
])
def test_add_subscription_normalizes_explicit_category(client, user, requested, expected):
    user_id, headers = user
    result = _add(user_id, category=requested)
    subscription = result["result"]["subscription"]
    assert subscription["category"] == expected

    stored = client.get(f"/api/subscriptions/{subscription['id']}", headers=headers).get_json()
    assert stored["category"] == expected


def test_explicit_category_overrides_inferred_merchant_category(client, user):
    user_id, _headers = user
    inferred = _add(user_id, service_name="Amazon Prime")
    assert inferred["result"]["subscription"]["category"] == "shopping"

    explicit = _add(user_id, service_name="Amazon Prime", category="entertainment")
    assert explicit["result"]["subscription"]["category"] == "entertainment"


@pytest.mark.parametrize("service_name, expected", [
    ("Netflix", "entertainment"),
    ("Spotify", "entertainment"),
    ("ChatGPT", "software"),
    ("Google One", "cloud_storage"),
    ("Udemy", "education"),
    ("my gym membership", "fitness"),
    ("Notion", "productivity"),
    ("PlayStation Plus", "gaming"),
    ("CNN subscription", "news_media"),
    ("Amazon Prime Video", "entertainment"),
])
def test_add_subscription_infers_category_when_none_given(client, user, service_name, expected):
    user_id, _headers = user
    result = _add(user_id, service_name=service_name)
    assert result["result"]["subscription"]["category"] == expected


def test_add_subscription_unknown_merchant_without_category_is_other(client, user):
    user_id, _headers = user
    result = _add(user_id, service_name="ABC subscription")
    assert result["result"]["subscription"]["category"] == "other"


@pytest.mark.parametrize("bad_category", ["space lasers", "DROP TABLE subscription", 123, ["music"]])
def test_add_subscription_uninterpretable_category_is_stored_as_other(client, user, bad_category):
    user_id, _headers = user
    result = _add(user_id, service_name="Netflix", category=bad_category)
    subscription = result["result"]["subscription"]
    assert subscription["category"] == "other"
    assert Subscription.query.get(subscription["id"]).category in CATEGORIES


def test_add_subscription_with_category_ignores_model_supplied_user_id(client, user, other_user):
    user_id, headers = user
    other_id, other_headers = other_user
    result = _add(user_id, service_name="Netflix", category="music", user_id=other_id)
    assert result["result"]["subscription"]["user_id"] == user_id
    assert client.get("/api/subscriptions", headers=other_headers).get_json() == []
    assert len(client.get("/api/subscriptions", headers=headers).get_json()) == 1


def test_update_subscription_normalizes_category(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers, name="Netflix", category="entertainment")

    result = _call("update_subscription", {"subscription_id": created["id"], "category": "Cloud Storage"}, user_id)
    assert result["result"]["subscription"]["category"] == "cloud_storage"

    result = _call("update_subscription", {"subscription_id": created["id"], "category": "nonsense"}, user_id)
    assert result["result"]["subscription"]["category"] == "other"


def test_update_subscription_without_category_keeps_existing_category(client, user):
    user_id, headers = user
    created = _create_subscription(client, headers, name="Netflix", category="gaming")

    result = _call("update_subscription", {"subscription_id": created["id"], "price": 9000}, user_id)
    updated = result["result"]["subscription"]
    assert updated["amount"] == 9000
    assert updated["category"] == "gaming"


def test_update_subscription_category_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    _other_id, other_headers = other_user
    theirs = _create_subscription(client, other_headers, category="fitness")

    result = _call("update_subscription", {"subscription_id": theirs["id"], "category": "gaming"}, user_id)
    assert result["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"

    unchanged = client.get(f"/api/subscriptions/{theirs['id']}", headers=other_headers).get_json()
    assert unchanged["category"] == "fitness"


def test_monthly_spend_still_works_with_categorized_subscriptions(client, user):
    user_id, _headers = user
    _add(user_id, service_name="Netflix", price=8000, currency="NGN", category="Entertainment")
    _add(user_id, service_name="Google One", price=2000, currency="NGN")

    result = _call("get_monthly_spend", {}, user_id)["result"]
    expected = _calculate_subscription_cost(user_id)
    result.pop("metadata")
    expected.pop("metadata")
    assert result == expected


def test_normalize_category_only_returns_canonical_values_or_none():
    assert normalize_category("News & Media") == "news_media"
    assert normalize_category("cloud_storage") == "cloud_storage"
    assert normalize_category("online music streaming") == "entertainment"
    assert normalize_category("cloud gaming") is None  # conflicting words: don't guess
    assert normalize_category("") is None
    assert normalize_category(None) is None
    assert infer_category("ABC") == "other"


def test_category_tool_schema_matches_service_categories():
    for tool_name in ("add_subscription", "update_subscription"):
        tool = next(t for t in TOOLS if t["name"] == tool_name)
        assert set(tool["parameters"]["properties"]["category"]["enum"]) == CATEGORIES
