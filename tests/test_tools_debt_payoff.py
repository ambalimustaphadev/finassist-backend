def _payload(**overrides):
    payload = {
        "current_debt": "1500000",
        "annual_interest_rate": "20",
        "minimum_monthly_payment": "50000",
        "extra_monthly_payment": "50000",
        "currency": "NGN",
    }
    payload.update(overrides)
    return payload


def _calculate(client, headers, **overrides):
    return client.post(
        "/api/tools/debt-payoff/calculate", headers=headers, json=_payload(**overrides)
    )


def test_requires_auth(client):
    response = client.post("/api/tools/debt-payoff/calculate", json=_payload())
    assert response.status_code == 401


def test_normal_payoff_with_extra_payment(client, auth_headers):
    response = _calculate(client, auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "debt_payoff_calculator"
    result = body["result"]
    assert result["months_to_payoff"] == 18
    assert result["total_interest"] == "240636.07"
    assert result["total_repayment"] == "1740636.07"


def test_interest_saved_and_months_saved_vs_minimum_only(client, auth_headers):
    body = _calculate(client, auth_headers).get_json()
    result = body["result"]
    assert result["minimum_only"]["payable"] is True
    assert result["minimum_only"]["months_to_payoff"] == 42
    assert result["minimum_only"]["total_interest"] == "596747.73"
    assert result["interest_saved"] == "356111.66"
    assert result["months_saved"] == 24


def test_no_extra_payment_means_no_savings_comparison_difference(client, auth_headers):
    body = _calculate(client, auth_headers, extra_monthly_payment=0).get_json()
    result = body["result"]
    assert result["interest_saved"] == "0.00"
    assert result["months_saved"] == 0


def test_minimum_alone_insufficient_but_total_payment_works(client, auth_headers):
    response = _calculate(
        client, auth_headers, minimum_monthly_payment="20000", extra_monthly_payment="50000"
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["months_to_payoff"] == 27
    assert result["minimum_only"]["payable"] is False
    assert result["minimum_only"]["months_to_payoff"] is None
    assert result["interest_saved"] is None
    assert result["months_saved"] is None


def test_payment_insufficient_to_cover_interest_returns_clear_error(client, auth_headers):
    # first month's interest on 1,500,000 at 20%/yr is 25,000 — a total
    # payment below that can never pay off the debt.
    response = _calculate(
        client, auth_headers, minimum_monthly_payment="10000", extra_monthly_payment="0"
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["minimum_monthly_payment"] == "DEBT_PAYMENT_TOO_LOW"


def test_payment_exactly_equal_to_interest_is_rejected(client, auth_headers):
    response = _calculate(
        client,
        auth_headers,
        current_debt="1500000",
        annual_interest_rate="20",
        minimum_monthly_payment="25000",
        extra_monthly_payment="0",
    )
    assert response.status_code == 400


def test_rejects_invalid_current_debt(client, auth_headers):
    response = _calculate(client, auth_headers, current_debt=0)
    assert response.status_code == 400


def test_rejects_negative_interest_rate(client, auth_headers):
    response = _calculate(client, auth_headers, annual_interest_rate=-1)
    assert response.status_code == 400


def test_rejects_invalid_minimum_payment(client, auth_headers):
    response = _calculate(client, auth_headers, minimum_monthly_payment=0)
    assert response.status_code == 400


def test_extra_payment_defaults_to_zero_when_omitted(client, auth_headers):
    payload = _payload()
    del payload["extra_monthly_payment"]
    response = client.post("/api/tools/debt-payoff/calculate", headers=auth_headers, json=payload)
    assert response.status_code == 200
    assert response.get_json()["inputs"]["extra_monthly_payment"] == "0.00"
