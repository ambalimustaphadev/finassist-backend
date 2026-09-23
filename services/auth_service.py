"""Business logic for registration and login.

Mirrors the shape of subscription_service.py: plain functions, no
Flask/request coupling — callers (authroute/authroute.py) parse the
request, call these, and issue JWTs. JWT issuance stays in the route
because it's a request/framework concern (which token type, what
claims), not a business rule about the user.
"""
from extensions import db
from models import User
from werkzeug.security import check_password_hash, generate_password_hash

REQUIRED_REGISTRATION_FIELDS = ("username", "first_name", "last_name", "email", "password")


class AuthError(Exception):
    """Raised for any expected registration/login failure. Carries the
    exact message and status code authroute.py already returns, so the
    route's existing flat `{"error": "..."}` response shape (which
    Flutter depends on) is unchanged by this extraction."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def user_to_dict(user):
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
    }


def register_user(data):
    """Creates a new user from registration form data. Raises AuthError
    for missing fields (400) or a duplicate username/email (409)."""
    if not all(data.get(field) for field in REQUIRED_REGISTRATION_FIELDS):
        raise AuthError("Missing required fields", 400)

    username = data.get("username")
    email = data.get("email")

    existing_user = User.query.filter(
        (User.username == username) | (User.email == email)
    ).first()
    if existing_user:
        raise AuthError("Username or email already exists", 409)

    user = User(
        username=username,
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        email=email,
        password=generate_password_hash(data.get("password")),
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email, password):
    """Verifies credentials and returns the matching User. Raises
    AuthError(status=401) on any mismatch — deliberately the same
    generic message whether the account doesn't exist or the password
    is wrong, so a client can't enumerate accounts by the error text."""
    if not email or not password:
        raise AuthError("Missing username or password", 400)

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        raise AuthError("Invalid email or password", 401)

    return user
