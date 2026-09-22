"""CurrencyService: the only layer routes talk to. It depends on the
CurrencyRateProvider interface, never on a specific provider — the
route imports this module, not `providers.frankfurter`."""
from decimal import Decimal

from utils import ValidationError

from ..common import build_tool_result, decimal_str, require_decimal
from .providers.base import CurrencyProviderError
from .providers.frankfurter import FrankfurterProvider

TOOL_NAME = "currency_converter"

# Backend is the source of truth for which currencies the Currency
# Converter exposes to Flutter — deliberately a curated subset of
# utils.CURRENCIES (the wider set other Tools accept), not the full
# Frankfurter currency list. Flutter maps each code to a presentation
# flag itself; the backend only returns code + name.
CURRENCY_NAMES = {
    "NGN": "Nigerian Naira",
    "USD": "US Dollar",
    "EUR": "Euro",
    "GBP": "British Pound",
    "CAD": "Canadian Dollar",
    "AUD": "Australian Dollar",
    "PLN": "Polish Złoty",
    "CNY": "Chinese Yuan",
    "JPY": "Japanese Yen",
    "CHF": "Swiss Franc",
    "SEK": "Swedish Krona",
    "NOK": "Norwegian Krone",
    "AED": "United Arab Emirates Dirham",
    "ZAR": "South African Rand",
    "INR": "Indian Rupee",
}


class CurrencyProviderUnavailable(Exception):
    """Raised by the service (never the provider's own exception type)
    so the route only needs to know about this module's contract."""


def get_default_provider():
    return FrankfurterProvider()


def list_currencies():
    return [{"code": code, "name": CURRENCY_NAMES[code]} for code in sorted(CURRENCY_NAMES)]


def _require_supported_currency(value, field_name, code="INVALID_CURRENCY"):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} is required.", {field_name: code})
    normalized = value.strip().upper()
    if normalized not in CURRENCY_NAMES:
        raise ValidationError(
            f"'{value}' is not a supported currency code.", {field_name: code}
        )
    return normalized


def convert(data, provider=None):
    provider = provider or get_default_provider()

    amount = require_decimal(
        data.get("amount"), "amount", "INVALID_AMOUNT", exclusive_minimum=0
    )
    from_currency = _require_supported_currency(data.get("from_currency"), "from_currency")
    to_currency = _require_supported_currency(data.get("to_currency"), "to_currency")

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
