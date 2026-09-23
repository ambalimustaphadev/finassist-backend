import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models import Subscription
from services import subscription_service
from services.subscription_service import (
    create_subscription,
    subscription_to_dict,
    update_subscription,
)
from utils import (
    ValidationError,
    current_user_id,
    error_response,
    get_owned,
    not_found_response,
    validation_error_response,
)

subscription_routes = Blueprint("subscriptions", __name__)
logger = logging.getLogger(__name__)


@subscription_routes.route("/api/subscriptions", methods=["GET"])
@jwt_required()
def list_subscriptions():
    user_id = current_user_id()

    subscriptions = subscription_service.list_subscriptions(user_id)

    return jsonify([subscription_to_dict(s) for s in subscriptions]), 200


@subscription_routes.route("/api/subscriptions", methods=["POST"])
@jwt_required()
def post_subscription():
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}

    try:
        subscription = create_subscription(user_id, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception:
        db.session.rollback()
        logger.exception("Create subscription error user_id=%s", user_id)
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while creating your subscription.", 500
        )

    return jsonify(subscription_to_dict(subscription)), 201


@subscription_routes.route("/api/subscriptions/<int:subscription_id>", methods=["GET"])
@jwt_required()
def get_subscription(subscription_id):
    user_id = current_user_id()
    subscription = get_owned(Subscription, subscription_id, user_id)
    if not subscription:
        return not_found_response("Subscription not found")
    return jsonify(subscription_to_dict(subscription)), 200


@subscription_routes.route("/api/subscriptions/<int:subscription_id>", methods=["PATCH"])
@jwt_required()
def patch_subscription(subscription_id):
    user_id = current_user_id()
    subscription = get_owned(Subscription, subscription_id, user_id)
    if not subscription:
        return not_found_response("Subscription not found")

    data = request.get_json(silent=True) or {}

    try:
        update_subscription(subscription, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception:
        db.session.rollback()
        logger.exception("Update subscription error user_id=%s subscription_id=%s", user_id, subscription_id)
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while updating your subscription.", 500
        )

    return jsonify(subscription_to_dict(subscription)), 200


@subscription_routes.route("/api/subscriptions/<int:subscription_id>", methods=["DELETE"])
@jwt_required()
def delete_subscription(subscription_id):
    user_id = current_user_id()
    subscription = get_owned(Subscription, subscription_id, user_id)
    if not subscription:
        return not_found_response("Subscription not found")

    subscription_service.delete_subscription(subscription)

    return jsonify({"message": "Subscription deleted successfully"}), 200
