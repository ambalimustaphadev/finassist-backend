"""Tests for the currency AI tools (services/ai_tools/currency.py). All
of these must go through the existing CurrencyService / fake_currency_
provider fixture (see conftest.py) — never a hardcoded rate, and never
a second Frankfurter client."""
from services.tools.currency.providers.base import CurrencyProviderError
from tools import dispatch_tool_call


def _call(name, arguments, user_id=1):
    return dispatch_tool_call(name, arguments, user_id)


def test_get_supported_currencies_matches_existing_currency_service(client):
    from services.tools.currency import service as currency_service

    result = _call("get_supported_currencies", {})
    assert result["result"]["currencies"] == currency_service.list_currencies()


def test_convert_currency_success(client, fake_currency_provider):
    result = _call("convert_currency", {
        "amount": 1000, "from_currency": "USD", "to_currency": "NGN",
    })
    assert result["result"]["result"]["rate"] == "1500.500000"
    assert result["result"]["result"]["converted_amount"] == "1500500.00"


def test_convert_currency_rejects_unsupported_currency(client, fake_currency_provider):
    result = _call("convert_currency", {
        "amount": 100, "from_currency": "USD", "to_currency": "XXX",
    })
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_convert_currency_rejects_non_positive_amount(client, fake_currency_provider):
    result = _call("convert_currency", {
        "amount": 0, "from_currency": "USD", "to_currency": "NGN",
    })
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_convert_currency_provider_failure_reaches_a_safe_error(client, fake_currency_provider):
    fake_currency_provider.error = CurrencyProviderError(
        "raw provider outage detail that should never reach the model"
    )
    result = _call("convert_currency", {
        "amount": 100, "from_currency": "USD", "to_currency": "NGN",
    })
    assert result["error"]["code"] == "CURRENCY_PROVIDER_UNAVAILABLE"
    assert "raw provider outage detail" not in str(result)


def test_get_exchange_rate_reuses_convert_and_returns_the_rate(client, fake_currency_provider):
    result = _call("get_exchange_rate", {"from_currency": "USD", "to_currency": "NGN"})
    assert result["result"]["rate"] == "1500.500000"
    assert result["result"]["from_currency"] == "USD"
    assert result["result"]["to_currency"] == "NGN"
    # Exactly one provider call, for 1 unit — no separate rate endpoint.
    assert fake_currency_provider.calls == [("USD", "NGN")]


def test_get_exchange_rate_provider_failure_reaches_a_safe_error(client, fake_currency_provider):
    fake_currency_provider.error = CurrencyProviderError("boom")
    result = _call("get_exchange_rate", {"from_currency": "USD", "to_currency": "NGN"})
    assert result["error"]["code"] == "CURRENCY_PROVIDER_UNAVAILABLE"


def test_get_exchange_rate_rejects_unsupported_currency(client, fake_currency_provider):
    result = _call("get_exchange_rate", {"from_currency": "USD", "to_currency": "XXX"})
    assert result["error"]["code"] == "VALIDATION_ERROR"


def test_currency_tools_have_no_rate_table_of_their_own(client, fake_currency_provider):
    """Sanity check that the tool layer never hardcodes a rate: changing
    the fake provider's configured rate changes the tool's answer."""
    fake_currency_provider.rates[("USD", "NGN")] = "9999.99"
    result = _call("convert_currency", {
        "amount": 1, "from_currency": "USD", "to_currency": "NGN",
    })
    assert result["result"]["result"]["rate"] == "9999.990000"
