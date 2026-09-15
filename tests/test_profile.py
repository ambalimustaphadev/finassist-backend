import io

import spaces
from config import Config


def test_get_own_profile(client, auth_headers):
    response = client.get("/api/profile", headers=auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["username"] == "user_a"
    assert body["currency"] == "NGN"
    assert body["onboarding_completed"] is False


def test_update_own_profile(client, auth_headers):
    response = client.patch("/api/profile", headers=auth_headers, json={
        "country": "Nigeria",
        "currency": "usd",
        "occupation": "Engineer",
        "employment_status": "employed",
        "income": 500000,
        "income_frequency": "monthly",
        "onboarding_completed": True,
    })
    assert response.status_code == 200
    body = response.get_json()
    assert body["country"] == "Nigeria"
    assert body["currency"] == "USD"
    assert body["income"] == 500000
    assert body["onboarding_completed"] is True


def test_update_profile_rejects_bad_currency(client, auth_headers):
    response = client.patch("/api/profile", headers=auth_headers, json={"currency": "ZZZ"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_cannot_update_another_users_profile(client, auth_headers, other_auth_headers, other_user):
    other_user_id, _ = other_user

    client.patch("/api/profile", headers=auth_headers, json={"occupation": "Attacker"})

    response = client.get("/api/profile", headers=other_auth_headers)
    assert response.get_json()["occupation"] is None


def test_profile_requires_auth(client):
    response = client.get("/api/profile")
    assert response.status_code == 401


def _stored_profile_picture(client, user_id):
    with client.application.app_context():
        from models import User
        return User.query.get(user_id).profile_picture_url


def _upload_picture(client, headers, filename="avatar.jpg", content=b"fake image bytes", content_type="image/jpeg"):
    return client.post(
        "/api/profile/picture",
        headers=headers,
        data={"file": (io.BytesIO(content), filename, content_type)},
        content_type="multipart/form-data",
    )


def test_public_url_helper_no_longer_exists():
    """spaces.public_url() relied on the now-disabled r2.dev public
    domain. It must be fully removed, not just unused, so neither the
    financial-document nor the profile-picture code path can ever call
    it by accident."""
    assert not hasattr(spaces, "public_url")


def test_upload_profile_picture_requires_authentication(client):
    response = client.post(
        "/api/profile/picture",
        data={"file": (io.BytesIO(b"bytes"), "avatar.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_upload_profile_picture_rejects_missing_file(client, auth_headers):
    response = client.post(
        "/api/profile/picture",
        headers=auth_headers,
        data={},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_profile_picture_rejects_empty_filename(client, auth_headers):
    response = client.post(
        "/api/profile/picture",
        headers=auth_headers,
        data={"file": (io.BytesIO(b"bytes"), "", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_profile_picture_rejects_unsupported_type(client, auth_headers, fake_r2):
    response = _upload_picture(client, auth_headers, filename="avatar.gif", content_type="image/gif")
    assert response.status_code == 400
    assert fake_r2.put_calls == []


def test_upload_profile_picture_rejects_oversized_file(client, auth_headers, fake_r2):
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    response = _upload_picture(client, auth_headers, content=oversized)
    assert response.status_code == 400
    assert fake_r2.put_calls == []


def test_upload_profile_picture_succeeds_for_allowed_types(client, auth_headers, fake_r2):
    for filename, content_type in [
        ("avatar.jpg", "image/jpeg"),
        ("avatar.png", "image/png"),
        ("avatar.webp", "image/webp"),
    ]:
        response = _upload_picture(client, auth_headers, filename=filename, content_type=content_type)
        assert response.status_code == 200
        body = response.get_json()
        # Existing Flutter contract: the field is profile_picture_url.
        assert "profile_picture_url" in body
        assert body["profile_picture_url"].startswith("https://fake-r2.example.com/profile-pictures/")


def test_upload_profile_picture_stores_object_key_not_url(client, auth_headers, user, fake_r2):
    user_id, _ = user
    response = _upload_picture(client, auth_headers)
    assert response.status_code == 200

    stored = _stored_profile_picture(client, user_id)
    assert stored is not None
    assert stored.startswith(f"profile-pictures/{user_id}/")
    assert not stored.startswith("http")
    assert "r2.dev" not in stored
    assert "expires_in" not in stored  # never a signed URL either


def test_get_profile_returns_temporary_signed_url_for_existing_picture(client, auth_headers, fake_r2):
    _upload_picture(client, auth_headers)

    response = client.get("/api/profile", headers=auth_headers)
    assert response.status_code == 200
    url = response.get_json()["profile_picture_url"]
    assert url.startswith("https://fake-r2.example.com/profile-pictures/")
    assert "expires_in=300" in url


def test_profile_picture_url_none_when_not_set(client, auth_headers):
    response = client.get("/api/profile", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["profile_picture_url"] is None


def test_user_cannot_retrieve_another_users_profile_picture(client, auth_headers, other_auth_headers, fake_r2):
    _upload_picture(client, auth_headers)

    response = client.get("/api/profile", headers=other_auth_headers)
    assert response.status_code == 200
    assert response.get_json()["profile_picture_url"] is None


def test_replacing_profile_picture_deletes_old_object_and_updates_key(client, auth_headers, user, fake_r2):
    user_id, _ = user

    first = _upload_picture(client, auth_headers, filename="first.jpg")
    assert first.status_code == 200
    first_key = _stored_profile_picture(client, user_id)

    second = _upload_picture(client, auth_headers, filename="second.png", content_type="image/png")
    assert second.status_code == 200
    second_key = _stored_profile_picture(client, user_id)

    assert second_key != first_key
    assert len(fake_r2.put_calls) == 2
    assert (Config.R2_BUCKET_NAME, first_key) in fake_r2.delete_calls


def test_legacy_public_url_profile_picture_still_resolves(client, auth_headers, user, fake_r2):
    """Rows written before r2.dev was disabled stored a full public URL.
    Reading them must not require a data migration: the object key is
    recovered from the URL's path and a fresh signed URL is generated
    from it."""
    user_id, _ = user
    legacy_key = f"profile-pictures/{user_id}/legacy-uuid.jpg"

    with client.application.app_context():
        from extensions import db
        from models import User
        legacy_user = User.query.get(user_id)
        legacy_user.profile_picture_url = f"https://pub-oldbucket.r2.dev/{legacy_key}"
        db.session.commit()

    response = client.get("/api/profile", headers=auth_headers)
    assert response.status_code == 200
    url = response.get_json()["profile_picture_url"]

    assert url.startswith(f"https://fake-r2.example.com/{legacy_key}")
    assert "r2.dev" not in url
