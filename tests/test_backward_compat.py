"""Regression tests for the endpoints that existed before this phase of
work. These must keep working exactly as before: auth, JWT, conversations,
and chat (with OpenAI mocked so no real API call is made)."""

import io


def test_register_and_login(client):
    register_response = client.post("/api/register", json={
        "username": "backward",
        "first_name": "Back",
        "last_name": "Ward",
        "email": "backward@example.com",
        "password": "password123",
    })
    assert register_response.status_code == 201

    login_response = client.post("/api/login", json={
        "email": "backward@example.com",
        "password": "password123",
    })
    assert login_response.status_code == 200
    body = login_response.get_json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_get_me_requires_jwt(client, auth_headers):
    response = client.get("/api/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["user"]["username"] == "user_a"

    unauthenticated = client.get("/api/me")
    assert unauthenticated.status_code == 401


def test_conversation_crud(client, auth_headers):
    create_response = client.post("/api/conversations", headers=auth_headers, json={"title": "My chat"})
    assert create_response.status_code == 201
    conversation_id = create_response.get_json()["conversation"]["id"]

    list_response = client.get("/api/conversations", headers=auth_headers)
    assert len(list_response.get_json()["conversations"]) == 1

    get_response = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.get_json()["messages"] == []

    delete_response = client.delete(f"/api/conversations/{conversation_id}", headers=auth_headers)
    assert delete_response.status_code == 200


def test_conversation_ownership_enforced(client, auth_headers, other_auth_headers):
    created = client.post("/api/conversations", headers=auth_headers, json={"title": "Private"}).get_json()
    conversation_id = created["conversation"]["id"]

    response = client.get(f"/api/conversations/{conversation_id}", headers=other_auth_headers)
    assert response.status_code == 404


class _FakeResponse:
    output_text = "Mocked FinAssist reply."
    output = []


class _FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, model, instructions, input, tools=None):
        self.calls.append({
            "model": model,
            "instructions": instructions,
            "input": input,
            "tools": tools,
        })
        return _FakeResponse()


class _FakeOpenAIClient:
    def __init__(self):
        self.responses = _FakeResponses()


def _upload_file(client, headers, filename="statement.pdf", content=b"statement bytes"):
    data = {"file": (io.BytesIO(content), filename)}
    response = client.post(
        "/api/files/upload", headers=headers, data=data, content_type="multipart/form-data"
    )
    return response.get_json()["file"]


def test_chat_sends_message_and_persists_history(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "How much should I save?",
        "conversation_id": conversation_id,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "Mocked FinAssist reply."

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert len(history["messages"]) == 2
    assert history["messages"][0]["role"] == "user"
    assert history["messages"][1]["role"] == "assistant"


def test_chat_with_file_attachment(client, auth_headers, monkeypatch, fake_r2):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "What's in this statement?",
        "conversation_id": conversation_id,
        "file_id": uploaded["id"],
    })
    assert response.status_code == 200

    # OpenAI received a freshly generated signed URL, never a permanent one.
    sent_content = fake_openai.responses.calls[-1]["input"][-1]["content"]
    assert isinstance(sent_content, list)
    file_part = next(part for part in sent_content if part.get("type") == "input_file")
    assert file_part["file_url"].startswith("https://fake-r2.example.com/")

    # The database only ever stores the file_id, never the signed URL.
    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    user_message_content = history["messages"][0]["content"]
    assert user_message_content == {
        "text": "What's in this statement?",
        "file_id": uploaded["id"],
    }


def test_chat_ignores_client_provided_file_url(client, auth_headers, monkeypatch):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Analyze this",
        "conversation_id": conversation_id,
        "file_url": "https://attacker.example.com/whatever.pdf",
    })
    assert response.status_code == 200

    # No file_id was supplied, so the client-provided file_url must be ignored
    # entirely — no attachment should reach OpenAI or be persisted.
    sent_content = fake_openai.responses.calls[-1]["input"][-1]["content"]
    assert sent_content == "Analyze this"

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert history["messages"][0]["content"] == "Analyze this"


def test_chat_rejects_other_users_file_id(client, auth_headers, other_auth_headers, monkeypatch, fake_r2):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    other_users_file = _upload_file(client, other_auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Analyze this",
        "conversation_id": conversation_id,
        "file_id": other_users_file["id"],
    })
    assert response.status_code == 404


def test_chat_accepts_decimal_string_file_id(client, auth_headers, monkeypatch, fake_r2):
    """Regression test: a Dart num/double round-trip commonly serializes an
    id as "1.0" instead of "1". The backend must still resolve it to the
    same file rather than rejecting it as an invalid file_id."""
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Analyze this",
        "conversation_id": conversation_id,
        "file_id": f"{uploaded['id']}.0",
    })
    assert response.status_code == 200


def test_chat_accepts_numeric_string_and_float_ids(client, auth_headers, monkeypatch, fake_r2):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Analyze this",
        "conversation_id": str(conversation_id),
        "file_id": float(uploaded["id"]),
    })
    assert response.status_code == 200


def test_chat_rejects_malformed_file_id_shape(client, auth_headers, monkeypatch):
    """A nested object instead of a scalar id is a genuinely malformed
    request and must still be rejected — this is not the same bug as the
    decimal-string case above and must not be silently accepted."""
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "Analyze this",
        "conversation_id": conversation_id,
        "file_id": {"id": 1, "filename": "statement.pdf"},
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "Invalid file_id"


def test_chat_missing_message_and_missing_file_id_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "No message provided."


def test_chat_file_only_message_omitted_succeeds(client, auth_headers, monkeypatch, fake_r2):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "file_id": uploaded["id"],
    })
    assert response.status_code == 200

    # Stored message must carry file_id and empty text — never a fake
    # user instruction like "Analyze this document."
    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert history["messages"][0]["content"] == {"text": "", "file_id": uploaded["id"]}

    # The guidance is only ever added to `instructions`, never persisted
    # and never inserted into the user's stored/sent content as fake text.
    sent_content = fake_openai.responses.calls[-1]["input"][-1]["content"]
    text_part = next(p for p in sent_content if p["type"] == "input_text")
    assert text_part["text"] == ""

    instructions = fake_openai.responses.calls[-1]["instructions"]
    assert "attached a document without additional text" in instructions


def test_chat_file_only_message_empty_string_succeeds(client, auth_headers, monkeypatch, fake_r2):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "",
        "file_id": uploaded["id"],
    })
    assert response.status_code == 200

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert history["messages"][0]["content"] == {"text": "", "file_id": uploaded["id"]}


def test_chat_file_only_message_whitespace_succeeds(client, auth_headers, monkeypatch, fake_r2):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "   \n  ",
        "file_id": uploaded["id"],
    })
    assert response.status_code == 200

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert history["messages"][0]["content"] == {"text": "", "file_id": uploaded["id"]}


def test_chat_rejects_other_users_conversation_id(client, auth_headers, other_auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    other_users_conversation_id = client.post(
        "/api/conversations", headers=other_auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "hello",
        "conversation_id": other_users_conversation_id,
    })
    assert response.status_code == 404


def test_chat_file_only_uses_preceding_conversation_context(client, auth_headers, monkeypatch, fake_r2):
    """The AI must receive the full prior conversation alongside a
    file-only turn, not just the bare attachment, so it can infer why the
    document was uploaded (e.g. it was requested in a prior assistant
    turn)."""
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    setup = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "Help me understand my spending.",
    })
    assert setup.status_code == 200

    uploaded = _upload_file(client, auth_headers)

    file_only = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "file_id": uploaded["id"],
    })
    assert file_only.status_code == 200

    sent_input = fake_openai.responses.calls[-1]["input"]
    # Prior turns (user's setup message + assistant's reply) precede the
    # new file-only turn — history isn't dropped just because the current
    # message has no text.
    assert len(sent_input) == 3
    assert sent_input[0]["content"] == "Help me understand my spending."
    assert sent_input[1]["role"] == "assistant"

    file_only_turn = sent_input[2]
    assert file_only_turn["role"] == "user"
    text_part = next(p for p in file_only_turn["content"] if p["type"] == "input_text")
    assert text_part["text"] == ""

    instructions = fake_openai.responses.calls[-1]["instructions"]
    assert "attached a document without additional text" in instructions


def test_chat_does_not_resend_historical_attachment(client, auth_headers, monkeypatch, fake_r2):
    """Only the CURRENT turn's file is ever attached. A file referenced by
    a historical message must not be re-signed or re-sent on a later
    turn — that would reprocess the same document (and its input-token
    cost) on every single message of the conversation. It's kept only as
    a lightweight text reference so the model still knows a document was
    involved."""
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    first = client.post("/api/chat", headers=auth_headers, json={
        "message": "What's in this statement?",
        "conversation_id": conversation_id,
        "file_id": uploaded["id"],
    })
    assert first.status_code == 200
    assert len(fake_r2.presign_calls) == 1  # signed exactly once, for the current turn

    second = client.post("/api/chat", headers=auth_headers, json={
        "message": "Summarize the top expense category.",
        "conversation_id": conversation_id,
    })
    assert second.status_code == 200

    # No new signed URL was generated for the old attachment.
    assert len(fake_r2.presign_calls) == 1

    second_call_history = fake_openai.responses.calls[1]["input"]
    historical_turn = second_call_history[0]

    assert historical_turn["role"] == "user"
    # The historical turn is plain text context, not a re-attached file.
    assert isinstance(historical_turn["content"], str)
    assert "What's in this statement?" in historical_turn["content"]
    assert "not included in the current context window" in historical_turn["content"]
    # The internal database file_id must never be exposed to the model.
    assert str(uploaded["id"]) not in historical_turn["content"]
    assert "input_file" not in historical_turn["content"]

    # The database record itself is untouched by any of this.
    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert history["messages"][0]["content"] == {
        "text": "What's in this statement?",
        "file_id": uploaded["id"],
    }


def test_chat_context_within_limit_sends_everything(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    for i in range(3):
        response = client.post("/api/chat", headers=auth_headers, json={
            "conversation_id": conversation_id,
            "message": f"message {i}",
        })
        assert response.status_code == 200

    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    final = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "final message",
    })
    assert final.status_code == 200

    # 3 prior turns x 2 messages each = 6 historical + 1 current = 7.
    sent_input = fake_openai.responses.calls[-1]["input"]
    assert len(sent_input) == 7
    assert sent_input[0]["content"] == "message 0"
    assert sent_input[-1]["content"] == "final message"


def test_chat_context_bounded_to_recent_messages_only(client, auth_headers, monkeypatch):
    """A long conversation must not resend its entire history — only the
    most recent CHAT_CONTEXT_MESSAGE_LIMIT messages, in chronological
    order, plus the current turn."""
    from services import chat_service

    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    prior_calls = 24
    for i in range(prior_calls):
        response = client.post("/api/chat", headers=auth_headers, json={
            "conversation_id": conversation_id,
            "message": f"message {i}",
        })
        assert response.status_code == 200

    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    final = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "final message",
    })
    assert final.status_code == 200

    sent_input = fake_openai.responses.calls[-1]["input"]
    limit = chat_service.CHAT_CONTEXT_MESSAGE_LIMIT
    assert limit == 20

    # limit historical messages + 1 current turn.
    assert len(sent_input) == limit + 1

    # 2 stored messages per prior call; the oldest surviving one after
    # keeping only the latest `limit` is call number (prior_calls - limit/2).
    oldest_expected_call = prior_calls - (limit // 2)
    assert sent_input[0]["content"] == f"message {oldest_expected_call}"
    assert sent_input[-1]["content"] == "final message"

    # Selected messages remain in chronological order.
    ordered_calls = [
        entry["content"] for entry in sent_input
        if isinstance(entry["content"], str) and entry["content"].startswith("message ")
    ]
    numbers = [int(text.split(" ")[1]) for text in ordered_calls]
    assert numbers == sorted(numbers)


def test_chat_current_message_and_file_not_duplicated(client, auth_headers, monkeypatch, fake_r2):
    fake_openai = _FakeOpenAIClient()
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: fake_openai)

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "earlier message",
    })

    uploaded = _upload_file(client, auth_headers)
    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "Find unusual transactions.",
        "file_id": uploaded["id"],
    })
    assert response.status_code == 200

    sent_input = fake_openai.responses.calls[-1]["input"]

    # The current message text appears exactly once in the OpenAI input.
    occurrences = sum(
        1 for entry in sent_input
        if entry["content"] == "Find unusual transactions."
        or (
            isinstance(entry["content"], list)
            and any(
                part.get("type") == "input_text" and part.get("text") == "Find unusual transactions."
                for part in entry["content"]
            )
        )
    )
    assert occurrences == 1

    # Exactly one input_file part across the whole request (the current
    # file), not one per historical reference.
    file_parts = [
        part
        for entry in sent_input
        if isinstance(entry["content"], list)
        for part in entry["content"]
        if part.get("type") == "input_file"
    ]
    assert len(file_parts) == 1
    assert len(fake_r2.presign_calls) == 1


def test_plain_text_conversation_without_attachments_still_works(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    first = client.post("/api/chat", headers=auth_headers, json={
        "message": "Hello there",
        "conversation_id": conversation_id,
    })
    assert first.status_code == 200

    second = client.post("/api/chat", headers=auth_headers, json={
        "message": "Follow up question",
        "conversation_id": conversation_id,
    })
    assert second.status_code == 200

    history = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert len(history["messages"]) == 4


def test_chat_requires_existing_conversation(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    response = client.post("/api/chat", headers=auth_headers, json={
        "message": "hello",
        "conversation_id": 999999,
    })
    assert response.status_code == 404


class _RaisingResponses:
    def __init__(self, exc):
        self._exc = exc

    def create(self, model, instructions, input, tools=None):
        raise self._exc


class _RaisingOpenAIClient:
    def __init__(self, exc):
        self.responses = _RaisingResponses(exc)


def test_chat_openai_service_failure_returns_502(client, auth_headers, monkeypatch):
    """An expected OpenAI SDK failure (connection error, timeout, rate
    limit, etc.) must be reported as an upstream 502, not a generic 500."""
    import httpx2
    import openai

    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    openai_error = openai.APIConnectionError(request=request)

    monkeypatch.setattr(
        "services.ai_service.get_openai_client",
        lambda: _RaisingOpenAIClient(openai_error),
    )

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "How much did I spend?",
    })
    assert response.status_code == 502
    assert "temporarily unavailable" in response.get_json()["error"]


def test_chat_unexpected_error_returns_500_not_502(client, auth_headers, monkeypatch):
    """A genuine programming error inside the OpenAI call path (anything
    that isn't an openai.OpenAIError) must NOT be disguised as an OpenAI
    service outage — it should surface as the generic 500."""
    monkeypatch.setattr(
        "services.ai_service.get_openai_client",
        lambda: _RaisingOpenAIClient(RuntimeError("boom")),
    )

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "How much did I spend?",
    })
    assert response.status_code == 500
    body = response.get_json()
    assert "temporarily unavailable" not in body["error"]
    assert "Something went wrong" in body["error"]


def test_chat_file_only_first_turn_gets_document_title(client, auth_headers, monkeypatch, fake_r2):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "file_id": uploaded["id"],
    })
    assert response.status_code == 200

    conversation = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert conversation["conversation"]["title"] == "Document Analysis"


def test_chat_text_first_turn_title_unaffected(client, auth_headers, monkeypatch):
    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]

    response = client.post("/api/chat", headers=auth_headers, json={
        "conversation_id": conversation_id,
        "message": "How much did I spend on groceries?",
    })
    assert response.status_code == 200

    conversation = client.get(f"/api/conversations/{conversation_id}", headers=auth_headers).get_json()
    assert conversation["conversation"]["title"] == "How much did I spend on groceries?"


def test_chat_logs_exclude_sensitive_content(client, auth_headers, monkeypatch, fake_r2, caplog):
    import logging

    monkeypatch.setattr("services.ai_service.get_openai_client", lambda: _FakeOpenAIClient())

    conversation_id = client.post(
        "/api/conversations", headers=auth_headers, json={}
    ).get_json()["conversation"]["id"]
    uploaded = _upload_file(client, auth_headers)

    secret_message = "My account number is 0123456789 and I earn a very specific salary."

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/chat", headers=auth_headers, json={
            "conversation_id": conversation_id,
            "message": secret_message,
            "file_id": uploaded["id"],
        })
    assert response.status_code == 200

    all_log_text = "\n".join(record.getMessage() for record in caplog.records)

    assert secret_message not in all_log_text
    assert auth_headers["Authorization"].split(" ")[1] not in all_log_text
    assert "fake-r2.example.com" not in all_log_text

    from config import Config
    if Config.OPEN_AI_KEY:
        assert Config.OPEN_AI_KEY not in all_log_text
