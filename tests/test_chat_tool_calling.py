"""Tests for the AI-chat tool-calling loop wired into /api/chat (see
services/ai_service.py:run_tool_loop). OpenAI is always mocked — these tests
must never depend on a real AI call. The fakes here mimic the shape of
openai's Responses API function-call output items (type/call_id/name/
arguments attributes, and a `.output` list on the response) closely
enough to exercise the real dispatch path against a real database."""
import json

from tools import MAX_TOOL_ROUNDS


class _FakeFunctionCall:
    def __init__(self, call_id, name, arguments):
        self.type = "function_call"
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(self, output_text="", output=None):
        self.output_text = output_text
        self.output = output or []


class _QueueingResponses:
    """Returns each queued response once, in call order. Records every
    call (including `tools`/`input`) for assertions."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, model, instructions, input, tools=None):
        self.calls.append({
            "model": model,
            "instructions": instructions,
            "input": list(input),
            "tools": tools,
        })
        return self._responses.pop(0)


class _QueueingOpenAIClient:
    def __init__(self, responses):
        self.responses = _QueueingResponses(responses)


def _new_conversation(client, headers):
    return client.post("/api/conversations", headers=headers, json={}).get_json()["conversation"]["id"]


def _find_function_call_output(input_list, call_id):
    for item in input_list:
        if isinstance(item, dict) and item.get("type") == "function_call_output" and item.get("call_id") == call_id:
            return json.loads(item["output"])
    return None


# --- basic plumbing ---

def test_chat_sends_tools_to_openai(client, auth_headers, monkeypatch):
    fake = _QueueingOpenAIClient([_FakeResponse(output_text="Hi there.")])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Hello",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200

    sent_tools = fake.responses.calls[0]["tools"]
    tool_names = {tool["name"] for tool in sent_tools}
    assert "list_subscriptions" in tool_names
    assert "convert_currency" in tool_names
    assert "create_reminder" in tool_names


def test_chat_without_a_tool_call_makes_exactly_one_api_call(client, auth_headers, monkeypatch):
    fake = _QueueingOpenAIClient([_FakeResponse(output_text="Just a normal reply.")])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "How much should I save?",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    assert response.get_json()["response"] == "Just a normal reply."
    assert len(fake.responses.calls) == 1


# --- single tool call ---

def test_chat_single_tool_call_executes_and_feeds_result_back(client, auth_headers, monkeypatch):
    call = _FakeFunctionCall("call_1", "get_supported_currencies", "{}")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="FinAssist supports 15 currencies."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "What currencies do you support?",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    assert response.get_json()["response"] == "FinAssist supports 15 currencies."
    assert len(fake.responses.calls) == 2

    # The second API call must include the tool's structured result.
    second_input = fake.responses.calls[1]["input"]
    tool_output = _find_function_call_output(second_input, "call_1")
    assert tool_output is not None
    assert "currencies" in tool_output["result"]

    # Only the real user/assistant turns are persisted — tool-call
    # plumbing never leaks into stored conversation history.
    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert len(history["messages"]) == 2
    assert history["messages"][0]["role"] == "user"
    assert history["messages"][1]["content"] == "FinAssist supports 15 currencies."


def test_chat_persists_only_the_final_natural_language_reply(client, auth_headers, monkeypatch):
    call = _FakeFunctionCall("call_1", "get_supported_currencies", "{}")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="Here they are."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    client.post("/api/chat", headers=auth_headers, json={
        "message": "What currencies do you support?",
        "conversation_id": conversation_id,
    })

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert history["messages"][0]["content"] == "What currencies do you support?"


# --- multiple tool calls in one round ---

def test_chat_handles_multiple_tool_calls_in_one_round(client, auth_headers, monkeypatch):
    call_a = _FakeFunctionCall("call_a", "get_supported_currencies", "{}")
    call_b = _FakeFunctionCall("call_b", "list_subscriptions", "{}")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call_a, call_b]),
        _FakeResponse(output_text="Here's both."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Show me currencies and my subscriptions.",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    assert len(fake.responses.calls) == 2

    second_input = fake.responses.calls[1]["input"]
    assert _find_function_call_output(second_input, "call_a") is not None
    assert _find_function_call_output(second_input, "call_b") is not None


# --- tool errors reach the AI, never silently succeed ---

def test_chat_tool_error_is_fed_back_not_hidden(client, auth_headers, monkeypatch):
    """If the model tries to cancel a subscription that doesn't exist,
    the dispatcher's structured error must reach the (mocked) model in
    the follow-up call — the AI is expected to report the failure, not
    claim success."""
    call = _FakeFunctionCall("call_1", "cancel_subscription", json.dumps({"subscription_id": 999999}))
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="I couldn't find that subscription."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Cancel my Netflix subscription.",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200

    second_input = fake.responses.calls[1]["input"]
    tool_output = _find_function_call_output(second_input, "call_1")
    assert tool_output["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


def test_chat_unknown_tool_name_handled_safely(client, auth_headers, monkeypatch):
    call = _FakeFunctionCall("call_1", "wire_transfer_money", "{}")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="I can't do that."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Wire $500 to my landlord.",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200

    second_input = fake.responses.calls[1]["input"]
    tool_output = _find_function_call_output(second_input, "call_1")
    assert tool_output["error"]["code"] == "UNKNOWN_TOOL"


def test_chat_malformed_tool_arguments_handled_safely(client, auth_headers, monkeypatch):
    call = _FakeFunctionCall("call_1", "get_subscription_details", "{not valid json")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="Something went wrong looking that up."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Tell me about my subscription.",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200

    second_input = fake.responses.calls[1]["input"]
    tool_output = _find_function_call_output(second_input, "call_1")
    assert tool_output["error"]["code"] == "INVALID_ARGUMENTS"


# --- ownership: the model can never reach another user's data via chat ---

def test_chat_tool_call_is_scoped_to_the_authenticated_user(client, auth_headers, other_auth_headers, monkeypatch):
    client.post("/api/subscriptions", headers=other_auth_headers, json={
        "name": "Theirs", "amount": 100, "currency": "NGN",
        "frequency": "monthly", "next_billing_date": "2026-10-15",
    })

    call = _FakeFunctionCall("call_1", "list_subscriptions", "{}")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="You have no subscriptions yet."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    client.post("/api/chat", headers=auth_headers, json={
        "message": "What subscriptions do I have?",
        "conversation_id": conversation_id,
    })

    second_input = fake.responses.calls[1]["input"]
    tool_output = _find_function_call_output(second_input, "call_1")
    assert tool_output["result"]["subscriptions"] == []


# --- runaway loop protection ---

def test_chat_tool_loop_has_a_maximum(client, auth_headers, monkeypatch):
    """A model that keeps requesting tool calls forever must not hang
    the request — the loop stops after MAX_TOOL_ROUNDS rounds and a
    safe fallback message is returned instead of looping forever."""
    call = _FakeFunctionCall("call_x", "get_supported_currencies", "{}")
    # One initial response + one follow-up per round, all requesting
    # another tool call and never producing a final text answer.
    responses = [_FakeResponse(output=[call]) for _ in range(MAX_TOOL_ROUNDS + 1)]
    fake = _QueueingOpenAIClient(responses)
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Keep going forever.",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    assert "wasn't able to finish" in response.get_json()["response"]

    # Exactly MAX_TOOL_ROUNDS + 1 calls: the initial call plus one
    # follow-up per executed round; the model's request for yet another
    # round after the limit is reached is never acted on.
    assert len(fake.responses.calls) == MAX_TOOL_ROUNDS + 1


def test_chat_tool_loop_stops_normally_well_under_the_maximum(client, auth_headers, monkeypatch):
    """A short, well-behaved tool chain (well under MAX_TOOL_ROUNDS)
    must finish normally without ever hitting the fallback message."""
    call = _FakeFunctionCall("call_1", "get_supported_currencies", "{}")
    fake = _QueueingOpenAIClient([
        _FakeResponse(output=[call]),
        _FakeResponse(output_text="All good."),
    ])
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Quick question.",
        "conversation_id": conversation_id,
    })
    assert response.get_json()["response"] == "All good."
    assert len(fake.responses.calls) == 2
