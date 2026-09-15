from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from models import Notification
from services.notification_service import mark_all_read, mark_read, notification_to_dict
from utils import not_found_response, paginate_query

notification_routes = Blueprint("notifications", __name__)


@notification_routes.route("/api/notifications", methods=["GET"])
@jwt_required()
def list_notifications():
    user_id = int(get_jwt_identity())

    query = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc())

    items, pagination = paginate_query(query, request.args, default_per_page=20)

    return jsonify({
        "items": [notification_to_dict(n) for n in items],
        "pagination": pagination,
    }), 200


@notification_routes.route("/api/notifications/<int:notification_id>", methods=["PATCH"])
@jwt_required()
def patch_notification(notification_id):
    user_id = int(get_jwt_identity())
    notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if not notification:
        return not_found_response("Notification not found")

    mark_read(notification)

    return jsonify(notification_to_dict(notification)), 200


@notification_routes.route("/api/notifications/read-all", methods=["PATCH"])
@jwt_required()
def patch_all_notifications():
    user_id = int(get_jwt_identity())
    mark_all_read(user_id)
    return jsonify({"message": "All notifications marked as read"}), 200
