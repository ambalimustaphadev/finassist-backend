from extensions import db
from models import Activity


def test_profile_update_logs_activity(client, auth_headers):
    client.patch("/api/profile", headers=auth_headers, json={
        "first_name": "Updated",
    })

    response = client.get("/api/activity", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["pagination"]["total"] == 1
    assert body["items"][0]["type"] == "profile_updated"


def test_client_can_log_calculator_activity(client, auth_headers):
    response = client.post("/api/activity", headers=auth_headers, json={
        "type": "currency_conversion",
        "title": "Converted NGN to USD",
        "metadata": {"amount": 500000, "from": "NGN", "to": "USD"},
    })
    assert response.status_code == 201
    assert response.get_json()["type"] == "currency_conversion"


def test_client_cannot_log_removed_calculator_activity_types(client, auth_headers):
    for removed_type in ("loan_calculation", "savings_calculation", "affordability_calculation"):
        response = client.post("/api/activity", headers=auth_headers, json={
            "type": removed_type,
            "title": "Removed calculator",
        })
        assert response.status_code == 400


def test_historical_removed_calculator_activity_remains_readable(client, user):
    # Rows logged before the loan/savings/affordability calculators were
    # removed must still list and load — only new writes are rejected.
    user_id, headers = user
    historical = Activity(user_id=user_id, type="loan_calculation", title="Calculated a car loan")
    db.session.add(historical)
    db.session.commit()

    listed = client.get("/api/activity", headers=headers)
    assert listed.status_code == 200
    assert [item["type"] for item in listed.get_json()["items"]] == ["loan_calculation"]

    detail = client.get(f"/api/activity/{historical.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.get_json()["type"] == "loan_calculation"
    assert detail.get_json()["title"] == "Calculated a car loan"


def test_client_cannot_log_internal_activity_type(client, auth_headers):
    response = client.post("/api/activity", headers=auth_headers, json={
        "type": "profile_updated",
        "title": "Forged activity",
    })
    assert response.status_code == 400


def test_activity_ownership_enforced(client, auth_headers, other_auth_headers):
    client.patch("/api/profile", headers=auth_headers, json={
        "first_name": "Updated",
    })

    response = client.get("/api/activity", headers=other_auth_headers)
    assert response.get_json()["pagination"]["total"] == 0


def test_activity_pagination(client, auth_headers):
    for i in range(3):
        client.post("/api/activity", headers=auth_headers, json={
            "type": "currency_conversion",
            "title": f"Conversion {i}",
        })

    response = client.get("/api/activity?page=1&per_page=2", headers=auth_headers)
    body = response.get_json()
    assert len(body["items"]) == 2
    assert body["pagination"]["total"] == 3
