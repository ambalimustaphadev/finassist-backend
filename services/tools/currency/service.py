"""CurrencyService: the only layer routes talk to. It depends on the
CurrencyRateProvider interface, never on a specific provider — the
route imports this module, not `providers.frankfurter`."""
from decimal import Decimal

from ..common import build_tool_result, decimal_str, require_currency_code, require_decimal
from .providers.base import CurrencyProviderError
from .providers.frankfurter import FrankfurterProvider

TOOL_NAME = "currency_converter"

# Backend is the source of truth for supported currency metadata — the
# codes mirror utils.CURRENCIES (shared with Subscriptions), so any
# currency accepted there is always convertible here.
CURRENCY_NAMES = {
    "NGN": "Nigerian Naira",
    "USD": "United States Dollar",
    "EUR": "Euro",
    "GBP": "British Pound Sterling",
    "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar",
    "ZAR": "South African Rand",
    "GHS": "Ghanaian Cedi",
    "KES": "Kenyan Shilling",
    "INR": "Indian Rupee",
    "JPY": "Japanese Yen",
    "CNY": "Chinese Yuan",
    "CHF": "Swiss Franc",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "DKK": "Danish Krone",
    "AED": "United Arab Emirates Dirham",
    "SAR": "Saudi Riyal",
    "EGP": "Egyptian Pound",
    "XOF": "West African CFA Franc",
    "XAF": "Central African CFA Franc",
    "BRL": "Brazilian Real",
    "MXN": "Mexican Peso",
    "SGD": "Singapore Dollar",
    "HKD": "Hong Kong Dollar",
    "NZD": "New Zealand Dollar",
}


class CurrencyProviderUnavailable(Exception):
    """Raised by the service (never the provider's own exception type)
    so the route only needs to know about this module's contract."""


def get_default_provider():
    return FrankfurterProvider()


def list_currencies():
    return [{"code": code, "name": CURRENCY_NAMES[code]} for code in sorted(CURRENCY_NAMES)]


def convert(data, provider=None):
    provider = provider or get_default_provider()

    amount = require_decimal(
        data.get("amount"), "amount", "INVALID_AMOUNT", exclusive_minimum=0
    )
    from_currency = require_currency_code(data.get("from_currency"), "from_currency")
    to_currency = require_currency_code(data.get("to_currency"), "to_currency")

    if from_currency == to_currency:
        rate = Decimal(1)
        rate_date = None
        source = "same_currency"
    else:
        try:
            rate_info = provider.get_exchange_rate(from_currency, to_currency)
        except CurrencyProviderError as exc:
            raise CurrencyProviderUnavailable(str(exc)) from exc
        rate = rate_info["rate"]
        rate_date = rate_info["rate_date"]
        source = rate_info["source"]

    converted_amount = amount * rate

    inputs = {
        "amount": decimal_str(amount),
        "from_currency": from_currency,
        "to_currency": to_currency,
    }
    result = {
        "rate": decimal_str(rate, 6),
        "converted_amount": decimal_str(converted_amount),
    }
    metadata = {"rate_date": rate_date, "source": source}

    return build_tool_result(TOOL_NAME, inputs, result, metadata)
