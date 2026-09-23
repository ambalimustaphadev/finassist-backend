"""Central registry for FinAssist's AI-chat tool-calling layer.

This is the single place the model's available tools (`TOOLS`) and the
allowlisted handler registry (`_HANDLERS`) are defined. The actual
business logic is never implemented here — every handler is a thin
adapter (see `services/ai_tools/*`) that calls into the existing
subscription service, currency service, or reminder service. See
chat_routes.py for how this is wired into the `/api/chat` tool-calling
loop.

SECURITY
--------
`dispatch_tool_call` receives `user_id` from the caller's trusted
server context (the JWT-authenticated user in chat_routes.py) — never
from the model. Any `user_id` the model puts in its own tool-call
arguments is dropped before the handler ever sees it. Tool names are
resolved through the explicit `_HANDLERS` dict only; there is no
dynamic dispatch (`eval`, `getattr(module, name)`, etc.), so a model
can never invoke anything beyond what's registered here.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from services.ai_tools import currency as currency_tools
from services.ai_tools import reminders as reminder_tools
from services.ai_tools import subscriptions as subscription_tools
from services.ai_tools.errors import ToolError

logger = logging.getLogger(__name__)

# Safety valve against a runaway tool-call loop in chat_routes.py — the
# model gets at most this many rounds of tool calls per user message
# before the loop stops and falls back to whatever text response (or
# safe fallback message) is available.
MAX_TOOL_ROUNDS = 5

# A model-generated tool-call arguments string beyond this size is
# rejected outright rather than parsed — there is no legitimate tool
# call in this registry that needs anywhere near this much input.
_MAX_ARGUMENTS_BYTES = 10_000


# ============================================================
# TOOL DEFINITIONS
# ============================================================
# NOTE ON SHAPE: the app's OpenAI integration (chat_routes.py) uses the
# Responses API (`client.responses.create`), whose function-tool shape
# is FLAT — {"type": "function", "name", "description", "parameters"}
# — not the nested {"type": "function", "function": {...}} shape used
# by the older Chat Completions API. The flat shape is used throughout
# below so these definitions actually work against the API this
# backend calls; using the nested shape here would silently fail to
# register any tools.

_SUBSCRIPTION_ID_PARAM = {
    "type": "integer",
    "description": "The numeric id of the subscription, as returned by a previous subscription tool call.",
}

TOOLS: list[dict[str, Any]] = [
    # --- SUBSCRIPTIONS (read) ---
    {
        "type": "function",
        "name": "list_subscriptions",
        "description": (
            "List the authenticated user's subscriptions, optionally filtered by "
            "status. Use this for broad questions about what subscriptions the "
            "user has, such as 'What subscriptions do I have?', 'Show me my "
            "subscriptions', 'Which subscriptions have I cancelled?', or 'What "
            "subscriptions are paused?'. Do not use this to look up a single "
            "named service — use find_subscription_by_service for that instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "cancelled", "paused"],
                    "description": "Only return subscriptions with this status. Omit to return all statuses.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "find_subscription_by_service",
        "description": (
            "Find the user's subscription(s) matching a service name (partial, "
            "case-insensitive match, e.g. 'net' matches 'Netflix'). Use this when "
            "the user asks about a specific named service, such as 'How much is "
            "Netflix?', 'When does Spotify renew?', 'Do I have Netflix?', or "
            "'What am I paying for Disney?'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "The service name (or part of it) to search for, e.g. 'Netflix'.",
                },
            },
            "required": ["service_name"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_upcoming_renewals",
        "description": (
            "Find the user's active subscriptions that will renew within a given "
            "number of days from today. Use this for questions like 'What renews "
            "this month?', 'What subscriptions will charge me soon?', or 'What "
            "renews in the next 7 days?'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "within_days": {
                    "type": "integer",
                    "description": "How many days ahead to look, starting from today. Defaults to 30. Must be between 1 and 365.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_monthly_spend",
        "description": (
            "Get the user's total recurring subscription spend, normalized to a "
            "monthly amount, using FinAssist's deterministic subscription-cost "
            "calculator. Use this for questions like 'How much do I spend on "
            "subscriptions each month?' or 'What's my total subscription cost?'. "
            "This is an authoritative backend calculation; never estimate or "
            "recompute this total yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_subscription_details",
        "description": (
            "Get the full details of one specific subscription by its id. Only "
            "use this when you already have a subscription_id from a previous "
            "list_subscriptions or find_subscription_by_service call — never "
            "guess or invent an id."
        ),
        "parameters": {
            "type": "object",
            "properties": {"subscription_id": _SUBSCRIPTION_ID_PARAM},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    # --- SUBSCRIPTIONS (write) ---
    {
        "type": "function",
        "name": "add_subscription",
        "description": (
            "Create a new subscription for the authenticated user. Only call "
            "this after an explicit request to add/track a subscription, and "
            "only once you have real values for service_name, price, and "
            "renewal_date — do not invent or guess any of these. If the user "
            "hasn't given you enough information (e.g. they just say 'I "
            "subscribed to Netflix' with no price or date), ask them for the "
            "missing details instead of calling this tool with fabricated values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "The name of the service, e.g. 'Netflix'.",
                },
                "price": {
                    "type": "number",
                    "description": "The subscription price as a positive number, in the given currency.",
                },
                "renewal_date": {
                    "type": "string",
                    "description": "The next billing/renewal date, as an ISO date: YYYY-MM-DD.",
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO currency code for the price, e.g. 'USD' or 'NGN'. "
                        "Optional — if omitted, the user's own account currency is used."
                    ),
                },
                "billing_cycle": {
                    "type": "string",
                    "enum": ["weekly", "monthly", "yearly"],
                    "description": "How often the subscription renews. Optional — defaults to 'monthly' if not stated.",
                },
            },
            "required": ["service_name", "price", "renewal_date"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "update_subscription",
        "description": (
            "Update one or more fields of an existing subscription belonging to "
            "the authenticated user. Only call this for an explicit update "
            "request (e.g. 'change my Netflix price to 8.99' or 'move my Spotify "
            "renewal to the 20th'), and only with a subscription_id already "
            "obtained from a prior tool call. Provide only the fields that are "
            "actually changing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subscription_id": _SUBSCRIPTION_ID_PARAM,
                "service_name": {"type": "string", "description": "New service name."},
                "price": {"type": "number", "description": "New price."},
                "renewal_date": {
                    "type": "string",
                    "description": "New renewal date, as an ISO date: YYYY-MM-DD.",
                },
                "currency": {"type": "string", "description": "New ISO currency code."},
                "billing_cycle": {
                    "type": "string",
                    "enum": ["weekly", "monthly", "yearly"],
                    "description": "New billing cadence.",
                },
            },
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "pause_subscription",
        "description": (
            "Pause an existing subscription belonging to the authenticated user. "
            "Only call this on an explicit instruction to pause (e.g. 'pause my "
            "Netflix subscription'), not on a vague or exploratory statement like "
            "'I might pause Netflix'."
        ),
        "parameters": {
            "type": "object",
            "properties": {"subscription_id": _SUBSCRIPTION_ID_PARAM},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "resume_subscription",
        "description": (
            "Resume a previously paused subscription belonging to the "
            "authenticated user. Only call this on an explicit instruction to "
            "resume/unpause."
        ),
        "parameters": {
            "type": "object",
            "properties": {"subscription_id": _SUBSCRIPTION_ID_PARAM},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "cancel_subscription",
        "description": (
            "Cancel an existing subscription belonging to the authenticated "
            "user. The subscription record is kept (marked cancelled), not "
            "deleted — use delete_subscription for permanent removal. Only call "
            "this for an explicit cancellation instruction, e.g. 'Cancel my "
            "Netflix subscription'. A vague or exploratory statement like 'I "
            "think I should cancel Netflix' is NOT a command to cancel it — "
            "discuss it with the user instead of calling this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {"subscription_id": _SUBSCRIPTION_ID_PARAM},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_subscription",
        "description": (
            "Permanently delete a subscription record belonging to the "
            "authenticated user. This is different from cancel_subscription: "
            "deletion removes the record entirely and cannot be undone, while "
            "cancellation just marks it cancelled. Only call this for an "
            "explicit, unambiguous deletion request (e.g. 'delete my old Hulu "
            "subscription entry' or 'remove this subscription completely'), "
            "never for a general 'cancel' request."
        ),
        "parameters": {
            "type": "object",
            "properties": {"subscription_id": _SUBSCRIPTION_ID_PARAM},
            "required": ["subscription_id"],
            "additionalProperties": False,
        },
    },
    # --- CURRENCY ---
    {
        "type": "function",
        "name": "get_supported_currencies",
        "description": (
            "Get the list of currencies FinAssist currently supports for "
            "conversion and exchange rates. Use this if the user asks what "
            "currencies are supported, or before attempting a conversion if "
            "you're unsure whether a currency is supported."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "convert_currency",
        "description": (
            "Convert an amount from one supported currency to another, using "
            "FinAssist's live exchange-rate backend. Use this for requests like "
            "'Convert 500,000 naira to USD' or 'How much is 100 euros in "
            "pounds?'. Never calculate or estimate an exchange rate yourself — "
            "always call this tool for any actual conversion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "The amount to convert. Must be positive."},
                "from_currency": {"type": "string", "description": "ISO currency code to convert from, e.g. 'NGN'."},
                "to_currency": {"type": "string", "description": "ISO currency code to convert to, e.g. 'USD'."},
            },
            "required": ["amount", "from_currency", "to_currency"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_exchange_rate",
        "description": (
            "Get the current exchange rate between two supported currencies, "
            "without converting a specific amount. Use this for questions like "
            "'What's the exchange rate between USD and NGN right now?'. Never "
            "fabricate or estimate a rate yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_currency": {"type": "string", "description": "ISO currency code, e.g. 'USD'."},
                "to_currency": {"type": "string", "description": "ISO currency code, e.g. 'NGN'."},
            },
            "required": ["from_currency", "to_currency"],
            "additionalProperties": False,
        },
    },
    # --- REMINDERS ---
    {
        "type": "function",
        "name": "create_reminder",
        "description": (
            "Create a persisted reminder for the authenticated user. Only call "
            "this once you have a clear, unambiguous title and time — if the "
            "user's requested time is ambiguous (e.g. no timezone/date context "
            "is clear), ask them to clarify rather than inventing a time. "
            "Example: 'Remind me tomorrow at 9am to review my subscriptions.'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "A short title for the reminder."},
                "remind_at": {
                    "type": "string",
                    "description": (
                        "The reminder time as an ISO-8601 datetime WITH an explicit "
                        "UTC offset, e.g. '2026-09-23T09:00:00+01:00' or "
                        "'2026-09-23T08:00:00Z'. Never omit the offset and never "
                        "assume the user's timezone — ask if it isn't clear from "
                        "the conversation."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Optional extra detail about the reminder.",
                },
            },
            "required": ["title", "remind_at"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_reminders",
        "description": (
            "List the authenticated user's reminders, optionally filtered by "
            "status. Use this for requests like 'What reminders do I have?' or "
            "'Show my upcoming reminders.'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "completed", "cancelled"],
                    "description": "Only return reminders with this status. Omit to return all statuses.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_reminder",
        "description": (
            "Delete/cancel a reminder belonging to the authenticated user, by "
            "id. Only use a reminder_id already obtained from a prior "
            "list_reminders or create_reminder call, and only on an explicit "
            "request to remove that reminder."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "integer",
                    "description": "The numeric id of the reminder, as returned by a previous reminder tool call.",
                },
            },
            "required": ["reminder_id"],
            "additionalProperties": False,
        },
    },
]

# ============================================================
# HANDLER REGISTRY
# ============================================================
# Explicit allowlist only — no dynamic dispatch (eval/getattr-by-name/
# globals()) is ever used to resolve a tool name to a function. A tool
# name that isn't a key here can never be executed, regardless of what
# the model sends.
_HANDLERS: dict[str, Callable[[int, dict[str, Any]], dict[str, Any]]] = {
    "list_subscriptions": subscription_tools.list_subscriptions,
    "find_subscription_by_service": subscription_tools.find_subscription_by_service,
    "get_upcoming_renewals": subscription_tools.get_upcoming_renewals,
    "get_monthly_spend": subscription_tools.get_monthly_spend,
    "get_subscription_details": subscription_tools.get_subscription_details,
    "add_subscription": subscription_tools.add_subscription,
    "update_subscription": subscription_tools.update_subscription,
    "pause_subscription": subscription_tools.pause_subscription,
    "resume_subscription": subscription_tools.resume_subscription,
    "cancel_subscription": subscription_tools.cancel_subscription,
    "delete_subscription": subscription_tools.delete_subscription,
    "get_supported_currencies": currency_tools.get_supported_currencies,
    "convert_currency": currency_tools.convert_currency,
    "get_exchange_rate": currency_tools.get_exchange_rate,
    "create_reminder": reminder_tools.create_reminder,
    "list_reminders": reminder_tools.list_reminders,
    "delete_reminder": reminder_tools.delete_reminder,
}

assert {tool["name"] for tool in TOOLS} == set(_HANDLERS), (
    "TOOLS and _HANDLERS have drifted apart — every defined tool must have "
    "exactly one registered handler, and vice versa."
)


def parse_tool_arguments(raw_arguments: str | None) -> dict[str, Any] | None:
    """Parses the model-supplied JSON arguments string for a tool call.

    Returns `{}` for an empty/missing string (a tool with no required
    parameters, called with no arguments), a dict for valid JSON object
    input, or `None` if the string is oversized, malformed, or doesn't
    decode to a JSON object — the caller treats `None` as an
    INVALID_ARGUMENTS error rather than silently proceeding with no
    arguments.
    """
    if raw_arguments is None or raw_arguments == "":
        return {}
    if len(raw_arguments) > _MAX_ARGUMENTS_BYTES:
        return None
    try:
        parsed = json.loads(raw_arguments)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _error(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}


def dispatch_tool_call(name: str, arguments: dict[str, Any], user_id: int) -> dict[str, Any]:
    """Executes one model-requested tool call and returns a
    JSON-serializable `{"result": ...}` or `{"error": {"code", "message"}}`
    — never a raw exception, stack trace, or internal error string.

    `user_id` must always be the authenticated user id from the
    caller's trusted server context (see chat_routes.py) — this
    function never reads `user_id` out of `arguments`, and explicitly
    strips it if a model-generated call included one, so a malicious or
    confused model can never redirect a call at another user's data.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        logger.warning("Unknown tool requested by model: name=%s", name)
        return _error("UNKNOWN_TOOL", "The requested tool is not available.")

    if not isinstance(arguments, dict):
        return _error("INVALID_ARGUMENTS", "Tool arguments must be an object.")

    # user_id is never taken from model-supplied arguments — silently
    # dropped here rather than trusted, even though no handler reads it
    # from `arguments` in the first place. Defense in depth.
    safe_arguments = {key: value for key, value in arguments.items() if key != "user_id"}

    try:
        result = handler(user_id, safe_arguments)
    except ToolError as exc:
        return _error(exc.code, exc.message, exc.details)
    except Exception:
        logger.exception(
            "Unhandled error in AI tool handler name=%s user_id=%s", name, user_id
        )
        return _error(
            "INTERNAL_ERROR", "Something went wrong while running that action."
        )

    return {"result": result}
