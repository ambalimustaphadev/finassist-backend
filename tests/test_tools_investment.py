def _payload(**overrides):
    payload = {
        "initial_amount": "500000",
        "monthly_contribution": "100000",
        "expected_annual_return": "12",
        "duration_years": 10,
        "compounding_frequency": "monthly",
        "currency": "NGN",
    }
    payload.update(overrides)
    return payload


def _calculate(client, headers, **overrides):
    return client.post(
        "/api/tools/investment/calculate", headers=headers, json=_payload(**overrides)
    )


def test_requires_auth(client):
    response = client.post("/api/tools/investment/calculate", json=_payload())
    assert response.status_code == 401


def test_compound_growth_monthly(client, auth_headers):
    response = _calculate(client, auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "investment_growth_calculator"
    result = body["result"]
    assert result["future_value"] == "24654062.39"
    assert result["total_contributions"] == "12500000.00"
    assert result["estimated_growth"] == "12154062.39"
    assert result["initial_amount"] == "500000.00"
    assert result["contribution_amount"] == "100000.00"


def test_different_compounding_frequencies(client, auth_headers):
    quarterly = _calculate(client, auth_headers, compounding_frequency="quarterly").get_json()
    annually = _calculate(client, auth_headers, compounding_frequency="annually").get_json()
    assert quarterly["result"]["future_value"] == "24476114.77"
    assert annually["result"]["future_value"] == "23745928.24"


def test_zero_return_means_future_value_equals_contributions(client, auth_headers):
    response = _calculate(client, auth_headers, expected_annual_return="0")
    result = response.get_json()["result"]
    assert result["future_value"] == "12500000.00"
    assert result["estimated_growth"] == "0.00"


def test_contribution_optional_defaults_to_zero(client, auth_headers):
    payload = _payload()
    del payload["monthly_contribution"]
    response = client.post("/api/tools/investment/calculate", headers=auth_headers, json=payload)
    assert response.status_code == 200
    assert response.get_json()["result"]["contribution_amount"] == "0.00"


def test_rejects_invalid_initial_amount(client, auth_headers):
    response = _calculate(client, auth_headers, initial_amount="not-a-number")
    assert response.status_code == 400


def test_rejects_negative_return(client, auth_headers):
    response = _calculate(client, auth_headers, expected_annual_return=-1)
    assert response.status_code == 400


def test_rejects_invalid_duration(client, auth_headers):
    response = _calculate(client, auth_headers, duration_years=0)
    assert response.status_code == 400


def test_rejects_invalid_compounding_frequency(client, auth_headers):
    response = _calculate(client, auth_headers, compounding_frequency="weekly")
    assert response.status_code == 400
    assert response.get_json()["error"]["details"]["compounding_frequency"] == "INVALID_FREQUENCY"


def test_result_labeled_as_estimate_not_guaranteed(client, auth_headers):
    body = _calculate(client, auth_headers).get_json()
    assert body["metadata"]["is_estimate"] is True
    assert "not investment advice" in body["metadata"]["assumptions"].lower()
