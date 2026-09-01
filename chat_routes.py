from datetime import datetime

from flask import app, Blueprint, jsonify, request

from openai import OpenAIError
from config import Config
from flask_jwt_extended import get_jwt_identity,jwt_required

from extensions import db
from models import Conversation, Message



chat_routes = Blueprint("chat", __name__,)


try:
    from openai import OpenAI
    client  = OpenAI(
        api_key=Config.OPEN_AI_KEY)
except ImportError:
        app.config['OPENAI_CLIENT'] = None
except OpenAIError:
        print("open ai key not found")


def message_to_dict(message):
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat() + "Z",
    }


def generate_title(message):
    """
    Creates a simple conversation title from
    the user's first message.

    This intentionally does not make another
    OpenAI request just to create a title.
    """

    title = message.strip()

    if not title:
        return "New Conversation"

    # Remove excessive whitespace.
    title = " ".join(title.split())

    # Keep titles short.
    if len(title) > 50:
        title = title[:50].rstrip() + "..."

    return title


@chat_routes.route("/api/chat",methods=["POST"],)
@jwt_required()
def chat():
    try:
        current_user_id = int(get_jwt_identity())

        data = request.get_json()

        if not data:
            return jsonify({
                "error": "No input provided"
            }), 400

        message = data.get("message")

        conversation_id = data.get("conversation_id")

        if not message:
            return jsonify({
                "error": "No message provided"
            }), 400

        message = message.strip()

        if not message:
            return jsonify({
                "error": "No message provided"
            }), 400

        if conversation_id is None:
            return jsonify({
                "error": "conversation_id is required"
            }), 400

        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return jsonify({
                "error": "Invalid conversation_id"
            }), 400


        # Find the conversation belonging to this user.
        conversation = Conversation.query.filter_by(id=conversation_id,user_id=current_user_id,).first()

        if not conversation:
            return jsonify({
                "error": "Conversation not found"
            }), 404


        # Load THIS conversation's history only.
        previous_messages = (Message.query.filter_by(conversation_id=conversation.id).order_by(Message.created_at.asc()).all())


        # Build OpenAI conversation input.
        conversation_history = []

        for previous_message in previous_messages:

            conversation_history.append({
                "role": previous_message.role,
                "content": previous_message.content,
            })

        # Add the new user message.
        conversation_history.append({
            "role": "user",
            "content": message,
        })

        # Load system prompt.
        system_prompt = ""

        with open("SYSTEM.MD", "r") as f:
            system_prompt = f.read()

        response = client.responses.create(
            model="gpt-5.6-luna",
            instructions=system_prompt,
            input=conversation_history,
        )

        ai_response = response.output_text

        if not ai_response:
            return jsonify({
                "error": "The AI returned an empty response."
            }), 500

        # Save user message.
        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            content=message,
        )

        db.session.add(user_message)

        # Save assistant message.
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=ai_response,
        )

        db.session.add(assistant_message)

 
        # Automatically generate a title if this is the first message in the conversation.
        if not previous_messages:conversation.title = generate_title(message)

        conversation.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            "conversation_id": conversation.id,
            "response": ai_response,
            "message": {
                "id": assistant_message.id,
                "role": assistant_message.role,
                "content": assistant_message.content,
                "created_at": (
                    assistant_message.created_at.isoformat()
                    + "Z"
                ),
            },
        }), 200

    except Exception as e:
        db.session.rollback()

        print(f"Chat error: {e}")

        return jsonify({
            "error": "Something went wrong while processing your message."
        }), 500