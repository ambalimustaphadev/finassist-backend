"""Tests for FinAssist's reminder subsystem: services/reminder_service.py
and the AI tools that sit on top of it (services/ai_tools/reminders.py),
exercised through tools.dispatch_tool_call exactly as chat_routes.py
would call them."""
from tools import dispatch_tool_call


def _call(name, arguments, user_id):
    return dispatch_tool_call(name, arguments, user_id)


# --- create_reminder ---

def test_create_reminder_persists_with_given_title(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {
        "title": "Review subscriptions",
        "remind_at": "2026-10-01T09:00:00+01:00",
    }, user_id)
    reminder = result["result"]["reminder"]
    assert reminder["title"] == "Review subscriptions"
    assert reminder["status"] == "active"
    assert "id" in reminder


def test_create_reminder_converts_offset_to_utc_for_storage(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {
        "title": "Foo", "remind_at": "2026-10-01T09:00:00+01:00",
    }, user_id)
    # 09:00 +01:00 is 08:00 UTC.
    assert result["result"]["reminder"]["remind_at"].startswith("2026-10-01T08:00:00")


def test_create_reminder_accepts_z_suffix_as_utc(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {
        "title": "Foo", "remind_at": "2026-10-01T08:00:00Z",
    }, user_id)
    assert result["result"]["reminder"]["remind_at"].startswith("2026-10-01T08:00:00")


def test_create_reminder_requires_title(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {"remind_at": "2026-10-01T09:00:00+01:00"}, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_create_reminder_requires_remind_at(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {"title": "Foo"}, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_create_reminder_rejects_naive_datetime_without_offset(client, user):
    """A bare local time with no UTC offset is ambiguous and must be
    rejected — never silently treated as UTC."""
    user_id, _headers = user
    result = _call("create_reminder", {
        "title": "Foo", "remind_at": "2026-10-01T09:00:00",
    }, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert result["error"]["details"]["remind_at"] == "missing_offset"


def test_create_reminder_rejects_garbage_datetime(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {"title": "Foo", "remind_at": "not-a-date"}, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_create_reminder_rejects_blank_title(client, user):
    user_id, _headers = user
    result = _call("create_reminder", {"title": "   ", "remind_at": "2026-10-01T09:00:00+01:00"}, user_id)
    assert result["error"]["code"] == "VALIDATION_ERROR"


# --- list_reminders ---

def test_list_reminders_only_returns_own(client, user, other_user):
    user_id, _headers = user
    other_id, _other_headers = other_user
    _call("create_reminder", {"title": "Mine", "remind_at": "2026-10-01T09:00:00+00:00"}, user_id)
    _call("create_reminder", {"title": "Theirs", "remind_at": "2026-10-01T09:00:00+00:00"}, other_id)

    result = _call("list_reminders", {}, user_id)
    titles = {r["title"] for r in result["result"]["reminders"]}
    assert titles == {"Mine"}


def test_list_reminders_filters_by_status(client, user):
    user_id, _headers = user
    _call("create_reminder", {"title": "Mine", "remind_at": "2026-10-01T09:00:00+00:00"}, user_id)

    result = _call("list_reminders", {"status": "completed"}, user_id)
    assert result["result"]["reminders"] == []

    result = _call("list_reminders", {"status": "active"}, user_id)
    assert len(result["result"]["reminders"]) == 1


def test_list_reminders_rejects_invalid_status(client, user):
    user_id, _headers = user
    result = _call("list_reminders", {"status": "bogus"}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_list_reminders_ordered_by_remind_at(client, user):
    user_id, _headers = user
    _call("create_reminder", {"title": "Later", "remind_at": "2026-12-01T09:00:00+00:00"}, user_id)
    _call("create_reminder", {"title": "Sooner", "remind_at": "2026-10-01T09:00:00+00:00"}, user_id)

    result = _call("list_reminders", {}, user_id)
    titles = [r["title"] for r in result["result"]["reminders"]]
    assert titles == ["Sooner", "Later"]


# --- delete_reminder ---

def test_delete_reminder_removes_it(client, user):
    user_id, _headers = user
    created = _call("create_reminder", {"title": "Mine", "remind_at": "2026-10-01T09:00:00+00:00"}, user_id)
    reminder_id = created["result"]["reminder"]["id"]

    result = _call("delete_reminder", {"reminder_id": reminder_id}, user_id)
    assert result["result"]["deleted"] is True

    listed = _call("list_reminders", {}, user_id)
    assert listed["result"]["reminders"] == []


def test_delete_reminder_missing_id_is_safe_error(client, user):
    user_id, _headers = user
    result = _call("delete_reminder", {"reminder_id": 999999}, user_id)
    assert result["error"]["code"] == "REMINDER_NOT_FOUND"


def test_delete_reminder_ownership_isolation(client, user, other_user):
    user_id, _headers = user
    other_id, _other_headers = other_user
    theirs = _call("create_reminder", {"title": "Theirs", "remind_at": "2026-10-01T09:00:00+00:00"}, other_id)
    reminder_id = theirs["result"]["reminder"]["id"]

    result = _call("delete_reminder", {"reminder_id": reminder_id}, user_id)
    assert result["error"]["code"] == "REMINDER_NOT_FOUND"

    still_there = _call("list_reminders", {}, other_id)
    assert len(still_there["result"]["reminders"]) == 1


def test_delete_reminder_rejects_non_integer_id(client, user):
    user_id, _headers = user
    result = _call("delete_reminder", {"reminder_id": "abc"}, user_id)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"
