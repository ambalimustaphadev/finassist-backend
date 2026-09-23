import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models import UploadFile
from services.file_service import (
    FileServiceError,
    delete_file,
    file_to_dict,
    list_files,
    upload_file,
)
from spaces import generate_signed_url
from utils import ValidationError, authenticated_user_id_or_none, error_response, get_owned, paginate_query

file_routes = Blueprint("files", __name__)
logger = logging.getLogger(__name__)

VIEW_URL_EXPIRATION = 300


@file_routes.route("/api/files/upload", methods=["POST"])
@jwt_required()
def upload_file_route():
    user_id = authenticated_user_id_or_none()
    if user_id is None:
        return jsonify({"error": "Invalid authentication."}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    try:
        uploaded_file, is_duplicate = upload_file(user_id, file, request.form)
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, 400, exc.details)
    except FileServiceError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        db.session.rollback()
        logger.exception("Unexpected file upload error user_id=%s", user_id)
        return jsonify({"error": "Could not upload file"}), 500

    if is_duplicate:
        return jsonify({
            "message": "File already uploaded",
            "file": file_to_dict(uploaded_file),
        }), 200

    return jsonify({
        "message": "File uploaded successfully",
        "file": file_to_dict(uploaded_file),
    }), 201


@file_routes.route("/api/files", methods=["GET"])
@jwt_required()
def list_files_route():
    user_id = authenticated_user_id_or_none()
    if user_id is None:
        return jsonify({"error": "Invalid authentication."}), 401

    try:
        query = list_files(user_id, request.args.get("document_type"))
        items, pagination = paginate_query(query, request.args)
    except ValidationError as exc:
        return error_response("VALIDATION_ERROR", exc.message, 400, exc.details)
    except Exception:
        logger.exception("List files error user_id=%s", user_id)
        return jsonify({"error": "Something went wrong while loading your files."}), 500

    return jsonify({
        "items": [file_to_dict(f) for f in items],
        "pagination": pagination,
    }), 200


@file_routes.route("/api/files/<int:file_id>", methods=["GET"])
@jwt_required()
def get_file(file_id):
    user_id = authenticated_user_id_or_none()
    if user_id is None:
        return jsonify({"error": "Invalid authentication."}), 401

    try:
        uploaded_file = get_owned(UploadFile, file_id, user_id)

        if not uploaded_file:
            return jsonify({"error": "File not found"}), 404

        return jsonify({"file": file_to_dict(uploaded_file)}), 200

    except Exception:
        logger.exception("Get file error user_id=%s file_id=%s", user_id, file_id)
        return jsonify({"error": "Something went wrong while loading the file."}), 500


@file_routes.route("/api/files/<int:file_id>/view", methods=["GET"])
@jwt_required()
def view_file(file_id):
    user_id = authenticated_user_id_or_none()
    if user_id is None:
        return jsonify({"error": "Invalid authentication."}), 401

    try:
        uploaded_file = get_owned(UploadFile, file_id, user_id)

        if not uploaded_file:
            return jsonify({"error": "File not found"}), 404

        try:
            url = generate_signed_url(uploaded_file.key, expires_in=VIEW_URL_EXPIRATION)
        except Exception:
            logger.exception("Could not generate signed URL for file_id=%s", file_id)
            return jsonify({"error": "Could not access the file."}), 500

        return jsonify({
            "url": url,
            "expires_in": VIEW_URL_EXPIRATION,
        }), 200

    except Exception:
        logger.exception("View file error user_id=%s file_id=%s", user_id, file_id)
        return jsonify({"error": "Something went wrong while accessing the file."}), 500


@file_routes.route("/api/files/<int:file_id>", methods=["DELETE"])
@jwt_required()
def delete_file_route(file_id):
    user_id = authenticated_user_id_or_none()
    if user_id is None:
        return jsonify({"error": "Invalid authentication."}), 401

    try:
        uploaded_file = get_owned(UploadFile, file_id, user_id)

        if not uploaded_file:
            return jsonify({"error": "File not found"}), 404

        try:
            delete_file(uploaded_file)
        except FileServiceError as exc:
            return jsonify({"error": exc.message}), exc.status

        return jsonify({"message": "File deleted successfully"}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Delete file error user_id=%s file_id=%s", user_id, file_id)
        return jsonify({"error": "Something went wrong while deleting the file."}), 500
