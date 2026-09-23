"""Adapters between the AI chat's tool-calling layer (see `tools.py` at
the project root) and FinAssist's existing services/models.

Each module here (`subscriptions`, `currency`, `reminders`) is thin
orchestration only: it translates a model-supplied `arguments` dict
into a call against the real business logic that already exists
elsewhere in the app (`services.subscription_service`,
`services.tools.currency.service`, `services.reminder_service`), and
enforces that every query/mutation is scoped to the authenticated
`user_id` passed in by the dispatcher. No calculation, persistence, or
validation rule is re-implemented here — see `services/ai_tools/errors.py`
for the shared error type these adapters raise.
"""
