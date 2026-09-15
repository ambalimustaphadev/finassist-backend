from file_routes import file_routes
from conversation_routes import conversation_routes
from profile_routes import profile_routes
from preference_routes import preference_routes
from activity_routes import activity_routes
from notification_routes import notification_routes
from subscription_routes import subscription_routes
from extensions import db, migrate, jwt
from flask import Flask
from config import Config

from authroute.authroute import routes


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        # Must be applied before db.init_app(app) — Flask-SQLAlchemy reads
        # SQLALCHEMY_DATABASE_URI at init time, so a test suite overriding
        # it afterward would silently keep binding to the real database.
        app.config.update(config_overrides)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)


    from chat_routes import chat_routes
     # Register blueprints
    app.register_blueprint(routes)
    app.register_blueprint(conversation_routes)
    app.register_blueprint(chat_routes)
    app.register_blueprint(file_routes)
    app.register_blueprint(profile_routes)
    app.register_blueprint(preference_routes)
    app.register_blueprint(activity_routes)
    app.register_blueprint(notification_routes)
    app.register_blueprint(subscription_routes)

    return app

