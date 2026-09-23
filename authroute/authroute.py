import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt_identity, jwt_required

from extensions import db
from services.auth_service import AuthError, authenticate_user, register_user, user_to_dict
from utils import current_user

routes = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)


@routes.route("/api/register", methods=["POST"])
def register():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No input provided"}), 400

        user = register_user(data)

        return jsonify({
            "message": "User created successfully",
            "user": user_to_dict(user),
        }), 201

    except AuthError as exc:
        db.session.rollback()
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        db.session.rollback()
        logger.exception("Registration error")
        return jsonify({"error": "Something went wrong during registration."}), 500


@routes.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No input provided"}), 400

        user = authenticate_user(data.get("email"), data.get("password"))

        access_token = create_access_token(identity=str(user.id))
        refresh_token = create_refresh_token(identity=str(user.id))

        return jsonify({
            "message": "Login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_to_dict(user),
        }), 200

    except AuthError as exc:
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        logger.exception("Login error")
        return jsonify({"error": "Something went wrong during login."}), 500


@routes.route("/api/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()

    new_access_token = create_access_token(identity=identity)

    return jsonify({
        "access_token": new_access_token}), 200


@routes.route("/api/me", methods=["GET"])
@jwt_required()
def get_current_user():
    try:
        user = current_user()

        if not user:
            return jsonify({
                "error": "User not found"
            }), 404

        return jsonify({"user": user_to_dict(user)}), 200

    except Exception:
        logger.exception("Get current user error")

        return jsonify({
            "error": "Something went wrong."
        }), 500
