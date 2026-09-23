import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from services.chat_service import ChatServiceError, process_chat
from utils import authenticated_user_id_or_none

chat_routes = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)


@chat_routes.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    try:
        current_user_id = authenticated_user_id_or_none()
        if current_user_id is None:
            logger.warning("Invalid JWT identity")
            return jsonify({"error": "Invalid authentication."}), 401

        data = request.get_json(silent=True)

        if not data:
            return jsonify({"error": "No input provided"}), 400

        try:
            result = process_chat(current_user_id, data)
        except ChatServiceError as exc:
            return jsonify({"error": exc.message}), exc.status

        return jsonify(result), 200

    except Exception:
        db.session.rollback()
        logger.exception("Unexpected error")
        return jsonify({
            "error": "Something went wrong while processing your message."
        }), 500
