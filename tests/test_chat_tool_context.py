"""Tests for the /api/chat tool_context extension (the chat handoff
for FinAssist's deterministic Tools). OpenAI is always mocked — these
tests must never depend on a real AI call."""


class _FakeResponse:
    output_text = "Mocked FinAssist reply."
    output = []


class _FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, model, instructions, input, tools=None):
        self.calls.append({
            "model": model, "instructions": instructions, "input": input, "tools": tools,
        })
        return _FakeResponse()


class _FakeOpenAIClient:
    def __init__(self):
        self.responses = _FakeResponses()


def _valid_tool_context(**overrides):
    context = {
        "type": "financial_tool_result",
        "tool": "loan_calculator",
        "version": "1",
        "inputs": {"loan_amount": "1000000", "annual_interest_rate": "18"},
        "result": {"periodic_payment": "91679.99", "total_interest": "100159.91"},
        "metadata": {"currency": "NGN", "is_estimate": True},
    }
    context.update(overrides)
    return context


def _new_conversation(client, headers):
    return client.post("/api/conversations", headers=headers, json={}).get_json()["conversation"]["id"]


def test_tool_context_accepted_with_message(client, auth_headers, monkeypatch):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Is this affordable for me?",
        "conversation_id": conversation_id,
        "tool_context": _valid_tool_context(),
    })
    assert response.status_code == 200

    sent_content = fake_openai.responses.calls[-1]["input"][-1]["content"]
    assert isinstance(sent_content, list)
    assert sent_content[0] == {"type": "input_text", "text": "Is this affordable for me?"}
    tool_block = sent_content[1]["text"]
    assert "loan_calculator" in tool_block
    assert "91679.99" in tool_block
    assert "do not recalculate" in tool_block.lower()


def test_empty_message_with_tool_context_is_valid(client, auth_headers, monkeypatch):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "",
        "conversation_id": conversation_id,
        "tool_context": _valid_tool_context(),
    })
    assert response.status_code == 200

    # tool-context-only guidance should be added to the instructions.
    instructions = fake_openai.responses.calls[-1]["instructions"]
    assert "without typing a question" in instructions


def test_tool_context_persisted_and_returned_in_history(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)
    context = _valid_tool_context()

    client.post("/api/chat", headers=auth_headers, json={
        "message": "Explain this",
        "conversation_id": conversation_id,
        "tool_context": context,
    })

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    user_message = history["messages"][0]
    assert user_message["content"] == {"text": "Explain this", "tool_context": context}


def test_historical_tool_context_not_resent_on_later_turns(client, auth_headers, monkeypatch):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)
    conversation_id = _new_conversation(client, auth_headers)

    client.post("/api/chat", headers=auth_headers, json={
        "message": "Explain this",
        "conversation_id": conversation_id,
        "tool_context": _valid_tool_context(),
    })
    client.post("/api/chat", headers=auth_headers, json={
        "message": "What about extra payments?",
        "conversation_id": conversation_id,
    })

    second_call_input = fake_openai.responses.calls[-1]["input"]
    # The first (historical) user turn should now be a placeholder, not
    # the raw structured tool_context JSON.
    first_turn_content = second_call_input[0]["content"]
    assert "loan_calculator" in first_turn_content
    assert '"result"' not in first_turn_content
    assert '"periodic_payment"' not in first_turn_content


def test_malformed_tool_context_missing_type_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)

    context = _valid_tool_context()
    del context["type"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Explain",
        "conversation_id": conversation_id,
        "tool_context": context,
    })
    assert response.status_code == 400


def test_malformed_tool_context_wrong_type_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Explain",
        "conversation_id": conversation_id,
        "tool_context": _valid_tool_context(type="something_else"),
    })
    assert response.status_code == 400


def test_malformed_tool_context_not_an_object_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Explain",
        "conversation_id": conversation_id,
        "tool_context": "not-an-object",
    })
    assert response.status_code == 400


def test_malformed_tool_context_missing_result_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)

    context = _valid_tool_context()
    del context["result"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Explain",
        "conversation_id": conversation_id,
        "tool_context": context,
    })
    assert response.status_code == 400


def test_no_message_and_no_tool_context_and_no_file_still_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 400


def test_tool_identifier_and_version_reach_ai_layer(client, auth_headers, monkeypatch):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)
    conversation_id = _new_conversation(client, auth_headers)

    client.post("/api/chat", headers=auth_headers, json={
        "message": "",
        "conversation_id": conversation_id,
        "tool_context": _valid_tool_context(tool="affordability_calculator", version="1"),
    })

    sent_content = fake_openai.responses.calls[-1]["input"][-1]["content"]
    tool_block = sent_content[1]["text"]
    assert '"tool": "affordability_calculator"' in tool_block
    assert '"version": "1"' in tool_block


def test_conversation_title_reflects_tool_when_no_message(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())
    conversation_id = _new_conversation(client, auth_headers)

    client.post("/api/chat", headers=auth_headers, json={
        "message": "",
        "conversation_id": conversation_id,
        "tool_context": _valid_tool_context(tool="loan_calculator"),
    })

    conversation = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert conversation["conversation"]["title"] == "Loan Calculator Result"


def test_normal_message_without_tool_context_unaffected(client, auth_headers, monkeypatch):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)
    conversation_id = _new_conversation(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Hello",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    sent_content = fake_openai.responses.calls[-1]["input"][-1]["content"]
    assert sent_content == "Hello"
