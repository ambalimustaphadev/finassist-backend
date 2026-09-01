
import hashlib
import os
import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from spaces import get_spaces_client, public_url
from config import Config

from extensions import db
from models import UploadFile


file_routes = Blueprint("files", __name__)


UPLOAD_FOLDER = "uploads"


def _file_to_dict(uploaded_file):
    return {
        "id": uploaded_file.id,
        "filename": uploaded_file.original_filename,
        "size": uploaded_file.size,
        "content_type": uploaded_file.content_type,
        "key": uploaded_file.key,
        "file_url": public_url(uploaded_file.key),
    }


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

        content = file.read()
        file_size = len(content)
        content_type = file.content_type or "application/octet-stream"

        # Identify identical content this user has already uploaded (by
        # the bytes, never the filename, since two different documents
        # can share a filename) so re-selecting the same statement from
        # Chat or Profile never creates a second R2 object or database
        # row for it — one document, one UploadFile record, referenced
        # from wherever it's needed.
        content_hash = hashlib.sha256(content).hexdigest()
        existing = UploadFile.query.filter_by(
            user_id=user_id, content_hash=content_hash
        ).first()
        if existing:
            return jsonify({
                "message": "File already uploaded",
                "file": _file_to_dict(existing),
            }), 200

        filename = f"{uuid.uuid4()}{extension}"
        # One folder per user, one unique object per file. The previous
        # key (`statement/{user_id}.{extension}`) collapsed every upload
        # from the same user onto a single R2 object, silently
        # overwriting the previous statement each time.
        file_key = f"statement/{user_id}/{filename}"

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
            content_hash=content_hash,
            entity_type="statement"
        )

        db.session.add(uploaded_file)
        db.session.commit()

        return jsonify({
            "message": "File uploaded successfully",
            "file": _file_to_dict(uploaded_file),
        }), 201

    except Exception as e:

        db.session.rollback()

        print(f"File upload error: {e}")

        return jsonify({
            "error": "Could not upload file"
        }), 500


@file_routes.route("/api/files/<int:file_id>", methods=["GET"])
@jwt_required()
def get_file(file_id):
    """Looks up a single uploaded file's metadata (including its R2
    file_url), always scoped to the authenticated user — changing the id
    in the URL can never reveal another user's document."""
    try:
        user_id = int(get_jwt_identity())

        uploaded_file = UploadFile.query.filter_by(
            id=file_id, user_id=user_id
        ).first()

        if not uploaded_file:
            return jsonify({"error": "File not found"}), 404

        return jsonify({"file": _file_to_dict(uploaded_file)}), 200

    except Exception as e:
        print(f"Get file error: {e}")

        return jsonify({
            "error": "Something went wrong while loading the file."
        }), 500