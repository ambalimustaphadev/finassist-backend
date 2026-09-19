"""Frankfurter (api.frankfurter.dev) implementation of
CurrencyRateProvider. This is the only file in the codebase that knows
Frankfurter's URL shape or response format — parsing its JSON never
leaks into CurrencyService or the routes above it."""
from decimal import Decimal, InvalidOperation

import requests

from config import Config

from .base import CurrencyProviderError, CurrencyRateProvider

DEFAULT_TIMEOUT_SECONDS = 5


class FrankfurterProvider(CurrencyRateProvider):
    SOURCE = "frankfurter"

    def __init__(self, base_url=None, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.base_url = (base_url or Config.FRANKFURTER_BASE_URL).rstrip("/")
        self.timeout = timeout

    def get_exchange_rate(self, base_currency, quote_currency):
        url = f"{self.base_url}/rate/{base_currency}/{quote_currency}"

        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.Timeout as exc:
            raise CurrencyProviderError("Exchange rate provider timed out.") from exc
        except requests.RequestException as exc:
            raise CurrencyProviderError(
                "Could not reach the exchange rate provider."
            ) from exc

        if response.status_code != 200:
            raise CurrencyProviderError(
                f"Exchange rate provider returned status {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise CurrencyProviderError(
                "Exchange rate provider returned a malformed response."
            ) from exc

        if not isinstance(payload, dict):
            raise CurrencyProviderError(
                "Exchange rate provider returned a malformed response."
            )

        raw_rate = payload.get("rate")
        rate_date = payload.get("date")

        if raw_rate is None or not rate_date:
            raise CurrencyProviderError(
                "Exchange rate provider response is missing the requested rate."
            )

        try:
            rate = Decimal(str(raw_rate))
        except (InvalidOperation, TypeError) as exc:
            raise CurrencyProviderError(
                "Exchange rate provider returned an invalid rate."
            ) from exc

        if not rate.is_finite() or rate <= 0:
            raise CurrencyProviderError(
                "Exchange rate provider returned an invalid rate."
            )

        return {"rate": rate, "rate_date": str(rate_date), "source": self.SOURCE}
