"""OpenAI Responses API access and the model <-> tool dispatcher loop.

This is the pure "talk to OpenAI" concern: constructing the client,
reading the tool calls a Responses API result carries, and driving the
call/dispatch/follow-up loop until the model produces a final answer or
the safety limit is hit. `services/chat_service.py` owns the per-request
chat workflow (conversation loading, history, persistence) and calls
into this module for everything OpenAI-specific.
"""
import json
import logging

from openai import OpenAI

from config import Config
from tools import MAX_TOOL_ROUNDS, TOOLS, dispatch_tool_call, parse_tool_arguments

logger = logging.getLogger(__name__)


def get_openai_client():
    """ The OpenAI client for this request.
    """
    return OpenAI(api_key=Config.OPEN_AI_KEY)


def _function_call_echo_item(call):
    """Builds the `input` item that echoes a model-requested tool call
    back into the conversation, in the shape the Responses API expects
    immediately before its matching `function_call_output`."""
    return {
        "type": "function_call",
        "call_id": call.call_id,
        "name": call.name,
        "arguments": call.arguments,
    }


def _pending_function_calls(response):
    """The `function_call` items in a Responses API result, if any. Uses
    getattr throughout so a response object that has no `.output` at
    all (never returns tool calls) is simply treated as having none,
    rather than raising."""
    return [
        item
        for item in (getattr(response, "output", None) or [])
        if getattr(item, "type", None) == "function_call"
    ]


def run_tool_loop(openai_client, model, instructions, conversation_history, response, user_id):
    """Executes the model <-> tool dispatcher loop for one /api/chat
    request, starting from an already-received `response`.

    Mutates `conversation_history` in place, appending each tool call
    the model makes and its structured result, exactly as the Responses
    API expects when following up on a function call. Returns the final
    `response` plus whether MAX_TOOL_ROUNDS was reached without the
    model producing a plain-text answer.

    At most MAX_TOOL_ROUNDS rounds of tool calls are executed. If the
    model still wants more tool calls after that, the loop stops
    without executing them — this is a hard safety valve against a
    runaway chain of tool calls, not an expected/normal path.
    """
    rounds_used = 0

    while True:
        function_calls = _pending_function_calls(response)

        if not function_calls:
            return response, False

        if rounds_used >= MAX_TOOL_ROUNDS:
            return response, True

        rounds_used += 1

        for call in function_calls:
            arguments = parse_tool_arguments(getattr(call, "arguments", None))
            if arguments is None:
                tool_result = {
                    "error": {
                        "code": "INVALID_ARGUMENTS",
                        "message": "The tool arguments could not be parsed.",
                    }
                }
            else:
                tool_result = dispatch_tool_call(call.name, arguments, user_id)

            logger.debug(
                "[chat tool_call] user_id=%s name=%s ok=%s",
                user_id, call.name, "error" not in tool_result,
            )

            conversation_history.append(_function_call_echo_item(call))
            conversation_history.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(tool_result),
            })

        response = openai_client.responses.create(
            model=model,
            instructions=instructions,
            input=conversation_history,
            tools=TOOLS,
        )


def load_system_prompt():
    with open("SYSTEM.MD", "r", encoding="utf-8") as file:
        return file.read()
