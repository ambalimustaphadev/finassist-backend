from services.tools.currency.providers.base import CurrencyProviderError


def _convert(client, headers, **overrides):
    payload = {"amount": "1000.00", "from_currency": "USD", "to_currency": "NGN"}
    payload.update(overrides)
    return client.post("/api/tools/currency/convert", headers=headers, json=payload)


# --- AUTH ---

def test_convert_requires_auth(client):
    response = _convert(client, {})
    assert response.status_code == 401


def test_currencies_requires_auth(client):
    response = client.get("/api/tools/currency/currencies")
    assert response.status_code == 401


# --- CURRENCIES LIST ---

EXPECTED_CURRENCY_CODES = {
    "NGN", "USD", "EUR", "GBP", "CAD", "AUD", "PLN", "CNY", "JPY",
    "CHF", "SEK", "NOK", "AED", "ZAR", "INR",
}


def test_currencies_list_returns_codes_and_names(client, auth_headers):
    response = client.get("/api/tools/currency/currencies", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert "currencies" in body
    codes = {c["code"] for c in body["currencies"]}
    assert "USD" in codes
    assert "NGN" in codes
    for entry in body["currencies"]:
        assert set(entry.keys()) == {"code", "name"}


def test_currencies_list_returns_exactly_the_supported_fifteen(client, auth_headers):
    response = client.get("/api/tools/currency/currencies", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    codes = {c["code"] for c in body["currencies"]}
    assert len(body["currencies"]) == 15
    assert codes == EXPECTED_CURRENCY_CODES


# --- CONVERSION ---

def test_convert_successful(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, amount="1000.00", from_currency="USD", to_currency="NGN")
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "currency_converter"
    assert body["version"] == "1"
    assert body["inputs"] == {
        "amount": "1000.00",
        "from_currency": "USD",
        "to_currency": "NGN",
    }
    assert body["result"]["rate"] == "1500.500000"
    assert body["result"]["converted_amount"] == "1500500.00"
    assert body["metadata"]["source"] == "fake"
    assert body["metadata"]["rate_date"] == "2026-09-18"
    assert "calculated_at" in body["metadata"]


def test_convert_reverse_direction(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, from_currency="NGN", to_currency="USD", amount="100")
    assert response.status_code == 200
    body = response.get_json()
    assert body["result"]["rate"] == "0.000667"


def test_convert_same_currency_short_circuits_provider(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, from_currency="USD", to_currency="USD", amount="50")
    assert response.status_code == 200
    body = response.get_json()
    assert body["result"]["rate"] == "1.000000"
    assert body["result"]["converted_amount"] == "50.00"
    assert body["metadata"]["source"] == "same_currency"
    assert fake_currency_provider.calls == []


def test_convert_normalizes_currency_case(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, from_currency="usd", to_currency="ngn")
    assert response.status_code == 200
    body = response.get_json()
    assert body["inputs"]["from_currency"] == "USD"
    assert body["inputs"]["to_currency"] == "NGN"


def test_convert_rejects_invalid_currency(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, to_currency="XXX")
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["to_currency"] == "INVALID_CURRENCY"


def test_convert_rejects_currency_outside_supported_fifteen(client, auth_headers, fake_currency_provider):
    # GHS is a valid currency code elsewhere in the Tools backend, but it is
    # not one of the 15 currencies the Currency Converter exposes.
    response = _convert(client, auth_headers, from_currency="NGN", to_currency="GHS")
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["to_currency"] == "INVALID_CURRENCY"


def test_convert_supports_newly_added_currency(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, from_currency="PLN", to_currency="NGN", amount="100")
    assert response.status_code == 200
    body = response.get_json()
    assert body["result"]["rate"] == "375.200000"


def test_convert_rejects_missing_currency(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, from_currency=None)
    assert response.status_code == 400


def test_convert_rejects_invalid_amount_type(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, amount="not-a-number")
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["amount"] == "INVALID_AMOUNT"


def test_convert_rejects_zero_amount(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, amount=0)
    assert response.status_code == 400


def test_convert_rejects_negative_amount(client, auth_headers, fake_currency_provider):
    response = _convert(client, auth_headers, amount=-10)
    assert response.status_code == 400


def test_convert_handles_provider_timeout(client, auth_headers, fake_currency_provider):
    fake_currency_provider.error = CurrencyProviderError("Exchange rate provider timed out.")
    response = _convert(client, auth_headers)
    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "CURRENCY_PROVIDER_UNAVAILABLE"


def test_convert_handles_provider_failure(client, auth_headers, fake_currency_provider):
    fake_currency_provider.error = CurrencyProviderError("Could not reach the exchange rate provider.")
    response = _convert(client, auth_headers)
    assert response.status_code == 502


def test_convert_handles_malformed_provider_response(client, auth_headers, fake_currency_provider):
    fake_currency_provider.error = CurrencyProviderError(
        "Exchange rate provider returned a malformed response."
    )
    response = _convert(client, auth_headers)
    assert response.status_code == 502
    assert "provider" in response.get_json()["error"]["message"].lower()


def test_convert_decimal_precision_not_lost(client, auth_headers, fake_currency_provider):
    fake_currency_provider.rates[("USD", "NGN")] = "1234.567891"
    response = _convert(client, auth_headers, amount="3.33")
    assert response.status_code == 200
    body = response.get_json()
    assert body["result"]["rate"] == "1234.567891"


# --- FRANKFURTER PROVIDER (unit-level, still no network) ---

def test_frankfurter_provider_parses_real_shape(monkeypatch):
    from services.tools.currency.providers.frankfurter import FrankfurterProvider

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"date": "2026-09-18", "base": "USD", "quote": "NGN", "rate": 1330.62}

    monkeypatch.setattr(
        "services.tools.currency.providers.frankfurter.requests.get",
        lambda url, timeout: FakeResponse(),
    )
    provider = FrankfurterProvider()
    result = provider.get_exchange_rate("USD", "NGN")
    assert result["rate"] == __import__("decimal").Decimal("1330.62")
    assert result["rate_date"] == "2026-09-18"
    assert result["source"] == "frankfurter"


def test_frankfurter_provider_raises_on_non_200(monkeypatch):
    from services.tools.currency.providers.base import CurrencyProviderError
    from services.tools.currency.providers.frankfurter import FrankfurterProvider

    class FakeResponse:
        status_code = 422

        def json(self):
            return {"status": 422, "message": "invalid currency: XXX"}

    monkeypatch.setattr(
        "services.tools.currency.providers.frankfurter.requests.get",
        lambda url, timeout: FakeResponse(),
    )
    provider = FrankfurterProvider()
    try:
        provider.get_exchange_rate("USD", "XXX")
        assert False, "expected CurrencyProviderError"
    except CurrencyProviderError:
        pass


def test_frankfurter_provider_raises_on_timeout(monkeypatch):
    import requests

    from services.tools.currency.providers.base import CurrencyProviderError
    from services.tools.currency.providers.frankfurter import FrankfurterProvider

    def raise_timeout(url, timeout):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(
        "services.tools.currency.providers.frankfurter.requests.get", raise_timeout
    )
    provider = FrankfurterProvider()
    try:
        provider.get_exchange_rate("USD", "NGN")
        assert False, "expected CurrencyProviderError"
    except CurrencyProviderError:
        pass


def test_frankfurter_provider_raises_on_missing_rate(monkeypatch):
    from services.tools.currency.providers.base import CurrencyProviderError
    from services.tools.currency.providers.frankfurter import FrankfurterProvider

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"date": "2026-09-18", "base": "USD", "quote": "NGN"}

    monkeypatch.setattr(
        "services.tools.currency.providers.frankfurter.requests.get",
        lambda url, timeout: FakeResponse(),
    )
    provider = FrankfurterProvider()
    try:
        provider.get_exchange_rate("USD", "NGN")
        assert False, "expected CurrencyProviderError"
    except CurrencyProviderError:
        pass
