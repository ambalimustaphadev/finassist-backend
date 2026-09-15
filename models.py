from datetime import datetime
from extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # bank_id = db.Column(db.Integer, default=1)
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
    # chat_histories = db.relationship('ChatHistory', backref='user', lazy=True)
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


# class ChatHistory(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
#     message = db.Column(db.Text, nullable=False)
#     response = db.Column(db.Text, nullable=False)
#     created_at = db.Column(db.DateTime, default=datetime.utcnow)


#     def __repr__(self):
#         return f'<ChatHistory {self.id} for User {self.user_id}>'