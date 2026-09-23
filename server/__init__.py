from file_routes import file_routes
from conversation_routes import conversation_routes
from chat_routes import chat_routes
from profile_routes import profile_routes
from preference_routes import preference_routes
from activity_routes import activity_routes
from notification_routes import notification_routes
from subscription_routes import subscription_routes
from tools_routes import tools_routes
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
    app.register_blueprint(tools_routes)

    _register_cli_commands(app)

    return app


def _register_cli_commands(app):
    """Flask CLI commands are how background/scheduled work runs in
    this app — there is no in-process scheduler (see
    services/reminder_delivery_service.py's module docstring for why).
    A production deployment invokes this on a schedule via an external
    scheduler (cron, a platform scheduled job, a Kubernetes CronJob);
    it is never called from inside a web request.
    """
    @app.cli.command("deliver-due-reminders")
    def deliver_due_reminders_command():
        """Delivers every reminder that is currently due. Safe to run
        repeatedly/concurrently — see reminder_delivery_service.py.
        Intended to be invoked periodically by an external scheduler,
        e.g. a cron entry such as:

            * * * * * cd /path/to/app && flask deliver-due-reminders >> /var/log/finassist-reminders.log 2>&1
        """
        from services.reminder_delivery_service import deliver_due_reminders

        summary = deliver_due_reminders()
        print(f"Reminder delivery: due={summary['due']} delivered={summary['delivered']}")

