import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from services.preference_service import (
    get_or_create_preferences,
    preferences_to_dict,
    update_preferences,
)
from utils import ValidationError, current_user_id, error_response, validation_error_response

preference_routes = Blueprint("preferences", __name__)
logger = logging.getLogger(__name__)


@preference_routes.route("/api/preferences", methods=["GET"])
@jwt_required()
def get_preferences():
    user_id = current_user_id()
    preferences = get_or_create_preferences(user_id)
    return jsonify(preferences_to_dict(preferences)), 200


@preference_routes.route("/api/preferences", methods=["PATCH"])
@jwt_required()
def patch_preferences():
    user_id = current_user_id()
    preferences = get_or_create_preferences(user_id)

    data = request.get_json(silent=True) or {}

    try:
        update_preferences(preferences, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception:
        db.session.rollback()
        logger.exception("Update preferences error user_id=%s", user_id)
        return error_response("INTERNAL_ERROR", "Something went wrong while updating your preferences.", 500)

    return jsonify(preferences_to_dict(preferences)), 200
