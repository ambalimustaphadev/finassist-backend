def _create_subscription(client, headers, **overrides):
    payload = {
        "name": "Netflix",
        "amount": 7000,
        "currency": "NGN",
        "frequency": "monthly",
        "next_billing_date": "2026-10-15",
    }
    payload.update(overrides)
    return client.post("/api/subscriptions", headers=headers, json=payload).get_json()


def _calculate(client, headers, **body):
    return client.post(
        "/api/tools/subscription-cost/calculate", headers=headers, json=body
    )


def test_requires_auth(client):
    response = client.post("/api/tools/subscription-cost/calculate", json={})
    assert response.status_code == 401


def test_monthly_subscription_normalization(client, auth_headers):
    _create_subscription(client, auth_headers, name="Netflix", amount=7000, frequency="monthly")
    response = _calculate(client, auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "subscription_cost_calculator"
    result = body["result"]
    assert result["subscription_count"] == 1
    assert result["subscriptions"][0]["monthly_cost"] == "7000.00"
    assert result["subscriptions"][0]["yearly_cost"] == "84000.00"
    assert result["total_monthly_cost"] == "7000.00"
    assert result["total_yearly_cost"] == "84000.00"


def test_yearly_subscription_normalization(client, auth_headers):
    _create_subscription(client, auth_headers, name="Spotify", amount=120000, frequency="yearly")
    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscriptions"][0]["monthly_cost"] == "10000.00"
    assert result["subscriptions"][0]["yearly_cost"] == "120000.00"


def test_weekly_normalization(client, auth_headers):
    _create_subscription(client, auth_headers, name="iCloud", amount=1000, frequency="weekly")
    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscriptions"][0]["monthly_cost"] == "4333.33"
    assert result["subscriptions"][0]["yearly_cost"] == "52000.00"


def test_quarterly_normalization(client, auth_headers):
    _create_subscription(client, auth_headers, name="ChatGPT", amount=60000, frequency="quarterly")
    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscriptions"][0]["monthly_cost"] == "20000.00"
    assert result["subscriptions"][0]["yearly_cost"] == "240000.00"


def test_semiannual_normalization(client, auth_headers):
    _create_subscription(client, auth_headers, name="Plan", amount=30000, frequency="semiannual")
    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscriptions"][0]["monthly_cost"] == "5000.00"
    assert result["subscriptions"][0]["yearly_cost"] == "60000.00"


def test_multiple_subscriptions_totaled_together(client, auth_headers):
    _create_subscription(client, auth_headers, name="Netflix", amount=7000, frequency="monthly")
    _create_subscription(client, auth_headers, name="Spotify", amount=120000, frequency="yearly")
    _create_subscription(client, auth_headers, name="iCloud", amount=1000, frequency="weekly")
    _create_subscription(client, auth_headers, name="ChatGPT", amount=60000, frequency="quarterly")

    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscription_count"] == 4
    assert result["total_monthly_cost"] == "41333.33"
    assert result["total_yearly_cost"] == "496000.00"
    assert result["currency"] == "NGN"


def test_cancelled_subscriptions_excluded_from_default_totals(client, auth_headers):
    netflix = _create_subscription(client, auth_headers, name="Netflix", amount=7000)
    client.patch(
        f"/api/subscriptions/{netflix['id']}", headers=auth_headers, json={"status": "cancelled"}
    )
    _create_subscription(client, auth_headers, name="Spotify", amount=10000)

    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscription_count"] == 1
    assert result["subscriptions"][0]["name"] == "Spotify"


def test_paused_subscriptions_excluded_from_default_totals(client, auth_headers):
    netflix = _create_subscription(client, auth_headers, name="Netflix", amount=7000)
    client.patch(
        f"/api/subscriptions/{netflix['id']}", headers=auth_headers, json={"status": "paused"}
    )
    _create_subscription(client, auth_headers, name="Spotify", amount=10000)

    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscription_count"] == 1
    assert result["subscriptions"][0]["name"] == "Spotify"


def test_explicit_ids_report_excluded_cancelled_subscription(client, auth_headers):
    netflix = _create_subscription(client, auth_headers, name="Netflix", amount=7000)
    client.patch(
        f"/api/subscriptions/{netflix['id']}", headers=auth_headers, json={"status": "cancelled"}
    )
    spotify = _create_subscription(client, auth_headers, name="Spotify", amount=10000)

    result = _calculate(
        client, auth_headers, subscription_ids=[netflix["id"], spotify["id"]]
    ).get_json()["result"]
    assert result["subscription_count"] == 1
    assert result["subscriptions"][0]["name"] == "Spotify"
    assert len(result["excluded_subscriptions"]) == 1
    assert result["excluded_subscriptions"][0]["name"] == "Netflix"
    assert result["excluded_subscriptions"][0]["status"] == "cancelled"


def test_explicit_subscription_ids_selects_subset(client, auth_headers):
    a = _create_subscription(client, auth_headers, name="Netflix", amount=7000)
    _create_subscription(client, auth_headers, name="Spotify", amount=10000)

    result = _calculate(client, auth_headers, subscription_ids=[a["id"]]).get_json()["result"]
    assert result["subscription_count"] == 1
    assert result["subscriptions"][0]["name"] == "Netflix"


def test_no_selection_and_no_subscriptions_returns_empty(client, auth_headers):
    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscription_count"] == 0
    assert result["subscriptions"] == []
    assert result["total_monthly_cost"] is None
    assert result["total_yearly_cost"] is None


def test_ownership_cannot_calculate_using_other_users_subscription(
    client, auth_headers, other_auth_headers
):
    theirs = _create_subscription(client, other_auth_headers, name="Theirs", amount=5000)

    response = _calculate(client, auth_headers, subscription_ids=[theirs["id"]])
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


def test_ownership_default_selection_never_includes_other_users_subscriptions(
    client, auth_headers, other_auth_headers
):
    _create_subscription(client, other_auth_headers, name="Theirs", amount=5000)

    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["subscription_count"] == 0


def test_nonexistent_subscription_id_returns_not_found(client, auth_headers):
    response = _calculate(client, auth_headers, subscription_ids=[999999])
    assert response.status_code == 404
    body = response.get_json()
    assert body["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"
    assert body["error"]["details"]["subscription_ids"] == [999999]


def test_mixed_currencies_are_not_summed_together(client, auth_headers):
    _create_subscription(client, auth_headers, name="Netflix", amount=7000, currency="NGN")
    _create_subscription(client, auth_headers, name="Spotify", amount=10, currency="USD")

    result = _calculate(client, auth_headers).get_json()["result"]
    assert result["total_monthly_cost"] is None
    assert result["total_yearly_cost"] is None
    assert result["currency"] is None
    currencies = {b["currency"] for b in result["totals_by_currency"]}
    assert currencies == {"NGN", "USD"}


def test_stored_amount_is_used_not_a_client_supplied_one(client, auth_headers):
    netflix = _create_subscription(client, auth_headers, name="Netflix", amount=7000)

    response = _calculate(
        client,
        auth_headers,
        subscription_ids=[netflix["id"]],
        # A client can't smuggle a different amount into the calculation —
        # the request body has no field for it in the first place, but
        # verify the DB value is what's actually used.
    )
    result = response.get_json()["result"]
    assert result["subscriptions"][0]["amount"] == "7000.00"


def test_invalid_subscription_ids_type_rejected(client, auth_headers):
    response = _calculate(client, auth_headers, subscription_ids="not-a-list")
    assert response.status_code == 400


def test_invalid_subscription_ids_contents_rejected(client, auth_headers):
    response = _calculate(client, auth_headers, subscription_ids=["abc"])
    assert response.status_code == 400
