
import os
import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from spaces import get_spaces_client
from config import Config

from extensions import db
from models import UploadFile


file_routes = Blueprint("files", __name__)


UPLOAD_FOLDER = "uploads"



@file_routes.route("/api/files/upload", methods=["POST"])
@jwt_required()
def upload_file():

    try:
        user_id = int(get_jwt_identity())

        if "file" not in request.files:
            return jsonify({
                "error": "No file provided"
            }), 400

        file = request.files["file"]

        if file.filename == "":
            return jsonify({
                "error": "No file selected"
            }), 400
        
        original_filename = file.filename
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        extension = os.path.splitext(original_filename)[1].lower()

        filename = f"{uuid.uuid4()}{extension}"
        content = file.read()

        # file_path = os.path.join(UPLOAD_FOLDER,filename)

        # file.save(file_path)
        
        file_size = len(content)

        content_type = file.content_type or "application/octet-stream"
        file_key= f"statement/{user_id}.{extension}"
        

            
        try:
            client = get_spaces_client()
            client.put_object(
                Bucket=Config.R2_BUCKET_NAME,
                Key=file_key,
                Body=content,
                ContentType=content_type
            )
        except Exception as e:
            db.session.rollback()

            print(f"File upload error: {e}")

            return jsonify({"error": "Could not upload file"}), 500


        uploaded_file = UploadFile(
            user_id=user_id,
            key=file_key,
            original_filename=original_filename,
            size=file_size,
            content_type=content_type,
            entity_type="statement"
        )

        db.session.add(uploaded_file)
        db.session.commit()

        return jsonify({
            "message": "File uploaded successfully",
            "file": {
                "id": uploaded_file.id,
                "filename": uploaded_file.original_filename,
                "size": uploaded_file.size,
                "content_type": uploaded_file.content_type,
                "key": uploaded_file.key
            }
        }), 201

    except Exception as e:

        db.session.rollback()

        print(f"File upload error: {e}")

        return jsonify({
            "error": "Could not upload file"
        }), 500