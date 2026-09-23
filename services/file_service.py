"""Business logic for user-uploaded financial documents (bank
statements, payslips, etc — see DOCUMENT_TYPES).

Mirrors the shape of subscription_service.py: plain functions, no
Flask/request coupling. file_routes.py parses the multipart form and
maps the exceptions below onto the endpoints' existing (mixed
structured/flat) error responses — this extraction changes no
response shape, status code, or field.
"""
import hashlib
import os
import uuid

from extensions import db
from models import UploadFile
from services.activity_service import log_activity
from spaces import delete_object, upload_object
from utils import ValidationError, parse_date, require_enum

DOCUMENT_TYPES = {
    "bank_statement",
    "loan_agreement",
    "investment_document",
    "insurance_document",
    "financial_report",
    "business_document",
    "other",
}


class FileServiceError(Exception):
    """Raised for an expected upload/delete failure that isn't a
    ValidationError — carries the exact flat `{"error": message}`
    status/text the route already returns for that failure."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def file_to_dict(uploaded_file):
    """Convert an UploadFile model into a safe API response.
    Important: never expose the R2 storage key or a permanent/public
    R2 URL."""
    return {
        "id": uploaded_file.id,
        "filename": uploaded_file.original_filename,
        "size": uploaded_file.size,
        "content_type": uploaded_file.content_type,
        "document_type": uploaded_file.document_type,
        "financial_period_start": (
            uploaded_file.financial_period_start.isoformat()
            if uploaded_file.financial_period_start
            else None
        ),
        "financial_period_end": (
            uploaded_file.financial_period_end.isoformat()
            if uploaded_file.financial_period_end
            else None
        ),
        "processing_status": uploaded_file.processing_status,
        "created_at": uploaded_file.created_at.isoformat() + "Z",
    }


def upload_file(user_id, file_storage, form):
    """Validates and stores one uploaded document for `user_id`.

    `file_storage` is the werkzeug FileStorage from
    `request.files["file"]` (the route has already confirmed it's
    present with a non-empty filename). `form` is `request.form`
    (document_type/financial_period_start/financial_period_end).

    Returns `(uploaded_file, is_duplicate)` — `is_duplicate` is True
    when this user already uploaded the exact same file content (the
    existing record is returned as-is; nothing new is created).

    Raises ValidationError for a bad document_type/date (the route's
    existing structured-error path), or FileServiceError for anything
    else the route has a specific flat-error response for: an empty
    file, an R2 storage failure, or a database failure.
    """
    document_type = form.get("document_type", "other")
    require_enum(document_type, DOCUMENT_TYPES, "document_type")
    financial_period_start = parse_date(form.get("financial_period_start"), "financial_period_start")
    financial_period_end = parse_date(form.get("financial_period_end"), "financial_period_end")

    original_filename = file_storage.filename.strip()
    extension = os.path.splitext(original_filename)[1].lower()
    content = file_storage.read()

    if not content:
        raise FileServiceError("The uploaded file is empty.", 400)

    file_size = len(content)
    content_type = file_storage.content_type or "application/octet-stream"

    # Prevent the same physical file from being uploaded multiple
    # times by the same user.
    content_hash = hashlib.sha256(content).hexdigest()
    existing = UploadFile.query.filter_by(user_id=user_id, content_hash=content_hash).first()
    if existing:
        return existing, True

    file_key = f"statement/{user_id}/{uuid.uuid4()}{extension}"

    try:
        upload_object(file_key, content, content_type)
    except Exception as exc:
        db.session.rollback()
        raise FileServiceError("Could not upload file", 500) from exc

    try:
        uploaded_file = UploadFile(
            user_id=user_id,
            key=file_key,
            original_filename=original_filename,
            size=file_size,
            content_type=content_type,
            content_hash=content_hash,
            entity_type="statement",
            document_type=document_type,
            financial_period_start=financial_period_start,
            financial_period_end=financial_period_end,
        )
        db.session.add(uploaded_file)
        db.session.flush()  # assign an id before the activity metadata needs it

        log_activity(
            user_id,
            "document_uploaded",
            f"Uploaded {original_filename}",
            metadata={"file_id": uploaded_file.id, "document_type": document_type},
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        # Clean up the orphaned R2 object — delete_object already
        # swallows its own failures (see spaces.py), so this never
        # masks the real error below.
        delete_object(file_key)
        raise FileServiceError("Could not save uploaded file", 500) from exc

    return uploaded_file, False


def list_files(user_id, document_type=None):
    """Returns the (not-yet-executed) query for `user_id`'s files,
    newest first, optionally filtered by document_type — the route
    still runs it through `utils.paginate_query` itself, since paging
    is a request-parameter concern. Raises ValidationError for an
    unrecognized document_type."""
    query = UploadFile.query.filter_by(user_id=user_id)
    if document_type:
        require_enum(document_type, DOCUMENT_TYPES, "document_type")
        query = query.filter_by(document_type=document_type)
    return query.order_by(UploadFile.created_at.desc())


def delete_file(uploaded_file):
    """Deletes the R2 object then the database row, logging activity.
    Raises FileServiceError("Could not delete file", 500) if the
    database step fails."""
    filename = uploaded_file.original_filename
    file_id = uploaded_file.id
    file_key = uploaded_file.key
    user_id = uploaded_file.user_id

    delete_object(file_key)

    try:
        db.session.delete(uploaded_file)
        log_activity(user_id, "document_deleted", f"Deleted {filename}", metadata={"file_id": file_id})
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise FileServiceError("Could not delete file", 500) from exc
