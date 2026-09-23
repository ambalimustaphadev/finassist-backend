import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from services.profile_service import (
    profile_to_dict,
    save_profile_picture,
    update_profile,
    validate_profile_picture,
)
from utils import ValidationError, current_user, error_response, not_found_response, validation_error_response

logger = logging.getLogger(__name__)

profile_routes = Blueprint("profile", __name__)


@profile_routes.route("/api/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user = current_user()
    if not user:
        return not_found_response("User not found")
    return jsonify(profile_to_dict(user)), 200


@profile_routes.route("/api/profile", methods=["PATCH"])
@jwt_required()
def patch_profile():
    user = current_user()
    if not user:
        return not_found_response("User not found")

    data = request.get_json(silent=True) or {}

    try:
        update_profile(user, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception:
        db.session.rollback()
        logger.exception("Update profile error")
        return error_response("INTERNAL_ERROR", "Something went wrong while updating your profile.", 500)

    return jsonify(profile_to_dict(user)), 200


@profile_routes.route("/api/profile/picture", methods=["POST"])
@jwt_required()
def upload_profile_picture():
    user = current_user()
    if not user:
        return not_found_response("User not found")

    if "file" not in request.files:
        return error_response("VALIDATION_ERROR", "No file provided.", 400)

    file = request.files["file"]
    if file.filename == "":
        return error_response("VALIDATION_ERROR", "No file selected.", 400)

    content_type = file.content_type or "application/octet-stream"
    content = file.read()

    try:
        validate_profile_picture(content_type, content)
    except ValidationError as exc:
        return validation_error_response(exc)

    try:
        # Stores the private R2 object key, never a public URL. The
        # client gets a short-lived signed URL back via profile_to_dict().
        save_profile_picture(user, content, content_type, file.filename)
    except Exception:
        logger.exception("Profile picture upload error")
        return error_response("INTERNAL_ERROR", "Could not upload profile picture.", 500)

    return jsonify(profile_to_dict(user)), 200
