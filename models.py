from datetime import datetime
from extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)

    country = db.Column(db.String(80), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="NGN")
    occupation = db.Column(db.String(120), nullable=True)
    employment_status = db.Column(db.String(30), nullable=True)
    income = db.Column(db.Float, nullable=True)
    income_frequency = db.Column(db.String(20), nullable=True)
    profile_picture_url = db.Column(db.String(512), nullable=True)
    onboarding_completed = db.Column(db.Boolean, nullable=False, default=False)

    conversations = db.relationship('Conversation', backref='user', lazy=True, cascade="all, delete-orphan")
    activities = db.relationship('Activity', backref='user', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade="all, delete-orphan")
    preferences = db.relationship('UserPreference', backref='user', lazy=True, uselist=False, cascade="all, delete-orphan")
    reminders = db.relationship('Reminder', backref='user', lazy=True, cascade="all, delete-orphan")
    device_tokens = db.relationship('DeviceToken', backref='user', lazy=True, cascade="all, delete-orphan")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False, default="New Conversation")
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade="all, delete-orphan", order_by="Message.created_at")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Conversation {self.id} for User {self.user_id}>'
    


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


    def __repr__(self):
        return f'<Message {self.id} in Conversation {self.conversation_id}>'
    

class UploadFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    key = db.Column(db.String(512), nullable=False, unique=True, index=True)
    original_filename = db.Column(db.String(255), nullable=True)
    size = db.Column(db.Integer, nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False, index=True)
    content_hash = db.Column(db.String(64), nullable=True, index=True)


    document_type = db.Column(db.String(30), nullable=False, default="other")
    financial_period_start = db.Column(db.Date, nullable=True)
    financial_period_end = db.Column(db.Date, nullable=True)
    processing_status = db.Column(db.String(20), nullable=False, default="uploaded")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True, index=True)
    currency = db.Column(db.String(3), nullable=False, default="NGN")
    language = db.Column(db.String(10), nullable=False, default="en")
    notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    document_notifications = db.Column(db.Boolean, nullable=False, default=True)

    financial_experience = db.Column(db.String(20), nullable=True)
    interests = db.Column(db.JSON, nullable=True)
    response_style = db.Column(db.String(20), nullable=True)

    proactive_suggestions = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    activity_metadata = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime, nullable=True)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.String(255), nullable=True)
    read = db.Column(db.Boolean, nullable=False, default=False)
    notification_metadata = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    frequency = db.Column(db.String(20), nullable=False)
    next_billing_date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(30), nullable=True)
    payment_method = db.Column(db.String(30), nullable=True)
    website = db.Column(db.String(512), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<Subscription {self.id} for User {self.user_id}>'


class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    # Always stored as a naive UTC datetime, matching every other
    # DateTime column in this file. The value that reaches here has
    # already been converted from whatever UTC offset the caller
    # supplied (see services.reminder_service) — never a silently
    # assumed offset.
    remind_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="active")  # active, completed, cancelled

    # Set exactly once, atomically, by the reminder delivery worker the
    # moment it claims this reminder for processing (see
    # services/reminder_delivery_service.py). This — not `status` alone
    # — is what prevents the same reminder from generating two
    # notifications if the delivery job runs twice (e.g. overlapping
    # cron ticks): the claim is a single conditional UPDATE ... WHERE
    # notified_at IS NULL, so only one run can ever win it.
    notified_at = db.Column(db.DateTime, nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Reminder {self.id} for User {self.user_id}>'


class DeviceToken(db.Model):
    """An FCM registration token for one app install on one device.

    A token belongs to whichever user most recently registered it, not
    permanently to an account — see services/device_token_service.py
    for why (a token is scoped to a device+app install; it must be
    reassigned, not duplicated, if a different user logs into the same
    physical device). A user may have any number of these (phone,
    tablet, reinstall, etc.) — see push_notification_service.py for how
    they're all targeted on send.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    # FCM registration tokens are opaque and typically well under 300
    # characters in practice, but nothing in the FCM contract guarantees
    # a hard cap — sized generously so a legitimate token is never
    # silently truncated (which would make it permanently unmatchable).
    token = db.Column(db.String(1024), nullable=False, unique=True, index=True)
    platform = db.Column(db.String(20), nullable=False)  # ios, android

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DeviceToken {self.id} for User {self.user_id} ({self.platform})>'