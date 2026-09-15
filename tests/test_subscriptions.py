def _payload(**overrides):
    payload = {
        "name": "Netflix",
        "amount": 7000,
        "currency": "NGN",
        "frequency": "monthly",
        "next_billing_date": "2026-10-15",
        "category": "entertainment",
        "payment_method": "debit_card",
        "website": "https://netflix.com",
        "notes": "Family plan",
    }
    payload.update(overrides)
    return payload


def _create(client, headers, **overrides):
    return client.post("/api/subscriptions", headers=headers, json=_payload(**overrides))


# --- AUTHENTICATION ---

def test_list_requires_auth(client):
    response = client.get("/api/subscriptions")
    assert response.status_code == 401


def test_create_requires_auth(client):
    response = client.post("/api/subscriptions", json=_payload())
    assert response.status_code == 401


def test_get_requires_auth(client):
    response = client.get("/api/subscriptions/1")
    assert response.status_code == 401


def test_update_requires_auth(client):
    response = client.patch("/api/subscriptions/1", json={"name": "x"})
    assert response.status_code == 401


def test_delete_requires_auth(client):
    response = client.delete("/api/subscriptions/1")
    assert response.status_code == 401


# --- OWNERSHIP ---

def test_user_cannot_see_other_users_subscription(client, auth_headers, other_auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.get(f"/api/subscriptions/{created['id']}", headers=other_auth_headers)
    assert response.status_code == 404


def test_user_cannot_update_other_users_subscription(client, auth_headers, other_auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=other_auth_headers, json={"name": "Hacked"}
    )
    assert response.status_code == 404


def test_user_cannot_delete_other_users_subscription(client, auth_headers, other_auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.delete(f"/api/subscriptions/{created['id']}", headers=other_auth_headers)
    assert response.status_code == 404

    still_there = client.get(f"/api/subscriptions/{created['id']}", headers=auth_headers)
    assert still_there.status_code == 200


# --- CREATE ---

def test_create_subscription_succeeds(client, auth_headers):
    response = _create(client, auth_headers)
    assert response.status_code == 201
    body = response.get_json()
    assert body["name"] == "Netflix"
    assert body["amount"] == 7000
    assert body["currency"] == "NGN"
    assert body["frequency"] == "monthly"
    assert body["next_billing_date"] == "2026-10-15"
    assert body["category"] == "entertainment"
    assert body["payment_method"] == "debit_card"
    assert body["website"] == "https://netflix.com"
    assert body["notes"] == "Family plan"


def test_create_defaults_status_active(client, auth_headers):
    response = _create(client, auth_headers)
    assert response.get_json()["status"] == "active"


def test_create_cancelled_at_starts_null(client, auth_headers):
    response = _create(client, auth_headers)
    assert response.get_json()["cancelled_at"] is None


def test_create_derives_user_id_from_jwt(client, auth_headers, user):
    user_id, _ = user
    response = _create(client, auth_headers, user_id=999999)
    assert response.status_code == 201
    assert response.get_json()["user_id"] == user_id


def test_create_rejects_missing_name(client, auth_headers):
    response = _create(client, auth_headers, name="")
    assert response.status_code == 400


def test_create_rejects_invalid_amount_type(client, auth_headers):
    response = _create(client, auth_headers, amount="not-a-number")
    assert response.status_code == 400


def test_create_rejects_zero_amount(client, auth_headers):
    response = _create(client, auth_headers, amount=0)
    assert response.status_code == 400


def test_create_rejects_negative_amount(client, auth_headers):
    response = _create(client, auth_headers, amount=-10)
    assert response.status_code == 400


def test_create_rejects_invalid_currency(client, auth_headers):
    response = _create(client, auth_headers, currency="XXX")
    assert response.status_code == 400


def test_create_rejects_invalid_frequency(client, auth_headers):
    response = _create(client, auth_headers, frequency="every_3_months")
    assert response.status_code == 400


def test_create_rejects_invalid_category(client, auth_headers):
    response = _create(client, auth_headers, category="cloud & storage")
    assert response.status_code == 400


def test_create_rejects_invalid_payment_method(client, auth_headers):
    response = _create(client, auth_headers, payment_method="Debit card")
    assert response.status_code == 400


def test_create_rejects_invalid_date(client, auth_headers):
    response = _create(client, auth_headers, next_billing_date="not-a-date")
    assert response.status_code == 400


def test_create_rejects_missing_date(client, auth_headers):
    response = _create(client, auth_headers, next_billing_date=None)
    assert response.status_code == 400


def test_create_allows_optional_fields_omitted(client, auth_headers):
    payload = _payload()
    del payload["category"]
    del payload["payment_method"]
    del payload["website"]
    del payload["notes"]
    response = client.post("/api/subscriptions", headers=auth_headers, json=payload)
    assert response.status_code == 201
    body = response.get_json()
    assert body["category"] is None
    assert body["payment_method"] is None
    assert body["website"] is None
    assert body["notes"] is None


# --- LIST ---

def test_list_only_returns_current_users_subscriptions(client, auth_headers, other_auth_headers):
    _create(client, auth_headers, name="Mine")
    _create(client, other_auth_headers, name="Theirs")

    response = client.get("/api/subscriptions", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["name"] == "Mine"


def test_list_orders_by_next_billing_date_ascending(client, auth_headers):
    _create(client, auth_headers, name="Later", next_billing_date="2026-12-01")
    _create(client, auth_headers, name="Sooner", next_billing_date="2026-10-01")
    _create(client, auth_headers, name="Middle", next_billing_date="2026-11-01")

    response = client.get("/api/subscriptions", headers=auth_headers)
    body = response.get_json()
    assert [s["name"] for s in body] == ["Sooner", "Middle", "Later"]


# --- GET ---

def test_get_existing_owned_subscription(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.get(f"/api/subscriptions/{created['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["id"] == created["id"]


def test_get_missing_subscription_returns_404(client, auth_headers):
    response = client.get("/api/subscriptions/999999", headers=auth_headers)
    assert response.status_code == 404


# --- UPDATE ---

def test_update_valid_fields_succeeds(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}",
        headers=auth_headers,
        json={"name": "Netflix Premium", "amount": 9000},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["name"] == "Netflix Premium"
    assert body["amount"] == 9000


def test_partial_update_preserves_other_fields(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"notes": "Updated notes"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["notes"] == "Updated notes"
    assert body["name"] == "Netflix"
    assert body["amount"] == 7000
    assert body["currency"] == "NGN"


def test_update_rejects_invalid_enum(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"frequency": "biannual"}
    )
    assert response.status_code == 400


def test_update_cannot_change_user_id(client, auth_headers, other_auth_headers, user):
    user_id, _ = user
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"user_id": 999999}
    )
    assert response.status_code == 200
    assert response.get_json()["user_id"] == user_id


def test_update_cannot_change_id_or_created_at(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}",
        headers=auth_headers,
        json={"id": 999999, "created_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == created["id"]
    assert body["created_at"] == created["created_at"]


def test_update_status_active_clears_cancelled_at(client, auth_headers):
    created = _create(client, auth_headers).get_json()
    client.patch(f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"status": "cancelled"})

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"status": "active"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "active"
    assert body["cancelled_at"] is None


def test_update_status_paused_keeps_cancelled_at_null(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"status": "paused"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "paused"
    assert body["cancelled_at"] is None


def test_update_status_cancelled_sets_cancelled_at(client, auth_headers):
    created = _create(client, auth_headers).get_json()
    assert created["cancelled_at"] is None

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"status": "cancelled"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None


def test_update_rejects_invalid_status_value(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}", headers=auth_headers, json={"status": "deleted"}
    )
    assert response.status_code == 400


def test_update_client_supplied_cancelled_at_is_ignored(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.patch(
        f"/api/subscriptions/{created['id']}",
        headers=auth_headers,
        json={"cancelled_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 200
    assert response.get_json()["cancelled_at"] is None


def test_update_missing_subscription_returns_404(client, auth_headers):
    response = client.patch("/api/subscriptions/999999", headers=auth_headers, json={"name": "x"})
    assert response.status_code == 404


# --- DELETE ---

def test_delete_owned_subscription(client, auth_headers):
    created = _create(client, auth_headers).get_json()

    response = client.delete(f"/api/subscriptions/{created['id']}", headers=auth_headers)
    assert response.status_code == 200

    follow_up = client.get(f"/api/subscriptions/{created['id']}", headers=auth_headers)
    assert follow_up.status_code == 404


def test_delete_missing_subscription_returns_404(client, auth_headers):
    response = client.delete("/api/subscriptions/999999", headers=auth_headers)
    assert response.status_code == 404


# --- SERIALIZATION ---

def test_response_contains_exact_expected_fields(client, auth_headers):
    response = _create(client, auth_headers)
    body = response.get_json()
    expected_fields = {
        "id", "user_id", "name", "amount", "currency", "frequency",
        "next_billing_date", "category", "payment_method", "website",
        "notes", "status", "created_at", "updated_at", "cancelled_at",
    }
    assert set(body.keys()) == expected_fields


def test_dates_serialized_consistently(client, auth_headers):
    response = _create(client, auth_headers)
    body = response.get_json()
    assert body["next_billing_date"] == "2026-10-15"
    assert body["created_at"].endswith("Z")
    assert body["updated_at"].endswith("Z")
