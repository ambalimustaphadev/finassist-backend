import logging
import os
import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from config import Config
from extensions import db
from models import User
from services.profile_service import profile_to_dict, set_profile_picture, update_profile
from spaces import get_spaces_client
from utils import ValidationError, error_response, not_found_response, validation_error_response

logger = logging.getLogger(__name__)

profile_routes = Blueprint("profile", __name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB


def _current_user():
    user_id = int(get_jwt_identity())
    return User.query.get(user_id)


@profile_routes.route("/api/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user = _current_user()
    if not user:
        return not_found_response("User not found")
    return jsonify(profile_to_dict(user)), 200


@profile_routes.route("/api/profile", methods=["PATCH"])
@jwt_required()
def patch_profile():
    user = _current_user()
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
    user = _current_user()
    if not user:
        return not_found_response("User not found")

    if "file" not in request.files:
        return error_response("VALIDATION_ERROR", "No file provided.", 400)

    file = request.files["file"]
    if file.filename == "":
        return error_response("VALIDATION_ERROR", "No file selected.", 400)

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_IMAGE_TYPES:
        return error_response(
            "VALIDATION_ERROR",
            "Profile picture must be a JPEG, PNG, or WEBP image.",
            400,
            {"content_type": "unsupported"},
        )

    content = file.read()
    if len(content) > MAX_IMAGE_SIZE:
        return error_response(
            "VALIDATION_ERROR", "Profile picture must be 5MB or smaller.", 400
        )

    extension = os.path.splitext(file.filename)[1].lower()
    file_key = f"profile-pictures/{user.id}/{uuid.uuid4()}{extension}"

    try:
        client = get_spaces_client()
        client.put_object(
            Bucket=Config.R2_BUCKET_NAME,
            Key=file_key,
            Body=content,
            ContentType=content_type,
        )
    except Exception:
        logger.exception("Profile picture upload error")
        return error_response("INTERNAL_ERROR", "Could not upload profile picture.", 500)

    # Store the private R2 object key, never a public URL. The client
    # gets a short-lived signed URL back via profile_to_dict().
    set_profile_picture(user, file_key)

    return jsonify(profile_to_dict(user)), 200
