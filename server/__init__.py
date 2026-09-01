import os

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from file_routes import file_routes
from conversation_routes import conversation_routes
from extensions import db, migrate, jwt
from flask import Flask
from config import Config
from datetime import timedelta
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity

from authroute.authroute import routes 

from dotenv import load_dotenv

load_dotenv()


# # Initialize extensions
# db.init_app(app)
# migrate.init_app(app, db)
# jwt = JWTManager(app)


# # Register blueprints
# app.register_blueprint(routes)
# app.register_blueprint(conversation_routes)
# app.register_blueprint(chat_routes)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
   
    
    from chat_routes import chat_routes
     # Register blueprints
    app.register_blueprint(routes)
    app.register_blueprint(conversation_routes)
    app.register_blueprint(chat_routes)
    app.register_blueprint(file_routes)
    

        # Create tables
    with app.app_context():
        db.create_all()

    return app

