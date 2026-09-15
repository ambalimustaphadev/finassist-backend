from extensions import db
from models import UserPreference
from services.preference_service import get_or_create_preferences


def test_get_preferences_creates_defaults(client, auth_headers):
    response = client.get("/api/preferences", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["currency"] == "NGN"
    assert body["language"] == "en"
    assert body["notifications_enabled"] is True


def test_update_preferences(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "currency": "GBP",
        "notifications_enabled": False,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["currency"] == "GBP"
    assert body["notifications_enabled"] is False


def test_update_preferences_rejects_bad_language(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={"language": "xx"})
    assert response.status_code == 400


def test_preferences_scoped_to_user(client, auth_headers, other_auth_headers):
    client.patch("/api/preferences", headers=auth_headers, json={"currency": "EUR"})

    response = client.get("/api/preferences", headers=other_auth_headers)
    assert response.get_json()["currency"] == "NGN"


def test_get_preferences_includes_personalization_defaults(client, auth_headers):
    response = client.get("/api/preferences", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    # Never fabricated for a user who hasn't been through personalization.
    assert body["financial_experience"] is None
    assert body["interests"] is None
    assert body["response_style"] is None
    # A behavior toggle, not a selection — defaults on like the other
    # notification-style booleans.
    assert body["proactive_suggestions"] is True


def test_patch_financial_experience(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "financial_experience": "beginner",
    })
    assert response.status_code == 200
    assert response.get_json()["financial_experience"] == "beginner"


def test_patch_response_style(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "response_style": "detailed",
    })
    assert response.status_code == 200
    assert response.get_json()["response_style"] == "detailed"


def test_patch_proactive_suggestions(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "proactive_suggestions": False,
    })
    assert response.status_code == 200
    assert response.get_json()["proactive_suggestions"] is False


def test_patch_interests(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "interests": ["general_money_questions", "understanding_documents"],
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["interests"] == ["general_money_questions", "understanding_documents"]
    assert isinstance(body["interests"], list)


def test_patch_all_personalization_fields_together(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "financial_experience": "moderate",
        "interests": ["tax_questions", "comparing_options"],
        "response_style": "balanced",
        "proactive_suggestions": False,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["financial_experience"] == "moderate"
    assert body["interests"] == ["tax_questions", "comparing_options"]
    assert body["response_style"] == "balanced"
    assert body["proactive_suggestions"] is False


def test_partial_patch_preserves_unrelated_preferences(client, auth_headers):
    client.patch("/api/preferences", headers=auth_headers, json={
        "currency": "GBP",
        "financial_experience": "advanced",
    })

    response = client.patch("/api/preferences", headers=auth_headers, json={
        "response_style": "simple",
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["response_style"] == "simple"
    # Untouched by this second PATCH — must survive unchanged.
    assert body["currency"] == "GBP"
    assert body["financial_experience"] == "advanced"


def test_patch_rejects_invalid_financial_experience(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "financial_experience": 123,
    })
    assert response.status_code == 400

    response = client.patch("/api/preferences", headers=auth_headers, json={
        "financial_experience": "expert",
    })
    assert response.status_code == 400


def test_patch_rejects_invalid_response_style(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "response_style": "casual",
    })
    assert response.status_code == 400


def test_patch_rejects_interests_not_array(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "interests": "understanding_documents",
    })
    assert response.status_code == 400


def test_patch_rejects_invalid_interest(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "interests": ["fake_topic"],
    })
    assert response.status_code == 400


def test_patch_interests_deduplicates(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "interests": ["financial_concepts", "financial_concepts", "other"],
    })
    assert response.status_code == 200
    assert response.get_json()["interests"] == ["financial_concepts", "other"]


def test_patch_interests_accepts_empty_list(client, auth_headers):
    client.patch("/api/preferences", headers=auth_headers, json={
        "interests": ["other"],
    })

    response = client.patch("/api/preferences", headers=auth_headers, json={
        "interests": [],
    })
    assert response.status_code == 200
    # A deliberate "no topics" selection, distinct from never having
    # answered (which reads back as null — see the defaults test above).
    assert response.get_json()["interests"] == []


def test_patch_rejects_invalid_proactive_suggestions_type(client, auth_headers):
    response = client.patch("/api/preferences", headers=auth_headers, json={
        "proactive_suggestions": "yes",
    })
    assert response.status_code == 400


def test_preferences_update_requires_auth(client):
    response = client.patch("/api/preferences", json={"financial_experience": "beginner"})
    assert response.status_code == 401


def test_personalization_fields_scoped_to_user(client, auth_headers, other_auth_headers):
    client.patch("/api/preferences", headers=auth_headers, json={
        "financial_experience": "advanced",
        "interests": ["tax_questions"],
        "response_style": "detailed",
        "proactive_suggestions": False,
    })

    response = client.get("/api/preferences", headers=other_auth_headers)
    body = response.get_json()
    assert body["financial_experience"] is None
    assert body["interests"] is None
    assert body["response_style"] is None
    assert body["proactive_suggestions"] is True


# --- Regression coverage for the UNIQUE(user_id) race in
# get_or_create_preferences (GET /api/preferences 500'ing with
# "sqlite3.IntegrityError: UNIQUE constraint failed: user_preference.user_id"
# when two first-access requests for the same user overlap). ---

def test_get_or_create_preferences_returns_existing_row_without_duplicating(app, user):
    user_id, _ = user
    with app.app_context():
        existing = get_or_create_preferences(user_id)
        existing_id = existing.id

        result = get_or_create_preferences(user_id)

        assert result.id == existing_id
        assert UserPreference.query.filter_by(user_id=user_id).count() == 1


def test_get_or_create_preferences_creates_exactly_one_row_for_new_user(app, user):
    user_id, _ = user
    with app.app_context():
        assert UserPreference.query.filter_by(user_id=user_id).count() == 0

        preferences = get_or_create_preferences(user_id)

        assert preferences.user_id == user_id
        assert UserPreference.query.filter_by(user_id=user_id).count() == 1


def test_get_or_create_preferences_is_idempotent_across_repeated_calls(app, user):
    user_id, _ = user
    with app.app_context():
        for _ in range(5):
            get_or_create_preferences(user_id)

        assert UserPreference.query.filter_by(user_id=user_id).count() == 1


def test_get_preferences_for_existing_row_returns_200(client, auth_headers, app, user):
    user_id, _ = user
    with app.app_context():
        get_or_create_preferences(user_id)

    response = client.get("/api/preferences", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["currency"] == "NGN"

    with app.app_context():
        assert UserPreference.query.filter_by(user_id=user_id).count() == 1


def test_get_preferences_for_new_user_creates_exactly_one_row(client, auth_headers, app, user):
    user_id, _ = user
    with app.app_context():
        assert UserPreference.query.filter_by(user_id=user_id).count() == 0

    response = client.get("/api/preferences", headers=auth_headers)
    assert response.status_code == 200

    with app.app_context():
        assert UserPreference.query.filter_by(user_id=user_id).count() == 1


def test_get_or_create_preferences_recovers_from_concurrent_insert(app, user, monkeypatch):
    """Simulates the actual race: this call's own existence-check misses
    a row that a "concurrent" request has, by the time of this call's
    commit, already inserted and committed for real. The expected
    IntegrityError must be recovered from (rollback + re-read), never
    raised to the caller, and must never leave a duplicate row behind."""
    from sqlalchemy.orm import Query

    user_id, _ = user

    with app.app_context():
        original_first = Query.first
        call_count = {"n": 0}

        def first_misses_once(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return None
            return original_first(self)

        monkeypatch.setattr(Query, "first", first_misses_once)

        # The "concurrent" request's row, already committed for real by
        # the time this call's own commit is attempted.
        winner = UserPreference(user_id=user_id)
        db.session.add(winner)
        db.session.commit()
        winner_id = winner.id

        # This call's existence-check (patched to miss once, above) finds
        # nothing, so it proceeds to INSERT its own row and collides with
        # `winner` on commit -- the exact production traceback.
        result = get_or_create_preferences(user_id)

        assert result.id == winner_id
        assert UserPreference.query.filter_by(user_id=user_id).count() == 1
        # The session must still be usable after recovering -- not left
        # in a broken/aborted-transaction state.
        assert UserPreference.query.all()
