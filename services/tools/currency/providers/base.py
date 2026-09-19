"""The abstraction CurrencyService depends on. Any provider (Frankfurter
today, something else later) plugs in behind this interface, so
swapping providers never touches CurrencyService, the routes, the
response schema, or Flutter."""
from abc import ABC, abstractmethod


class CurrencyProviderError(Exception):
    """Raised for any provider failure — timeout, connection error,
    non-2xx status, malformed payload, or a missing/invalid rate.
    Callers only ever see this, never a raw provider/HTTP exception."""


class CurrencyRateProvider(ABC):
    @abstractmethod
    def get_exchange_rate(self, base_currency: str, quote_currency: str) -> dict:
        """Return the current rate for 1 unit of `base_currency` in
        `quote_currency` as {"rate": Decimal, "rate_date": "YYYY-MM-DD",
        "source": str}. Raises CurrencyProviderError on any failure."""
        raise NotImplementedError
