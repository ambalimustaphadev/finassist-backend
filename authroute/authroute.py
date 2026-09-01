from flask import jsonify, request, Blueprint
from extensions import db
from models import User
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token,create_refresh_token,get_jwt_identity,jwt_required


routes = Blueprint("auth", __name__)


@routes.route("/api/register", methods=["POST"])
def register():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No input provided"}), 400

        username = data.get("username")
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        email = data.get("email")
        password = data.get("password")

        if not all([username, first_name, last_name, email, password]):
            return jsonify({"error": "Missing required fields"}), 400
        

        hash_password = generate_password_hash(password)

        # Check if the username or email already exists
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)).first()

        if existing_user:
            return jsonify({"error": "Username or email already exists"}), 409

        new_user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=hash_password,
        )

        db.session.add(new_user)
        db.session.commit()

        return jsonify({
            "message": "User created successfully",
            "user": {
                "id": new_user.id,
                "username": new_user.username,
                "first_name": new_user.first_name,
                "last_name": new_user.last_name,
                "email": new_user.email,
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"Registration error: {e}")
        return jsonify({"error": "Something went wrong during registration."}), 500
    


@routes.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No input provided"}), 400

        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"error": "Missing username or password"}), 400

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):

            return jsonify({
                "error": "Invalid email or password"
            }), 401
        
        access_token = create_access_token(
            identity=str(user.id)
        )

        refresh_token = create_refresh_token(
            identity=str(user.id)
        )
        return jsonify({
                "message": "Login successful",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                }
            }), 200

    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({"error": "Something went wrong during login."}), 500
    

@routes.route("/api/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    current_user_id = get_jwt_identity()

    new_access_token = create_access_token(
        identity=current_user_id)

    return jsonify({
        "access_token": new_access_token}), 200


@routes.route("/api/me", methods=["GET"])
@jwt_required()
def get_current_user():
    try:
        current_user_id = int(get_jwt_identity())

        user = User.query.get(current_user_id)

        if not user:
            return jsonify({
                "error": "User not found"
            }), 404

        return jsonify({
            "user": {
                "id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
            }
        }), 200

    except Exception as e:
        print(f"Get current user error: {e}")

        return jsonify({
            "error": "Something went wrong."
        }), 500