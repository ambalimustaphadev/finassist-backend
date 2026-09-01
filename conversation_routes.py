from datetime import datetime
import json

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models import Conversation, Message


conversation_routes = Blueprint( "conversations", __name__,)


def conversation_to_dict(conversation):
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat() + "Z",
        "updated_at": conversation.updated_at.isoformat() + "Z",
    }


def _deserialize_content(raw):
    """Mirrors `chat_routes._deserialize_content` — a message that
    attached a file is stored as a JSON-encoded content-parts list;
    everything else is stored (and returned) as plain text."""
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw
    return raw


def message_to_dict(message):
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": _deserialize_content(message.content),
        "created_at": message.created_at.isoformat() + "Z",
    }


@conversation_routes.route("/api/conversations",methods=["GET"],)
@jwt_required()
def get_conversations():
    try:
        current_user_id = int(get_jwt_identity())

        conversations = (Conversation.query.filter_by(user_id=current_user_id).order_by(Conversation.updated_at.desc() ).all())

        return jsonify({ "conversations": [conversation_to_dict(conversation)for conversation in conversations]}), 200

    except Exception as e:
        print(f"Get conversations error: {e}")

        return jsonify({"error": "Something went wrong while loading conversations."}), 500


@conversation_routes.route("/api/conversations",methods=["POST"],)
@jwt_required()
def create_conversation():
    try:
        current_user_id = int(get_jwt_identity())

        data = request.get_json() or {}

        title = data.get("title", "New Conversation",)

        title = str(title).strip()

        if not title:
            title = "New Conversation"

        conversation = Conversation(user_id=current_user_id,title=title,)

        db.session.add(conversation)
        db.session.commit()

        return jsonify({"conversation": conversation_to_dict(conversation)}), 201

    except Exception as e:
        db.session.rollback()

        print(f"Create conversation error: {e}")

        return jsonify({
            "error": "Something went wrong while creating the conversation."
        }), 500


@conversation_routes.route("/api/conversations/<int:conversation_id>",methods=["GET"],)
@jwt_required()
def get_conversation(conversation_id):
    try:
        current_user_id = int(get_jwt_identity())

        conversation = (Conversation.query.filter_by(id=conversation_id,user_id=current_user_id,).first())

        if not conversation:
            return jsonify({
                "error": "Conversation not found"
            }), 404

        messages = (Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at.asc()).all())

        return jsonify({
            "conversation": conversation_to_dict(conversation),
            "messages": [
                message_to_dict(message)
                for message in messages
            ],
        }), 200

    except Exception as e:
        print(f"Get conversation error: {e}")

        return jsonify({
            "error": "Something went wrong while loading the conversation."
        }), 500


@conversation_routes.route("/api/conversations/<int:conversation_id>",methods=["DELETE"],)
@jwt_required()
def delete_conversation(conversation_id):
    try:
        current_user_id = int(get_jwt_identity())

        conversation = (Conversation.query.filter_by(id=conversation_id,user_id=current_user_id,).first())

        if not conversation:
            return jsonify({
                "error": "Conversation not found"
            }), 404

        db.session.delete(conversation)
        db.session.commit()

        return jsonify({
            "message": "Conversation deleted successfully"
        }), 200

    except Exception as e:
        db.session.rollback()

        print(f"Delete conversation error: {e}")

        return jsonify({
            "error": "Something went wrong while deleting the conversation."
        }), 500