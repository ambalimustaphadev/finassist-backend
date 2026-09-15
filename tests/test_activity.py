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
        "type": "loan_calculation",
        "title": "Calculated a car loan",
        "metadata": {"principal": 500000, "rate": 0.1},
    })
    assert response.status_code == 201
    assert response.get_json()["type"] == "loan_calculation"


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
