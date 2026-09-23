"""AI-tool adapters for currency operations.

Delegates entirely to `services.tools.currency.service`
(`CurrencyService`) — the same module the `/api/tools/currency/*`
routes and the Currency Converter UI use, which itself is the only
thing in the codebase that talks to `CurrencyRateProvider`
(Frankfurter today). This module never imports a provider directly,
never builds a request URL, and never hardcodes a rate or a currency
list: `get_supported_currencies` returns exactly what
`CurrencyService.list_currencies()` returns, and `convert_currency` /
`get_exchange_rate` both go through `CurrencyService.convert()`, which
is also where the 15-currency allowlist is enforced.
"""
from services.tools.currency import service as currency_service
from services.tools.currency.service import CurrencyProviderUnavailable
from utils import ValidationError

from .errors import ToolError, from_validation_error


def _convert(arguments, amount_override=None):
    payload = {
        "amount": arguments.get("amount") if amount_override is None else amount_override,
        "from_currency": arguments.get("from_currency"),
        "to_currency": arguments.get("to_currency"),
    }
    try:
        return currency_service.convert(payload)
    except ValidationError as exc:
        raise from_validation_error(exc)
    except CurrencyProviderUnavailable:
        raise ToolError(
            "CURRENCY_PROVIDER_UNAVAILABLE",
            "Exchange rates are temporarily unavailable. Please try again shortly.",
        )


def get_supported_currencies(user_id, arguments):
    return {"currencies": currency_service.list_currencies()}


def convert_currency(user_id, arguments):
    return _convert(arguments)


def get_exchange_rate(user_id, arguments):
    # CurrencyService.convert() already returns the rate as part of its
    # result (see currency/service.py:convert) — reused here for 1 unit
    # rather than adding a second call path into the provider.
    converted = _convert(arguments, amount_override="1")
    return {
        "from_currency": converted["inputs"]["from_currency"],
        "to_currency": converted["inputs"]["to_currency"],
        "rate": converted["result"]["rate"],
        "rate_date": converted["metadata"].get("rate_date"),
        "source": converted["metadata"].get("source"),
    }
