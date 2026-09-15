import io

import spaces


def test_public_url_helper_no_longer_exists():
    """Financial documents must never gain a public-URL code path.
    spaces.public_url() relied on the now-disabled r2.dev domain and has
    been removed entirely."""
    assert not hasattr(spaces, "public_url")


def _upload(client, headers, filename="statement.pdf", content=b"hello world", **form):
    data = {"file": (io.BytesIO(content), filename)}
    data.update(form)
    return client.post(
        "/api/files/upload", headers=headers, data=data, content_type="multipart/form-data"
    )


def test_upload_and_list_files(client, auth_headers, fake_r2):
    response = _upload(client, auth_headers)
    assert response.status_code == 201
    assert len(fake_r2.put_calls) == 1

    list_response = client.get("/api/files", headers=auth_headers)
    assert list_response.status_code == 200
    body = list_response.get_json()
    assert body["pagination"]["total"] == 1
    assert body["items"][0]["document_type"] == "other"


def test_upload_with_document_type_and_period(client, auth_headers, fake_r2):
    response = _upload(
        client, auth_headers,
        document_type="bank_statement",
        financial_period_start="2021-01-01",
        financial_period_end="2021-01-31",
    )
    body = response.get_json()["file"]
    assert body["document_type"] == "bank_statement"
    assert body["financial_period_start"] == "2021-01-01"
    assert body["financial_period_end"] == "2021-01-31"


def test_upload_rejects_invalid_document_type(client, auth_headers, fake_r2):
    response = _upload(client, auth_headers, document_type="not_a_type")
    assert response.status_code == 400
    assert fake_r2.put_calls == []


def test_duplicate_upload_does_not_create_second_object(client, auth_headers, fake_r2):
    _upload(client, auth_headers, filename="a.pdf", content=b"same-bytes")
    response = _upload(client, auth_headers, filename="b.pdf", content=b"same-bytes")

    assert response.status_code == 200
    assert response.get_json()["message"] == "File already uploaded"
    assert len(fake_r2.put_calls) == 1

    list_response = client.get("/api/files", headers=auth_headers)
    assert list_response.get_json()["pagination"]["total"] == 1


def test_delete_file(client, auth_headers, fake_r2):
    uploaded = _upload(client, auth_headers).get_json()["file"]

    response = client.delete(f"/api/files/{uploaded['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert len(fake_r2.delete_calls) == 1

    get_response = client.get(f"/api/files/{uploaded['id']}", headers=auth_headers)
    assert get_response.status_code == 404


def test_upload_requires_authentication(client, fake_r2):
    data = {"file": (io.BytesIO(b"hello world"), "statement.pdf")}
    response = client.post(
        "/api/files/upload", data=data, content_type="multipart/form-data"
    )
    assert response.status_code == 401
    assert fake_r2.put_calls == []


def test_file_ownership_enforced(client, auth_headers, other_auth_headers, fake_r2):
    uploaded = _upload(client, auth_headers).get_json()["file"]

    get_response = client.get(f"/api/files/{uploaded['id']}", headers=other_auth_headers)
    assert get_response.status_code == 404

    delete_response = client.delete(f"/api/files/{uploaded['id']}", headers=other_auth_headers)
    assert delete_response.status_code == 404
    assert fake_r2.delete_calls == []

    list_response = client.get("/api/files", headers=other_auth_headers)
    assert list_response.get_json()["pagination"]["total"] == 0


def test_upload_response_never_exposes_internal_storage_details(client, auth_headers, fake_r2):
    response = _upload(client, auth_headers)
    body = response.get_json()["file"]

    assert "key" not in body
    assert "public_url" not in body
    assert "signed_url" not in body
    assert "url" not in body
    assert "file_url" not in body
    assert set(body.keys()) == {
        "id", "filename", "size", "content_type", "document_type",
        "financial_period_start", "financial_period_end",
        "processing_status", "created_at",
    }


def test_view_file_requires_authentication(client, auth_headers, fake_r2):
    uploaded = _upload(client, auth_headers).get_json()["file"]

    response = client.get(f"/api/files/{uploaded['id']}/view")
    assert response.status_code == 401


def test_view_file_enforces_ownership(client, auth_headers, other_auth_headers, fake_r2):
    uploaded = _upload(client, auth_headers).get_json()["file"]

    response = client.get(f"/api/files/{uploaded['id']}/view", headers=other_auth_headers)
    assert response.status_code == 404


def test_view_file_generates_temporary_signed_url(client, auth_headers, fake_r2):
    uploaded = _upload(client, auth_headers).get_json()["file"]

    response = client.get(f"/api/files/{uploaded['id']}/view", headers=auth_headers)
    assert response.status_code == 200

    body = response.get_json()
    assert body["expires_in"] == 300
    assert body["url"].startswith("https://fake-r2.example.com/")
    assert "key" not in body
