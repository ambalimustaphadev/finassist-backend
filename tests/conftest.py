from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool

from extensions import db
from server import create_app
from services.tools.currency.providers.base import CurrencyProviderError


class FakeR2Client:
    def __init__(self):
        self.put_calls = []
        self.delete_calls = []
        self.presign_calls = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put_calls.append((Bucket, Key))

    def delete_object(self, Bucket, Key):
        self.delete_calls.append((Bucket, Key))

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presign_calls.append((Params["Key"], ExpiresIn))
        call_number = len(self.presign_calls)
        return (
            f"https://fake-r2.example.com/{Params['Key']}"
            f"?expires_in={ExpiresIn}&call={call_number}"
        )


@pytest.fixture()
def fake_r2(monkeypatch):
    fake_client = FakeR2Client()
    # file_service.py/profile_service.py only ever reach R2 through
    # spaces.py's own wrappers (upload_object/delete_object/
    # generate_signed_url), which all resolve get_spaces_client() from
    # this module's own namespace — patching it here is the single
    # interception point for every caller.
    monkeypatch.setattr("spaces.get_spaces_client", lambda: fake_client)
    return fake_client


class FakeCurrencyProvider:
    """Test double for CurrencyRateProvider. Never touches the network —
    tests must not depend on Frankfurter's real availability."""

    def __init__(self, rates=None, error=None):
        self.rates = rates or {}
        self.error = error
        self.calls = []

    def get_exchange_rate(self, base_currency, quote_currency):
        self.calls.append((base_currency, quote_currency))
        if self.error is not None:
            raise self.error
        key = (base_currency, quote_currency)
        if key not in self.rates:
            raise CurrencyProviderError(f"No fake rate configured for {key}.")
        return {
            "rate": Decimal(str(self.rates[key])),
            "rate_date": "2026-09-18",
            "source": "fake",
        }


@pytest.fixture()
def fake_currency_provider(monkeypatch):
    fake_provider = FakeCurrencyProvider(
        rates={
            ("USD", "NGN"): "1500.50",
            ("NGN", "USD"): "0.000667",
            ("EUR", "USD"): "1.08",
            ("PLN", "NGN"): "375.20",
        }
    )
    monkeypatch.setattr(
        "services.tools.currency.service.get_default_provider", lambda: fake_provider
    )
    return fake_provider


class FakeSendResult:
    """Stand-in for firebase_admin.messaging.SendResponse."""

    def __init__(self, success, exception=None):
        self.success = success
        self.exception = exception


class FakeBatchResponse:
    """Stand-in for firebase_admin.messaging.BatchResponse."""

    def __init__(self, responses):
        self.responses = responses
        self.success_count = sum(1 for r in responses if r.success)
        self.failure_count = len(responses) - self.success_count


class FakePushNotifications:
    """Test double for push_notification_service._send_multicast — the
    one seam that module is designed to be tested through (see its
    module docstring). Never touches Firebase or the network.

    Configure `invalid_tokens` (a set of token strings that should come
    back as an UnregisteredError, i.e. "this token is dead") or
    `unavailable=True` (simulates the whole FCM request failing) before
    a send. Every call is recorded in `.calls`.
    """

    def __init__(self):
        self.calls = []
        self.invalid_tokens = set()
        self.unavailable = False

    def __call__(self, tokens, title, body, data):
        self.calls.append({
            "tokens": list(tokens), "title": title, "body": body, "data": data,
        })
        if self.unavailable:
            from services.push_notification_service import PushNotificationUnavailable
            raise PushNotificationUnavailable("fake FCM outage")

        from firebase_admin import messaging

        responses = [
            FakeSendResult(False, exception=messaging.UnregisteredError("gone"))
            if token in self.invalid_tokens
            else FakeSendResult(True)
            for token in tokens
        ]
        return FakeBatchResponse(responses)


@pytest.fixture()
def fake_push(monkeypatch):
    fake = FakePushNotifications()
    monkeypatch.setattr("services.push_notification_service._send_multicast", fake)
    return fake


def register_device_token(client, headers, token="fcm-token-1", platform="ios"):
    return client.post(
        "/api/notifications/device-token",
        headers=headers,
        json={"token": token, "platform": platform},
    )


@pytest.fixture()
def app():
    application = create_app({
        "TESTING": True,
        "JWT_SECRET_KEY": "test-secret-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    })

    with application.app_context():
        # Hard guard: if this ever binds to a real file instead of the
        # in-memory sqlite above, refuse to touch it. A prior version of
        # this fixture overrode SQLALCHEMY_DATABASE_URI *after*
        # create_app() had already called db.init_app() with the real
        # config, and db.drop_all() below wiped the actual dev database.
        engine_url = str(db.engine.url)
        assert engine_url == "sqlite://", (
            f"Refusing to run tests against non-in-memory database: {engine_url}"
        )

        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register_and_login(client, suffix="a"):
    client.post("/api/register", json={
        "username": f"user_{suffix}",
        "first_name": "Test",
        "last_name": "User",
        "email": f"user_{suffix}@example.com",
        "password": "password123",
    })
    response = client.post("/api/login", json={
        "email": f"user_{suffix}@example.com",
        "password": "password123",
    })
    body = response.get_json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture()
def user(client):
    return register_and_login(client, "a")


@pytest.fixture()
def other_user(client):
    return register_and_login(client, "b")


@pytest.fixture()
def auth_headers(user):
    return user[1]


@pytest.fixture()
def other_auth_headers(other_user):
    return other_user[1]
