"""The /api/chat request workflow: conversation/attachment resolution,
tool_context handling, the OpenAI turn (via services.ai_service), and
persisting the resulting messages.

chat_routes.py is a thin controller that calls `process_chat` and maps
`ChatServiceError` to its existing flat `{"error": "..."}"` response
shape — every message/status pair below is exactly what the route used
to return directly, just raised instead of returned so this module has
no Flask/response coupling of its own.
"""
import json
import logging
from datetime import datetime, timezone

from openai import OpenAIError

from extensions import db
from models import Conversation, Message, UploadFile
from services import ai_service
from services.conversation_service import generate_title, message_to_dict, reconstruct_message_content, serialize_content
from spaces import generate_signed_url
from tools import TOOLS
from utils import get_owned, parse_positive_id

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

# A "tool_context" is a normalized result already computed by one of
# FinAssist's deterministic Tools calculators (see tools_routes.py /
# services/tools/*), attached when the user taps "Ask FinAssist" on a
# result card. See SYSTEM.MD's "TOOL RESULTS" section for the standing
# policy; this is the per-request reinforcement plus the guidance for
# the specific case where no question was typed.
TOOL_CONTEXT_TYPE = "financial_tool_result"
MAX_TOOL_CONTEXT_BYTES = 20_000

TOOL_CONTEXT_GUIDANCE = (
    "The message below includes a tool_context: a structured result "
    "already computed by FinAssist's deterministic Tools system, not by "
    "you. Treat its `result` values as authoritative — do not "
    "recalculate them, do not change any number in them, and do not "
    "imply you personally performed the calculation. You may explain "
    "it, interpret it, and answer follow-up questions using it; clearly "
    "label anything in `metadata` marked as an estimate or assumption "
    "as such rather than as fact. Only perform new calculations if the "
    "user asks for something beyond what tool_context already contains, "
    "and say clearly when you do."
)

TOOL_CONTEXT_ONLY_GUIDANCE = (
    "The user attached this tool_context without typing a question. "
    "Give a concise, useful explanation of the result — what it means "
    "and anything worth noting about its assumptions — rather than "
    "asking what they want to know."
)

# Shown to the user only if the model-driven tool-calling loop (see
# services.ai_service.run_tool_loop) hits MAX_TOOL_ROUNDS without ever
# reaching a final text answer. This should be rare in practice; it
# exists purely as a safe stop so a pathological chain of tool calls
# can never hang the request or loop forever.
TOOL_LOOP_LIMIT_FALLBACK_MESSAGE = (
    "I wasn't able to finish that using the available tools just now. "
    "Could you try again, or let me know if you'd like to rephrase the request?"
)


class ChatServiceError(Exception):
    """Raised for every expected /api/chat failure mode. `status` and
    `message` are exactly what chat_routes.py returns as
    `jsonify({"error": message}), status` — preserving the endpoint's
    existing flat error-response contract."""
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _validate_tool_context(value):
    """Returns the cleaned tool_context dict, or None if not supplied.
    Raises ValueError with a user-facing message on malformed input."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("tool_context must be an object.")
    if value.get("type") != TOOL_CONTEXT_TYPE:
        raise ValueError(f"tool_context.type must be '{TOOL_CONTEXT_TYPE}'.")
    if not isinstance(value.get("tool"), str) or not value["tool"].strip():
        raise ValueError("tool_context.tool is required.")
    if not isinstance(value.get("version"), str) or not value["version"].strip():
        raise ValueError("tool_context.version is required.")
    if not isinstance(value.get("inputs"), dict):
        raise ValueError("tool_context.inputs must be an object.")
    if not isinstance(value.get("result"), dict):
        raise ValueError("tool_context.result must be an object.")
    metadata = value.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("tool_context.metadata must be an object.")
    try:
        size = len(json.dumps(value))
    except (TypeError, ValueError):
        raise ValueError("tool_context is not serializable.")
    if size > MAX_TOOL_CONTEXT_BYTES:
        raise ValueError("tool_context is too large.")
    return value


def _format_tool_context_block(tool_context):
    return f"{TOOL_CONTEXT_GUIDANCE}\n\n{json.dumps(tool_context)}"


def process_chat(user_id, data):
    """Runs one /api/chat turn end-to-end and returns the plain result
    dict for the route to `jsonify(...), 200`. Raises ChatServiceError
    on every expected failure; any other exception is a genuine bug and
    is left to the route's generic 500 handler."""
    message = data.get("message")
    conversation_id = data.get("conversation_id")
    file_id = data.get("file_id")

    try:
        tool_context = _validate_tool_context(data.get("tool_context"))
    except ValueError as exc:
        raise ChatServiceError(400, str(exc))

    if message is None:
        message = ""
    elif isinstance(message, str):
        message = message.strip()
    else:
        raise ChatServiceError(400, "Message must be a string.")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise ChatServiceError(413, "Message is too long.")

    # A file-only or tool-context-only turn (no typed text) is valid
    # as long as one of them was actually supplied — otherwise there
    # is nothing to process.
    has_context_attempt = file_id is not None or tool_context is not None

    if not message and not has_context_attempt:
        raise ChatServiceError(400, "No message provided.")

    logger.debug(
        "[chat] user_id=%s message_present=%s message_length=%s",
        user_id,
        bool(message),
        len(message),
    )

    if conversation_id is None:
        raise ChatServiceError(400, "conversation_id is required")

    try:
        conversation_id = parse_positive_id(conversation_id)
    except ValueError:
        raise ChatServiceError(400, "Invalid conversation_id")

    conversation = get_owned(Conversation, conversation_id, user_id)

    if not conversation:
        raise ChatServiceError(404, "Conversation not found")

    uploaded_file = None

    if file_id is not None:
        try:
            file_id = parse_positive_id(file_id)
        except ValueError:
            raise ChatServiceError(400, "Invalid file_id")

        uploaded_file = get_owned(UploadFile, file_id, user_id)

        if not uploaded_file:
            raise ChatServiceError(404, "File not found")

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
        content, was_attachment = reconstruct_message_content(
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
            raise ChatServiceError(500, "Could not access the attached file.")

    logger.debug("[chat] current_file_attached=%s", bool(signed_file_url))
    logger.debug("[chat] tool_context_attached=%s", bool(tool_context))

    # A file/tool_context attached with no typed text — the model
    # needs guidance (added to `instructions` below, never stored as
    # if the user typed it) to infer intent from the preceding
    # conversation instead of asking the user to repeat themselves.
    is_file_only_turn = bool(signed_file_url) and not message and not tool_context
    is_tool_context_only_turn = bool(tool_context) and not message

    if signed_file_url or tool_context:
        user_content = [{"type": "input_text", "text": message}]
        if tool_context:
            user_content.append(
                {"type": "input_text", "text": _format_tool_context_block(tool_context)}
            )
        if signed_file_url:
            user_content.append({"type": "input_file", "file_url": signed_file_url})
    else:
        user_content = message

    conversation_history.append({
        "role": "user",
        "content": user_content,
    })

    try:
        system_prompt = ai_service.load_system_prompt()
    except OSError:
        logger.exception("Failed to load SYSTEM.MD")
        raise ChatServiceError(500, "The AI service is not configured correctly.")

    extra_guidance = []
    if is_file_only_turn:
        extra_guidance.append(FILE_ONLY_GUIDANCE)
    if is_tool_context_only_turn:
        extra_guidance.append(TOOL_CONTEXT_ONLY_GUIDANCE)

    effective_instructions = system_prompt
    if extra_guidance:
        effective_instructions = "\n\n".join([system_prompt, *extra_guidance])

    try:
        openai_client = ai_service.get_openai_client()
        response = openai_client.responses.create(
            model=CHAT_MODEL,
            instructions=effective_instructions,
            input=conversation_history,
            tools=TOOLS,
        )
        # If the model requested one or more tools (subscriptions,
        # currency, reminders — see tools.py), run the dispatcher and
        # feed each result back until the model produces a final
        # text answer, up to MAX_TOOL_ROUNDS rounds. A plain response
        # with no tool call returns immediately with tool_round_limit
        # _reached=False, so the common case costs nothing extra.
        response, tool_round_limit_reached = ai_service.run_tool_loop(
            openai_client,
            CHAT_MODEL,
            effective_instructions,
            conversation_history,
            response,
            user_id,
        )
    except OpenAIError:
        # Covers the SDK's whole expected-failure family: connection
        # errors, timeouts, rate limits, auth/config problems, and
        # upstream 5xx responses. Anything else is a genuine
        # programming error and should fall through to the generic
        # handler below as a 500, not be reported as an AI outage.
        logger.exception(
            "OpenAI request failed user_id=%s conversation_id=%s file_id=%s",
            user_id,
            conversation.id,
            uploaded_file.id if uploaded_file else None,
        )
        raise ChatServiceError(502, "The AI service is temporarily unavailable. Please try again.")

    ai_response = (getattr(response, "output_text", None) or "").strip()

    if not ai_response:
        if tool_round_limit_reached:
            # A safe, user-facing stop rather than an error: the tool
            # loop hit MAX_TOOL_ROUNDS without the model ever
            # producing a final text answer. This should be rare.
            logger.warning(
                "Tool loop reached MAX_TOOL_ROUNDS without a final "
                "answer user_id=%s conversation_id=%s",
                user_id,
                conversation.id,
            )
            ai_response = TOOL_LOOP_LIMIT_FALLBACK_MESSAGE
        else:
            logger.error(
                "OpenAI returned empty response user_id=%s conversation_id=%s",
                user_id,
                conversation.id,
            )
            raise ChatServiceError(502, "The AI returned an empty response.")

    # Store the user message. Never store the temporary signed URL —
    # store the file_id instead.
    if uploaded_file or tool_context:
        stored_user_content = {"text": message}
        if uploaded_file:
            stored_user_content["file_id"] = uploaded_file.id
        if tool_context:
            stored_user_content["tool_context"] = tool_context
    else:
        stored_user_content = message

    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=serialize_content(stored_user_content),
    )
    db.session.add(user_message)

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=ai_response,
    )
    db.session.add(assistant_message)

    if not previous_messages:
        conversation.title = generate_title(
            message,
            uploaded_file is not None,
            tool_context.get("tool") if tool_context else None,
        )

    conversation.updated_at = datetime.now(timezone.utc)

    db.session.commit()

    return {
        "conversation_id": conversation.id,
        "response": ai_response,
        "message": message_to_dict(assistant_message),
    }
