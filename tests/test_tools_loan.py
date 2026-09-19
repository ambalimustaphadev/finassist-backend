def _payload(**overrides):
    payload = {
        "loan_amount": "1000000",
        "annual_interest_rate": "18",
        "duration": 12,
        "duration_unit": "months",
        "repayment_frequency": "monthly",
        "currency": "NGN",
    }
    payload.update(overrides)
    return payload


def _calculate(client, headers, **overrides):
    return client.post("/api/tools/loan/calculate", headers=headers, json=_payload(**overrides))


def test_requires_auth(client):
    response = client.post("/api/tools/loan/calculate", json=_payload())
    assert response.status_code == 401


def test_normal_amortized_loan(client, auth_headers):
    response = _calculate(client, auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "loan_calculator"
    assert body["version"] == "1"
    result = body["result"]
    assert result["periodic_payment"] == "91679.99"
    assert result["total_repayment"] == "1100159.91"
    assert result["total_interest"] == "100159.91"
    assert result["number_of_payments"] == 12
    assert body["metadata"]["is_estimate"] is True
    assert body["metadata"]["currency"] == "NGN"


def test_zero_interest_loan(client, auth_headers):
    response = _calculate(client, auth_headers, annual_interest_rate="0")
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["periodic_payment"] == "83333.33"
    assert result["total_repayment"] == "1000000.00"
    assert result["total_interest"] == "0.00"
    assert result["number_of_payments"] == 12


def test_different_frequencies_produce_different_payment_counts(client, auth_headers):
    weekly = _calculate(client, auth_headers, repayment_frequency="weekly").get_json()
    quarterly = _calculate(client, auth_headers, repayment_frequency="quarterly").get_json()
    monthly = _calculate(client, auth_headers, repayment_frequency="monthly").get_json()

    assert weekly["result"]["number_of_payments"] == 52
    assert quarterly["result"]["number_of_payments"] == 4
    assert monthly["result"]["number_of_payments"] == 12


def test_duration_in_years_converts_to_months(client, auth_headers):
    response = _calculate(client, auth_headers, duration=1, duration_unit="years")
    monthly = _calculate(client, auth_headers, duration=12, duration_unit="months")
    assert response.get_json()["result"] == monthly.get_json()["result"]


def test_rejects_invalid_amount(client, auth_headers):
    response = _calculate(client, auth_headers, loan_amount=0)
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["loan_amount"] == "INVALID_AMOUNT"


def test_rejects_negative_interest_rate(client, auth_headers):
    response = _calculate(client, auth_headers, annual_interest_rate=-5)
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["annual_interest_rate"] == "INVALID_INTEREST_RATE"


def test_rejects_invalid_duration(client, auth_headers):
    response = _calculate(client, auth_headers, duration=0)
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["duration"] == "INVALID_DURATION"


def test_rejects_invalid_frequency(client, auth_headers):
    response = _calculate(client, auth_headers, repayment_frequency="daily")
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["repayment_frequency"] == "INVALID_FREQUENCY"


def test_rejects_invalid_currency(client, auth_headers):
    response = _calculate(client, auth_headers, currency="XXX")
    assert response.status_code == 400


def test_response_contains_expected_envelope_keys(client, auth_headers):
    body = _calculate(client, auth_headers).get_json()
    assert set(body.keys()) == {"tool", "version", "inputs", "result", "metadata"}
