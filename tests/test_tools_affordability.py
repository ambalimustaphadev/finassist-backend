def _payload(**overrides):
    payload = {
        "monthly_income": "500000",
        "existing_commitments": "150000",
        "purchase_price": "2000000",
        "payment_method": "installment",
        "duration_months": 12,
        "currency": "NGN",
    }
    payload.update(overrides)
    return payload


def _calculate(client, headers, **overrides):
    return client.post(
        "/api/tools/affordability/calculate", headers=headers, json=_payload(**overrides)
    )


def test_requires_auth(client):
    response = client.post("/api/tools/affordability/calculate", json=_payload())
    assert response.status_code == 401


def test_installment_calculation(client, auth_headers):
    response = _calculate(client, auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "affordability_calculator"
    result = body["result"]
    assert result["estimated_monthly_payment"] == "166666.67"
    assert result["total_monthly_commitments"] == "316666.67"
    assert result["commitment_ratio"] == "0.6333"
    assert result["remaining_income"] == "183333.33"


def test_within_threshold_flag(client, auth_headers):
    affordable = _calculate(client, auth_headers, purchase_price="600000").get_json()
    unaffordable = _calculate(client, auth_headers, purchase_price="20000000").get_json()
    assert affordable["metadata"]["within_threshold"] is True
    assert unaffordable["metadata"]["within_threshold"] is False


def test_cash_payment_has_no_recurring_payment(client, auth_headers):
    response = _calculate(client, auth_headers, payment_method="cash", duration_months=None)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["estimated_monthly_payment"] == "0.00"
    assert result["total_monthly_commitments"] == "150000.00"


def test_cash_payment_does_not_require_duration(client, auth_headers):
    response = _calculate(client, auth_headers, payment_method="cash", duration_months=None)
    assert response.status_code == 200


def test_installment_requires_duration(client, auth_headers):
    response = _calculate(client, auth_headers, duration_months=None)
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["duration_months"] == "INVALID_DURATION"


def test_rejects_invalid_income(client, auth_headers):
    response = _calculate(client, auth_headers, monthly_income=0)
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["monthly_income"] == "INVALID_AMOUNT"


def test_rejects_negative_existing_commitments(client, auth_headers):
    response = _calculate(client, auth_headers, existing_commitments=-1)
    assert response.status_code == 400


def test_rejects_invalid_duration(client, auth_headers):
    response = _calculate(client, auth_headers, duration_months=0)
    assert response.status_code == 400


def test_rejects_invalid_payment_method(client, auth_headers):
    response = _calculate(client, auth_headers, payment_method="crypto")
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["payment_method"] == "INVALID_PAYMENT"


def test_response_is_not_presented_as_absolute_truth(client, auth_headers):
    body = _calculate(client, auth_headers).get_json()
    assert "commitment_ratio_threshold" in body["metadata"]
    assert "assumptions" in body["metadata"]
