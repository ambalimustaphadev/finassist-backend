"""Tests for the subscription AI tools (services/ai_tools/subscriptions.py),
exercised through tools.dispatch_tool_call exactly as chat_routes.py
would call them. Subscriptions are created/read back through the
existing REST API (subscription_routes.py) so these tests also confirm
the AI tools stay consistent with it, not a separate parallel model."""
import datetime

from tools import dispatch_tool_call


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
