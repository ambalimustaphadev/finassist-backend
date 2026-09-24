import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models import Activity
from services.activity_service import (
    activity_to_dict,
    list_activity as list_activity_query,
    record_client_activity,
)
from utils import (
    ValidationError,
    current_user_id,
    error_response,
    get_owned,
    not_found_response,
    paginate_query,
    validation_error_response,
)

activity_routes = Blueprint("activity", __name__)
logger = logging.getLogger(__name__)


@activity_routes.route("/api/activity", methods=["GET"])
@jwt_required()
def list_activity():
    user_id = current_user_id()

    try:
        query = list_activity_query(user_id)
        items, pagination = paginate_query(query, request.args, default_per_page=20)
    except Exception:
        logger.exception("List activity error user_id=%s", user_id)
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while loading activity.", 500
        )

    return jsonify({
        "items": [activity_to_dict(a) for a in items],
        "pagination": pagination,
    }), 200


@activity_routes.route("/api/activity/<int:activity_id>", methods=["GET"])
@jwt_required()
def get_activity(activity_id):
    user_id = current_user_id()
    try:
        activity = get_owned(Activity, activity_id, user_id)
    except Exception:
        logger.exception("Get activity error user_id=%s activity_id=%s", user_id, activity_id)
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while loading activity.", 500
        )
    if not activity:
        return not_found_response("Activity not found")
    return jsonify(activity_to_dict(activity)), 200


@activity_routes.route("/api/activity", methods=["POST"])
@jwt_required()
def post_activity():
    """Lets the client log activity the backend has no other way to
    observe, such as a completed currency conversion. Only
    the client-loggable types are accepted, so this can never be used to
    forge server-side events like `goal_created`."""
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}

    try:
        activity = record_client_activity(
            user_id,
            data.get("type"),
            data.get("title"),
            data.get("description"),
            data.get("metadata"),
        )
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception:
        db.session.rollback()
        logger.exception("Create activity error user_id=%s", user_id)
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while recording activity.", 500
        )

    return jsonify(activity_to_dict(activity)), 201
