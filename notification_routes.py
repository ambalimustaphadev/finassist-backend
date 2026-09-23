import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models import Notification
from services.device_token_service import (
    delete_device_token,
    device_token_to_dict,
    register_device_token,
)
from services.notification_service import (
    list_notifications as list_notifications_query,
    mark_all_read,
    mark_read,
    notification_to_dict,
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

notification_routes = Blueprint("notifications", __name__)
logger = logging.getLogger(__name__)


@notification_routes.route("/api/notifications", methods=["GET"])
@jwt_required()
def list_notifications():
    user_id = current_user_id()

    query = list_notifications_query(user_id)

    items, pagination = paginate_query(query, request.args, default_per_page=20)

    return jsonify({
        "items": [notification_to_dict(n) for n in items],
        "pagination": pagination,
    }), 200


@notification_routes.route("/api/notifications/<int:notification_id>", methods=["PATCH"])
@jwt_required()
def patch_notification(notification_id):
    user_id = current_user_id()
    notification = get_owned(Notification, notification_id, user_id)
    if not notification:
        return not_found_response("Notification not found")

    mark_read(notification)

    return jsonify(notification_to_dict(notification)), 200


@notification_routes.route("/api/notifications/read-all", methods=["PATCH"])
@jwt_required()
def patch_all_notifications():
    user_id = current_user_id()
    mark_all_read(user_id)
    return jsonify({"message": "All notifications marked as read"}), 200


@notification_routes.route("/api/notifications/device-token", methods=["POST"])
@jwt_required()
def post_device_token():
    """Registers (or re-registers) an FCM device token for the
    authenticated user. user_id always comes from the JWT — the request
    body only ever supplies `token`/`platform`, never a user id."""
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}

    try:
        device_token = register_device_token(user_id, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception:
        db.session.rollback()
        logger.exception("Device token registration error user_id=%s", user_id)
        return error_response(
            "INTERNAL_ERROR",
            "Something went wrong while registering the device token.",
            500,
        )

    return jsonify(device_token_to_dict(device_token)), 200


@notification_routes.route("/api/notifications/device-token", methods=["DELETE"])
@jwt_required()
def delete_device_token_route():
    """Unregisters one device token belonging to the authenticated
    user (e.g. on logout/sign-out on that device). A token that
    doesn't exist, or belongs to another user, is reported as not
    found either way — never which case it was."""
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}
    token = data.get("token")

    if not isinstance(token, str) or not token.strip():
        return error_response(
            "VALIDATION_ERROR", "token is required.", 400, {"token": "required"}
        )

    removed = delete_device_token(user_id, token.strip())
    if not removed:
        return not_found_response("Device token not found")

    return jsonify({"message": "Device token removed"}), 200
