import json
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from openai import OpenAI, OpenAIError

from config import Config
from extensions import db
from models import Conversation, Message, UploadFile
from spaces import generate_signed_url

chat_routes = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)

CHAT_MODEL = "gpt-5.6-luna"

SIGNED_URL_EXPIRATION = 300

MAX_MESSAGE_LENGTH = 20_000

# How many of the most recent messages in a conversation are sent to OpenAI as context.
CHAT_CONTEXT_MESSAGE_LIMIT = 20

FILE_ONLY_GUIDANCE = (
    "The user has attached a document without additional text. Use the "
    "preceding conversation to understand the likely purpose of the "
    "attachment, but inspect the actual document contents to determine "
    "what it is; do not assume its type from the conversation or its "
    "filename. If the preceding conversation clearly establishes the "
    "requested task, continue that task using the attached document. Do "
    "not ask the user to repeat an instruction that is already clear "
    "from the conversation. If the document is clearly understandable "
    "but no task was established, give a useful, concise analysis "
    "appropriate to what it actually is. If the document or the intended "
    "task is genuinely unclear, ask a concise clarification question "
    "rather than guessing."
)


def get_openai_client():
    """ The OpenAI client for this request.
    """
    return OpenAI(api_key=Config.OPEN_AI_KEY)


def _serialize_content(content):
    """`Message.content` is a plain Text column. A normal text message is
    stored as-is; a message that also carries a file (a {text, file_id}
    dict) is stored as a JSON string, since a Python dict can't be bound
    directly to a Text column."""
    if isinstance(content, str):
        return content
    return json.dumps(content)


def _deserialize_content(raw):
    """Reverses `_serialize_content`. Only attempts JSON-decoding values
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


def _parse_positive_id(value):
    """
    Real clients don't always send a clean JSON int: a Dart `num`/`double`
    round-trip commonly produces "1.0" instead of "1" for the same id, and
    an id sent as a plain numeric string ("1") is also legitimate. Both
    are accepted here. Anything that isn't unambiguously an integer value
    (bools, nested objects/lists, non-integral numbers, empty/garbage
    strings) raises ValueError so the caller can reject it with a 400.
    """
    if isinstance(value, bool):
        raise ValueError("must be an integer")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError("must be an integer")
        parsed = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = int(stripped)
        except ValueError:
            as_float = float(stripped)  # raises ValueError for non-numeric strings
            if not as_float.is_integer():
                raise ValueError("must be an integer")
            parsed = int(as_float)
    else:
        raise ValueError("must be an integer")

    if parsed <= 0:
        raise ValueError("must be positive")

    return parsed


def _reconstruct_message_content(raw_content):
    """
    Only the CURRENT turn's file (resolved separately in chat()) is ever
    attached to the OpenAI request. A historical attachment is not
    re-resolved, re-signed, or re-sent on every later turn: doing so
    would reprocess the same document (and its input-token cost) on
    every single message of a conversation. It's kept as a lightweight
    text reference instead, so the model still knows a document was
    involved at that point without paying to re-read it, and without
    exposing the internal database file_id to the model. The stored
    message itself still keeps the real file_id, so a future "compare
    with the previous statement" feature can selectively re-attach a
    specific historical file by id.
    """
    deserialized = _deserialize_content(raw_content)

    if isinstance(deserialized, dict) and "file_id" in deserialized:
        text = deserialized.get("text") or ""
        note = (
            "[The user previously attached a document here. The "
            "document is not included in the current context window.]"
        )
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


def message_to_dict(message):
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": _deserialize_content(message.content),
        "created_at": message.created_at.isoformat() + "Z",
    }


def generate_title(message, has_attachment):
    """Create a short conversation title from the first turn.
    """
    title = message.strip()

    if not title:
        return "Document Analysis" if has_attachment else "New Conversation"

    # Remove excessive whitespace.
    title = " ".join(title.split())

    # Keep titles short.
    if len(title) > 50:
        title = title[:50].rstrip() + "..."

    return title


def load_system_prompt():
    with open("SYSTEM.MD", "r", encoding="utf-8") as file:
        return file.read()


@chat_routes.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    try:
        try:
            current_user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            logger.warning("Invalid JWT identity")
            return jsonify({"error": "Invalid authentication."}), 401

        data = request.get_json(silent=True)

        if not data:
            return jsonify({"error": "No input provided"}), 400

        message = data.get("message")
        conversation_id = data.get("conversation_id")
        file_id = data.get("file_id")

        if message is None:
            message = ""
        elif isinstance(message, str):
            message = message.strip()
        else:
            return jsonify({"error": "Message must be a string."}), 400

        if len(message) > MAX_MESSAGE_LENGTH:
            return jsonify({"error": "Message is too long."}), 413

        # A file-only turn (no typed text) is valid as long as a file_id
        # was actually supplied — otherwise there is nothing to process.
        has_attachment_attempt = file_id is not None

        if not message and not has_attachment_attempt:
            return jsonify({"error": "No message provided."}), 400

        logger.debug(
            "[chat] user_id=%s message_present=%s message_length=%s",
            current_user_id,
            bool(message),
            len(message),
        )

        if conversation_id is None:
            return jsonify({"error": "conversation_id is required"}), 400

        try:
            conversation_id = _parse_positive_id(conversation_id)
        except ValueError:
            return jsonify({"error": "Invalid conversation_id"}), 400

        conversation = Conversation.query.filter_by(
            id=conversation_id,
            user_id=current_user_id,
        ).first()

        if not conversation:
            return jsonify({"error": "Conversation not found"}), 404

        uploaded_file = None

        if file_id is not None:
            try:
                file_id = _parse_positive_id(file_id)
            except ValueError:
                return jsonify({"error": "Invalid file_id"}), 400

            uploaded_file = UploadFile.query.filter_by(
                id=file_id,
                user_id=current_user_id,
            ).first()

            if not uploaded_file:
                return jsonify({"error": "File not found"}), 404

        # Bounded context: only the most recent N messages are sent to
        # OpenAI, not the entire conversation history. Fetched newest
        # first (with a stable id tie-break) then reversed, so this is a
        # single indexed LIMIT query rather than loading everything and
        # slicing in Python.
        previous_messages = list(reversed(
            Message.query.filter_by(conversation_id=conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(CHAT_CONTEXT_MESSAGE_LIMIT)
            .all()
        ))

        conversation_history = []
        historical_files_skipped = 0

        for previous_message in previous_messages:
            content, was_attachment = _reconstruct_message_content(
                previous_message.content,
            )

            if was_attachment:
                historical_files_skipped += 1

            conversation_history.append({
                "role": previous_message.role,
                "content": content,
            })

        logger.debug(
            "[chat context] selected_messages=%s historical_files_skipped=%s",
            len(previous_messages),
            historical_files_skipped,
        )

        signed_file_url = None

        if uploaded_file:
            try:
                signed_file_url = generate_signed_url(
                    key=uploaded_file.key,
                    expires_in=SIGNED_URL_EXPIRATION,
                )
            except Exception:
                logger.exception(
                    "Failed to generate signed URL for file_id=%s",
                    uploaded_file.id,
                )
                return jsonify({
                    "error": "Could not access the attached file."
                }), 500

        logger.debug("[chat] current_file_attached=%s", bool(signed_file_url))

        # A file attached with no typed text — the model needs guidance
        # (added to `instructions` below, never stored as if the user
        # typed it) to infer intent from the preceding conversation
        # instead of asking the user to repeat themselves.
        is_file_only_turn = bool(signed_file_url) and not message

        if signed_file_url:
            user_content = [
                {"type": "input_text", "text": message},
                {"type": "input_file", "file_url": signed_file_url},
            ]
        else:
            user_content = message

        conversation_history.append({
            "role": "user",
            "content": user_content,
        })

        try:
            system_prompt = load_system_prompt()
        except OSError:
            logger.exception("Failed to load SYSTEM.MD")
            return jsonify({
                "error": "The AI service is not configured correctly."
            }), 500

        effective_instructions = system_prompt

        if is_file_only_turn:
            effective_instructions = f"{system_prompt}\n\n{FILE_ONLY_GUIDANCE}"

        try:
            openai_client = get_openai_client()
            response = openai_client.responses.create(
                model=CHAT_MODEL,
                instructions=effective_instructions,
                input=conversation_history,
            )
        except OpenAIError:
            # Covers the SDK's whole expected-failure family: connection
            # errors, timeouts, rate limits, auth/config problems, and
            # upstream 5xx responses. Anything else is a genuine
            # programming error and should fall through to the generic
            # handler below as a 500, not be reported as an AI outage.
            logger.exception(
                "OpenAI request failed user_id=%s conversation_id=%s file_id=%s",
                current_user_id,
                conversation.id,
                uploaded_file.id if uploaded_file else None,
            )
            return jsonify({
                "error": "The AI service is temporarily unavailable. Please try again."
            }), 502

        ai_response = (getattr(response, "output_text", None) or "").strip()

        if not ai_response:
            logger.error(
                "OpenAI returned empty response user_id=%s conversation_id=%s",
                current_user_id,
                conversation.id,
            )
            return jsonify({
                "error": "The AI returned an empty response."
            }), 502

        # Store the user message. Never store the temporary signed URL —
        # store the file_id instead.
        if uploaded_file:
            stored_user_content = {
                "text": message,
                "file_id": uploaded_file.id,
            }
        else:
            stored_user_content = message

        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            content=_serialize_content(stored_user_content),
        )
        db.session.add(user_message)

        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=ai_response,
        )
        db.session.add(assistant_message)

        if not previous_messages:
            conversation.title = generate_title(message, uploaded_file is not None)

        conversation.updated_at = datetime.now(timezone.utc)

        db.session.commit()

        return jsonify({
            "conversation_id": conversation.id,
            "response": ai_response,
            "message": message_to_dict(assistant_message),
        }), 200

    except Exception:
        db.session.rollback()
        logger.exception("Unexpected error")
        return jsonify({
            "error": "Something went wrong while processing your message."
        }), 500
