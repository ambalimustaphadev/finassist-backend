from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models import Activity
from services.activity_service import CLIENT_LOGGABLE_TYPES, activity_to_dict, log_activity
from utils import ValidationError, error_response, not_found_response, paginate_query, require_non_empty_string, validation_error_response

activity_routes = Blueprint("activity", __name__)


@activity_routes.route("/api/activity", methods=["GET"])
@jwt_required()
def list_activity():
    user_id = int(get_jwt_identity())

    query = Activity.query.filter_by(user_id=user_id).order_by(Activity.created_at.desc())

    items, pagination = paginate_query(query, request.args, default_per_page=20)

    return jsonify({
        "items": [activity_to_dict(a) for a in items],
        "pagination": pagination,
    }), 200


@activity_routes.route("/api/activity/<int:activity_id>", methods=["GET"])
@jwt_required()
def get_activity(activity_id):
    user_id = int(get_jwt_identity())
    activity = Activity.query.filter_by(id=activity_id, user_id=user_id).first()
    if not activity:
        return not_found_response("Activity not found")
    return jsonify(activity_to_dict(activity)), 200


@activity_routes.route("/api/activity", methods=["POST"])
@jwt_required()
def post_activity():
    """Lets the client log activity the backend has no other way to
    observe, such as a calculator that runs entirely in the app. Only
    the client-loggable types are accepted, so this can never be used to
    forge server-side events like `goal_created`."""
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    type_ = data.get("type")
    if type_ not in CLIENT_LOGGABLE_TYPES:
        return error_response(
            "VALIDATION_ERROR",
            f"'{type_}' is not a loggable activity type.",
            400,
            {"type": f"must be one of {sorted(CLIENT_LOGGABLE_TYPES)}"},
        )

    try:
        title = require_non_empty_string(data.get("title"), "title", 120)
    except ValidationError as exc:
        return validation_error_response(exc)

    description = data.get("description")
    metadata = data.get("metadata")

    activity = log_activity(user_id, type_, title, description, metadata)
    db.session.commit()

    return jsonify(activity_to_dict(activity)), 201
