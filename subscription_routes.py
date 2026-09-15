from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models import Subscription
from services.subscription_service import (
    create_subscription,
    subscription_to_dict,
    update_subscription,
)
from utils import ValidationError, error_response, not_found_response, validation_error_response

subscription_routes = Blueprint("subscriptions", __name__)


@subscription_routes.route("/api/subscriptions", methods=["GET"])
@jwt_required()
def list_subscriptions():
    user_id = int(get_jwt_identity())

    subscriptions = (
        Subscription.query.filter_by(user_id=user_id)
        .order_by(Subscription.next_billing_date.asc(), Subscription.id.asc())
        .all()
    )

    return jsonify([subscription_to_dict(s) for s in subscriptions]), 200


@subscription_routes.route("/api/subscriptions", methods=["POST"])
@jwt_required()
def post_subscription():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    try:
        subscription = create_subscription(user_id, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception as e:
        db.session.rollback()
        print(f"Create subscription error: {e}")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while creating your subscription.", 500
        )

    return jsonify(subscription_to_dict(subscription)), 201


@subscription_routes.route("/api/subscriptions/<int:subscription_id>", methods=["GET"])
@jwt_required()
def get_subscription(subscription_id):
    user_id = int(get_jwt_identity())
    subscription = Subscription.query.filter_by(id=subscription_id, user_id=user_id).first()
    if not subscription:
        return not_found_response("Subscription not found")
    return jsonify(subscription_to_dict(subscription)), 200


@subscription_routes.route("/api/subscriptions/<int:subscription_id>", methods=["PATCH"])
@jwt_required()
def patch_subscription(subscription_id):
    user_id = int(get_jwt_identity())
    subscription = Subscription.query.filter_by(id=subscription_id, user_id=user_id).first()
    if not subscription:
        return not_found_response("Subscription not found")

    data = request.get_json(silent=True) or {}

    try:
        update_subscription(subscription, data)
    except ValidationError as exc:
        db.session.rollback()
        return validation_error_response(exc)
    except Exception as e:
        db.session.rollback()
        print(f"Update subscription error: {e}")
        return error_response(
            "INTERNAL_ERROR", "Something went wrong while updating your subscription.", 500
        )

    return jsonify(subscription_to_dict(subscription)), 200


@subscription_routes.route("/api/subscriptions/<int:subscription_id>", methods=["DELETE"])
@jwt_required()
def delete_subscription(subscription_id):
    user_id = int(get_jwt_identity())
    subscription = Subscription.query.filter_by(id=subscription_id, user_id=user_id).first()
    if not subscription:
        return not_found_response("Subscription not found")

    db.session.delete(subscription)
    db.session.commit()

    return jsonify({"message": "Subscription deleted successfully"}), 200
