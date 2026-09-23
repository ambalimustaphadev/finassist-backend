"""Shared error type for the AI-tool adapter layer."""


class ToolError(Exception):
    """Raised by an AI-tool adapter (services/ai_tools/*) for any
    expected failure: not found, ownership mismatch, bad arguments, an
    upstream provider outage, etc. Caught by `dispatch_tool_call` in
    `tools.py` and converted into the structured
    `{"error": {"code", "message"}}` shape sent back to the model —
    never a raw exception, stack trace, or internal error string.
    """

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def from_validation_error(exc):
    """Wraps the app's existing `utils.ValidationError` (already used by
    every REST route and service) as a ToolError, so adapters reuse the
    same validation error shape instead of inventing a second one."""
    return ToolError("VALIDATION_ERROR", exc.message, exc.details)
