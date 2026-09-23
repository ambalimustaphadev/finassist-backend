"""Business logic for conversations and their messages.

Mirrors the shape of subscription_service.py: plain functions, no
Flask/request coupling. Houses the canonical `Message.content`
serialize/deserialize contract — previously duplicated independently
in both chat_routes.py and conversation_routes.py — plus the
conversation CRUD conversation_routes.py used to do entirely inline.

services/chat_service.py imports the serialization helpers, plus
`generate_title`/`reconstruct_message_content` below, from here; it
keeps its own request-flow-specific logic (bounded history windowing,
the tool-calling loop, tool_context handling) inline, since that's
specific to how a chat turn is processed, not generic conversation
data access.
"""
import json

from extensions import db
from models import Conversation, Message


def serialize_content(content):
    """`Message.content` is a plain Text column. A normal text message
    is stored as-is; a message that also carries a file (a {text,
    file_id} dict) is stored as a JSON string, since a Python dict
    can't be bound directly to a Text column."""
    if isinstance(content, str):
        return content
    return json.dumps(content)


def deserialize_content(raw):
    """Reverses `serialize_content`. Only attempts JSON-decoding values
    that look like a JSON array/object, so an ordinary text message is
    never misinterpreted (e.g. one that happens to just be the digit
    "5", which is itself valid JSON)."""
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw
    return raw


def conversation_to_dict(conversation):
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat() + "Z",
        "updated_at": conversation.updated_at.isoformat() + "Z",
    }


def message_to_dict(message):
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": deserialize_content(message.content),
        "created_at": message.created_at.isoformat() + "Z",
    }


def list_conversations(user_id):
    return (
        Conversation.query.filter_by(user_id=user_id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )


def create_conversation(user_id, title):
    """`title` is the raw client-supplied value (or the "New
    Conversation" default already substituted by the caller when the
    field was absent) — stripped, and re-defaulted if that leaves it
    empty."""
    title = str(title).strip()
    if not title:
        title = "New Conversation"

    conversation = Conversation(user_id=user_id, title=title)
    db.session.add(conversation)
    db.session.commit()
    return conversation


def get_messages(conversation_id):
    return (
        Message.query.filter_by(conversation_id=conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )


def delete_conversation(conversation):
    db.session.delete(conversation)
    db.session.commit()


def reconstruct_message_content(raw_content):
    """
    Only the CURRENT turn's file/tool_context (resolved separately by
    chat_service.process_chat) is ever attached to the OpenAI request. A
    historical attachment is not re-resolved, re-signed, or re-sent on
    every later turn: doing so would reprocess the same document (and
    its input-token cost) on every single message of a conversation.
    It's kept as a lightweight text reference instead, so the model
    still knows an attachment was involved at that point without paying
    to re-read it, and without exposing the internal database file_id
    to the model. The stored message itself still keeps the real
    file_id (or tool_context), so a future "compare with the previous
    statement" feature can selectively re-attach a specific historical
    item.
    """
    deserialized = deserialize_content(raw_content)

    if isinstance(deserialized, dict) and ("file_id" in deserialized or "tool_context" in deserialized):
        text = deserialized.get("text") or ""
        notes = []
        if "file_id" in deserialized:
            notes.append(
                "[The user previously attached a document here. The "
                "document is not included in the current context window.]"
            )
        if "tool_context" in deserialized:
            tool_name = (deserialized.get("tool_context") or {}).get("tool", "a financial tool")
            notes.append(
                f"[The user previously shared a {tool_name} result here. "
                "The full structured data is not repeated in this "
                "context window; refer to your earlier reply for the "
                "figures.]"
            )
        note = " ".join(notes)
        content = f"{text}\n\n{note}" if text else note
        return content, True

    if isinstance(deserialized, list):
        # Legacy rows created before attachments were stored as file_id
        # may still carry a stale/expired file_url part with no file_id
        # to reference. Keep only the text.
        text_parts = [
            part.get("text", "")
            for part in deserialized
            if isinstance(part, dict) and part.get("type") == "input_text"
        ]
        return "\n".join(part for part in text_parts if part), True

    return deserialized, False


def generate_title(message, has_attachment, tool_name=None):
    """Create a short conversation title from the first turn.
    """
    title = message.strip()

    if not title:
        if tool_name:
            return f"{tool_name.replace('_', ' ').title()} Result"
        return "Document Analysis" if has_attachment else "New Conversation"

    # Remove excessive whitespace.
    title = " ".join(title.split())

    # Keep titles short.
    if len(title) > 50:
        title = title[:50].rstrip() + "..."

    return title
