import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models import Conversation
from services.conversation_service import (
    conversation_to_dict,
    create_conversation,
    delete_conversation,
    get_messages,
    list_conversations,
    message_to_dict,
)
from utils import current_user_id, get_owned

conversation_routes = Blueprint("conversations", __name__)
logger = logging.getLogger(__name__)


@conversation_routes.route("/api/conversations", methods=["GET"])
@jwt_required()
def get_conversations():
    try:
        conversations = list_conversations(current_user_id())
        return jsonify({"conversations": [conversation_to_dict(c) for c in conversations]}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Get conversations error")
        return jsonify({"error": "Something went wrong while loading conversations."}), 500


@conversation_routes.route("/api/conversations", methods=["POST"])
@jwt_required()
def create_conversation_route():
    try:
        data = request.get_json() or {}
        title = data.get("title", "New Conversation")

        conversation = create_conversation(current_user_id(), title)

        return jsonify({"conversation": conversation_to_dict(conversation)}), 201

    except Exception:
        db.session.rollback()
        logger.exception("Create conversation error")
        return jsonify({
            "error": "Something went wrong while creating the conversation."
        }), 500


@conversation_routes.route("/api/conversations/<int:conversation_id>", methods=["GET"])
@jwt_required()
def get_conversation(conversation_id):
    try:
        conversation = get_owned(Conversation, conversation_id, current_user_id())

        if not conversation:
            return jsonify({
                "error": "Conversation not found"
            }), 404

        messages = get_messages(conversation.id)

        return jsonify({
            "conversation": conversation_to_dict(conversation),
            "messages": [message_to_dict(m) for m in messages],
        }), 200

    except Exception:
        db.session.rollback()
        logger.exception("Get conversation error")
        return jsonify({
            "error": "Something went wrong while loading the conversation."
        }), 500


@conversation_routes.route("/api/conversations/<int:conversation_id>", methods=["DELETE"])
@jwt_required()
def delete_conversation_route(conversation_id):
    try:
        conversation = get_owned(Conversation, conversation_id, current_user_id())

        if not conversation:
            return jsonify({
                "error": "Conversation not found"
            }), 404

        delete_conversation(conversation)

        return jsonify({
            "message": "Conversation deleted successfully"
        }), 200

    except Exception:
        db.session.rollback()
        logger.exception("Delete conversation error")
        return jsonify({
            "error": "Something went wrong while deleting the conversation."
        }), 500
