def _payload(**overrides):
    payload = {
        "target_amount": "120000",
        "duration_months": 12,
        "currency": "NGN",
    }
    payload.update(overrides)
    return payload


def _calculate(client, headers, **overrides):
    return client.post("/api/tools/savings/calculate", headers=headers, json=_payload(**overrides))


def test_requires_auth(client):
    response = client.post("/api/tools/savings/calculate", json=_payload())
    assert response.status_code == 401


def test_target_based_calculation_no_growth(client, auth_headers):
    response = _calculate(client, auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["tool"] == "savings_calculator"
    result = body["result"]
    assert result["required_monthly_contribution"] == "10000.00"
    assert result["projected_amount"] == "120000.00"
    assert result["total_contributions"] == "120000.00"
    assert result["estimated_growth"] == "0.00"
    assert body["metadata"]["mode"] == "target_based"


def test_target_based_calculation_with_growth(client, auth_headers):
    response = _calculate(client, auth_headers, annual_return_rate="6")
    body = response.get_json()
    result = body["result"]
    assert result["required_monthly_contribution"] == "9727.97"
    assert result["projected_amount"] == "120000.00"
    assert result["estimated_growth"] != "0.00"


def test_contribution_based_calculation(client, auth_headers):
    response = _calculate(
        client, auth_headers, target_amount=None, monthly_contribution="10000"
    )
    assert response.status_code == 200
    body = response.get_json()
    result = body["result"]
    assert result["projected_amount"] == "120000.00"
    assert result["total_contributions"] == "120000.00"
    assert result["estimated_growth"] == "0.00"
    assert body["metadata"]["mode"] == "contribution_based"


def test_contribution_based_calculation_with_growth(client, auth_headers):
    response = _calculate(
        client,
        auth_headers,
        target_amount=None,
        monthly_contribution="10000",
        annual_return_rate="6",
    )
    body = response.get_json()
    result = body["result"]
    assert result["projected_amount"] == "123355.62"
    assert result["total_contributions"] == "120000.00"
    assert result["estimated_growth"] == "3355.62"


def test_rejects_when_both_target_and_contribution_given(client, auth_headers):
    response = _calculate(client, auth_headers, monthly_contribution="10000")
    assert response.status_code == 400


def test_rejects_when_neither_target_nor_contribution_given(client, auth_headers):
    response = _calculate(client, auth_headers, target_amount=None)
    assert response.status_code == 400


def test_rejects_zero_target_amount(client, auth_headers):
    response = _calculate(client, auth_headers, target_amount=0)
    assert response.status_code == 400


def test_rejects_invalid_duration(client, auth_headers):
    response = _calculate(client, auth_headers, duration_months=0)
    assert response.status_code == 400


def test_rejects_negative_return_rate(client, auth_headers):
    response = _calculate(client, auth_headers, annual_return_rate=-1)
    assert response.status_code == 400


def test_no_growth_assumed_when_rate_omitted(client, auth_headers):
    response = _calculate(client, auth_headers)
    body = response.get_json()
    assert body["inputs"]["annual_return_rate"] == "0.0000"
