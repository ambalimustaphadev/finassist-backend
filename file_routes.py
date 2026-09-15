import hashlib
import os
import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from config import Config
from extensions import db
from models import UploadFile
from services.activity_service import log_activity
from spaces import delete_object, generate_signed_url, get_spaces_client
from utils import (
    ValidationError,
    error_response,
    paginate_query,
    parse_date,
    require_enum,
)


file_routes = Blueprint("files", __name__)


UPLOAD_FOLDER = "uploads"

VIEW_URL_EXPIRATION = 300

DOCUMENT_TYPES = {
    "bank_statement",
    "loan_agreement",
    "investment_document",
    "insurance_document",
    "financial_report",
    "business_document",
    "other",
}


def _file_to_dict(uploaded_file):
    """
    Convert an UploadFile model into a safe API response.
    Important:
    - Never expose the R2 storage key.
    - Never expose a permanent/public R2 URL.
    """

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


@file_routes.route("/api/files/upload", methods=["POST"])
@jwt_required()
def upload_file():
    try:
        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid authentication."
            }), 401

        if "file" not in request.files:
            return jsonify({
                "error": "No file provided"
            }), 400

        file = request.files["file"]

        if not file or file.filename == "":
            return jsonify({
                "error": "No file selected"
            }), 400

        document_type = request.form.get(
            "document_type",
            "other",
        )

        try:
            require_enum(
                document_type,
                DOCUMENT_TYPES,
                "document_type",
            )

            financial_period_start = parse_date(
                request.form.get("financial_period_start"),
                "financial_period_start",
            )

            financial_period_end = parse_date(
                request.form.get("financial_period_end"),
                "financial_period_end",
            )

        except ValidationError as exc:
            return error_response(
                "VALIDATION_ERROR",
                exc.message,
                400,
                exc.details,
            )

        original_filename = file.filename.strip()

        extension = os.path.splitext(original_filename)[1].lower()

        content = file.read()

        if not content:
            return jsonify({
                "error": "The uploaded file is empty."
            }), 400

        file_size = len(content)

        content_type = (
            file.content_type
            or "application/octet-stream"
        )

        # CONTENT HASH
        # Prevent the same physical file from being uploaded
        # multiple times by the same user.
        content_hash = hashlib.sha256(content).hexdigest()

        existing = UploadFile.query.filter_by(user_id=user_id,content_hash=content_hash,).first()

        if existing:
            return jsonify({
                "message": "File already uploaded",
                "file": _file_to_dict(existing),
            }), 200

        # GENERATE PRIVATE R2 KEY
        filename = f"{uuid.uuid4()}{extension}"

        file_key = (
            f"statement/{user_id}/{filename}"
        )

        # UPLOAD TO CLOUDFLARE R2
        try:
            client = get_spaces_client()

            client.put_object(
                Bucket=Config.R2_BUCKET_NAME,
                Key=file_key,
                Body=content,
                ContentType=content_type,
            )

        except Exception:
            db.session.rollback()

            print("File upload error while uploading to R2:")

            import traceback
            traceback.print_exc()

            return jsonify({
                "error": "Could not upload file"
            }), 500


        # CREATE DATABASE RECORD

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

            # Assign ID before creating activity metadata.
            db.session.flush()

            # ACTIVITY
            log_activity(
                user_id,
                "document_uploaded",
                f"Uploaded {original_filename}",
                metadata={
                    "file_id": uploaded_file.id,
                    "document_type": document_type,
                },
            )

            db.session.commit()

        except Exception:
            db.session.rollback()

            # Clean up the orphaned R2 object.
            try:
                delete_object(file_key)
            except Exception:
                pass

            print("File upload database error:")

            import traceback
            traceback.print_exc()

            return jsonify({
                "error": "Could not save uploaded file"
            }), 500


        # RESPONSE
        return jsonify({
            "message": "File uploaded successfully",
            "file": _file_to_dict(uploaded_file),
        }), 201

    except Exception:
        db.session.rollback()

        print("Unexpected file upload error:")

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": "Could not upload file"
        }), 500


@file_routes.route("/api/files", methods=["GET"])
@jwt_required()
def list_files():
    try:

        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid authentication."
            }), 401

        query = UploadFile.query.filter_by(user_id=user_id)

        document_type = request.args.get(
            "document_type"
        )

        if document_type:
            try:
                require_enum(
                    document_type,
                    DOCUMENT_TYPES,
                    "document_type",
                )
            except ValidationError as exc:
                return error_response(
                    "VALIDATION_ERROR",
                    exc.message,
                    400,
                    exc.details,
                )

            query = query.filter_by(
                document_type=document_type
            )

        query = query.order_by(UploadFile.created_at.desc())

        items, pagination = paginate_query(
            query,
            request.args,
        )

        return jsonify({
            "items": [
                _file_to_dict(uploaded_file)
                for uploaded_file in items
            ],
            "pagination": pagination,
        }), 200

    except ValidationError as exc:
        return error_response(
            "VALIDATION_ERROR",
            exc.message,
            400,
            exc.details,
        )

    except Exception:
        print("List files error:")

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": (
                "Something went wrong while "
                "loading your files."
            )
        }), 500


@file_routes.route("/api/files/<int:file_id>",methods=["GET"],)
@jwt_required()
def get_file(file_id):
    try:

        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid authentication."
            }), 401

        uploaded_file = UploadFile.query.filter_by(
            id=file_id,
            user_id=user_id,).first()

        if not uploaded_file:
            return jsonify({
                "error": "File not found"
            }), 404

        return jsonify({
            "file": _file_to_dict(uploaded_file)
        }), 200

    except Exception:
        print("Get file error:")

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": (
                "Something went wrong while "
                "loading the file."
            )
        }), 500


@file_routes.route("/api/files/<int:file_id>/view",methods=["GET"],)
@jwt_required()
def view_file(file_id):
    try:

        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid authentication."
            }), 401

        uploaded_file = UploadFile.query.filter_by(
            id=file_id,
            user_id=user_id,
        ).first()

        if not uploaded_file:
            return jsonify({
                "error": "File not found"
            }), 404

        try:
            url = generate_signed_url(
                uploaded_file.key,
                expires_in=VIEW_URL_EXPIRATION,
            )
        except Exception:
            print(
                f"Could not generate signed URL "
                f"for file_id={file_id}"
            )

            import traceback
            traceback.print_exc()

            return jsonify({
                "error": "Could not access the file."
            }), 500

        return jsonify({
            "url": url,
            "expires_in": VIEW_URL_EXPIRATION,
        }), 200

    except Exception:
        print("View file error:")

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": (
                "Something went wrong while "
                "accessing the file."
            )
        }), 500


@file_routes.route("/api/files/<int:file_id>",methods=["DELETE"],)
@jwt_required()
def delete_file(file_id):
    try:

        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid authentication."
            }), 401


        uploaded_file = UploadFile.query.filter_by(
            id=file_id,
            user_id=user_id,
        ).first()

        if not uploaded_file:
            return jsonify({
                "error": "File not found"
            }), 404


        filename = uploaded_file.original_filename
        file_key = uploaded_file.key

        try:
            delete_object(file_key)
        except Exception:
            print(
                f"Could not delete R2 object "
                f"for file_id={file_id}"
            )

            import traceback
            traceback.print_exc()

            return jsonify({
                "error": "Could not delete file"
            }), 500

        try:
            db.session.delete(uploaded_file)

            log_activity(
                user_id,
                "document_deleted",
                f"Deleted {filename}",
                metadata={
                    "file_id": file_id
                },
            )

            db.session.commit()

        except Exception:
            db.session.rollback()

            print(
                f"Could not delete database record "
                f"for file_id={file_id}"
            )

            import traceback
            traceback.print_exc()

            return jsonify({
                "error": "Could not delete file"
            }), 500

        return jsonify({
            "message": "File deleted successfully"
        }), 200

    except Exception:
        db.session.rollback()

        print("Delete file error:")

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": (
                "Something went wrong while "
                "deleting the file."
            )
        }), 500
