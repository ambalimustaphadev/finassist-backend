"""Tests for tools.py: the AI-tool registry and dispatcher itself
(allowlisting, argument parsing, error shaping, user_id trust
boundary). Individual tool behavior is covered in
test_ai_tools_subscriptions.py, test_ai_tools_currency.py, and
test_reminders.py.
"""
import tools
from tools import TOOLS, _HANDLERS, dispatch_tool_call, parse_tool_arguments


def test_every_defined_tool_has_exactly_one_registered_handler():
    tool_names = {tool["name"] for tool in TOOLS}
    assert tool_names == set(_HANDLERS)


def test_tool_definitions_use_the_flat_responses_api_shape():
    # chat_routes.py calls the Responses API (client.responses.create),
    # whose function-tool shape is flat: {"type","name","parameters"} —
    # not the Chat Completions {"type","function": {...}} nesting. Using
    # the wrong shape would silently register no usable tools.
    for tool in TOOLS:
        assert tool["type"] == "function"
        assert isinstance(tool.get("name"), str) and tool["name"]
        assert isinstance(tool.get("description"), str) and tool["description"]
        assert "parameters" in tool
        assert "function" not in tool


def test_tool_names_match_the_exact_expected_set():
    expected = {
        "list_subscriptions", "find_subscription_by_service", "get_upcoming_renewals",
        "get_monthly_spend", "get_subscription_details", "add_subscription",
        "update_subscription", "pause_subscription", "resume_subscription",
        "cancel_subscription", "delete_subscription",
        "get_supported_currencies", "convert_currency", "get_exchange_rate",
        "create_reminder", "list_reminders", "delete_reminder",
    }
    assert {tool["name"] for tool in TOOLS} == expected


def test_dispatch_unknown_tool_returns_structured_error():
    result = dispatch_tool_call("delete_everything", {}, user_id=1)
    assert result == {
        "error": {
            "code": "UNKNOWN_TOOL",
            "message": "The requested tool is not available.",
        }
    }


def test_dispatch_valid_tool_returns_result_envelope(client):
    result = dispatch_tool_call("get_supported_currencies", {}, user_id=1)
    assert "error" not in result
    assert "currencies" in result["result"]


def test_dispatch_rejects_non_object_arguments(client):
    result = dispatch_tool_call("list_subscriptions", "not-a-dict", user_id=1)
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_dispatch_model_supplied_user_id_is_ignored(client, user, other_user):
    """A malicious or confused model that puts its own user_id inside
    the tool-call arguments must never redirect the dispatcher at
    another user's data — only the trusted server-side user_id (the
    positional argument, from the JWT) is ever honored."""
    user_id, headers = user
    other_id, other_headers = other_user

    client.post("/api/subscriptions", headers=headers, json={
        "name": "Mine", "amount": 100, "currency": "NGN",
        "frequency": "monthly", "next_billing_date": "2026-10-15",
    })
    client.post("/api/subscriptions", headers=other_headers, json={
        "name": "Theirs", "amount": 200, "currency": "NGN",
        "frequency": "monthly", "next_billing_date": "2026-10-15",
    })

    result = dispatch_tool_call(
        "list_subscriptions", {"user_id": other_id}, user_id=user_id
    )
    names = {s["name"] for s in result["result"]["subscriptions"]}
    assert names == {"Mine"}


def test_dispatch_handler_exception_is_not_leaked(client, monkeypatch):
    def _boom(user_id, arguments):
        raise RuntimeError("raw internal detail: password=hunter2")

    monkeypatch.setitem(tools._HANDLERS, "list_subscriptions", _boom)

    result = dispatch_tool_call("list_subscriptions", {}, user_id=1)
    assert result == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Something went wrong while running that action.",
        }
    }
    assert "hunter2" not in str(result)


def test_parse_tool_arguments_missing_or_empty_is_empty_dict():
    assert parse_tool_arguments(None) == {}
    assert parse_tool_arguments("") == {}


def test_parse_tool_arguments_valid_json_object():
    assert parse_tool_arguments('{"a": 1}') == {"a": 1}


def test_parse_tool_arguments_malformed_json_returns_none():
    assert parse_tool_arguments("{not valid json") is None


def test_parse_tool_arguments_non_object_json_returns_none():
    assert parse_tool_arguments("[1, 2, 3]") is None
    assert parse_tool_arguments('"just a string"') is None
    assert parse_tool_arguments("42") is None


def test_parse_tool_arguments_oversized_returns_none():
    huge = '{"a": "' + ("x" * 20_000) + '"}'
    assert parse_tool_arguments(huge) is None
