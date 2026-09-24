import re
from datetime import datetime

from extensions import db
from models import Subscription
from utils import (
    ValidationError,
    iso_date,
    iso_datetime,
    parse_date,
    require_currency,
    require_enum,
    require_non_empty_string,
    require_number,
)

FREQUENCIES = {"weekly", "monthly", "quarterly", "semiannual", "yearly"}
CATEGORIES = {
    "entertainment",
    "software",
    "cloud_storage",
    "education",
    "fitness",
    "news_media",
    "productivity",
    "shopping",
    "gaming",
    "other",
}

# Loose, natural-language category phrases -> canonical CATEGORIES
# value. Used only by normalize_category (the AI tool path); the REST
# API keeps accepting exactly the canonical values. The display labels
# the Flutter client shows ("Cloud & Storage", "News & Media") are
# included so a model echoing a label still lands on the stored value.
_CATEGORY_ALIASES = {
    "entertainment": (
        "entertainment", "music", "streaming", "movies", "movie", "film",
        "films", "tv", "television", "video", "video streaming",
        "music streaming",
    ),
    "software": (
        "software", "app", "apps", "application", "applications", "saas",
        "developer software", "developer tools", "coding software", "ai",
    ),
    "cloud_storage": (
        "cloud storage", "cloud and storage", "cloud", "storage",
        "online storage", "backup", "cloud services", "hosting",
    ),
    "education": (
        "education", "learning", "school", "course", "courses", "training",
        "study", "e learning", "language learning",
    ),
    "fitness": (
        "fitness", "gym", "workout", "health club", "exercise", "sports",
    ),
    "news_media": (
        "news media", "news and media", "news", "media", "newspaper",
        "magazine", "magazines", "journalism", "publication",
    ),
    "productivity": (
        "productivity", "work", "work tools", "organization",
        "organisation", "task management", "project management",
        "notes", "note taking",
    ),
    "shopping": (
        "shopping", "retail", "ecommerce", "e commerce", "purchases",
        "delivery",
    ),
    "gaming": (
        "gaming", "games", "game", "video games", "playstation", "xbox",
        "steam", "nintendo",
    ),
    "other": ("other", "others", "miscellaneous", "misc"),
}

# Well-known services, used only to infer a category when the caller
# gave none. Deliberately short: anything not recognisable here falls
# back to "other" rather than a guess.
_SERVICE_CATEGORY_HINTS = {
    "entertainment": (
        "netflix", "spotify", "disney", "hulu", "showmax", "dstv", "gotv",
        "apple music", "apple tv", "youtube premium", "youtube music",
        "prime video", "amazon prime video", "hbo", "paramount", "peacock",
        "deezer", "tidal", "audiomack", "boomplay", "crunchyroll",
    ),
    "software": (
        "chatgpt", "openai", "claude", "adobe", "github", "copilot",
        "jetbrains", "figma", "canva", "cursor",
    ),
    "cloud_storage": (
        "google one", "google drive", "icloud", "dropbox", "onedrive",
        "aws", "amazon web services", "azure", "google cloud",
        "digitalocean", "backblaze",
    ),
    "education": (
        "udemy", "coursera", "duolingo", "skillshare", "masterclass",
        "linkedin learning", "codecademy", "brilliant",
    ),
    "fitness": ("peloton", "strava", "fitbit", "myfitnesspal", "classpass"),
    "news_media": (
        "cnn", "new york times", "nytimes", "bloomberg", "economist",
        "wall street journal", "wsj", "financial times", "washington post",
        "medium", "substack",
    ),
    "productivity": (
        "notion", "evernote", "todoist", "trello", "asana", "slack", "zoom",
        "microsoft 365", "office 365", "grammarly", "calendly", "clickup",
    ),
    "shopping": ("amazon prime", "jumia prime", "walmart", "costco", "instacart"),
    "gaming": (
        "playstation", "ps plus", "xbox", "game pass", "steam", "nintendo",
        "ea play", "roblox",
    ),
}


def _normalize_phrase(value):
    """'News & Media' / 'news_media' / ' Cloud-Storage ' -> 'news and
    media' / 'news media' / 'cloud storage'."""
    text = value.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _build_lookup(table):
    lookup = {}
    for category, phrases in table.items():
        lookup[_normalize_phrase(category)] = category
        for phrase in phrases:
            lookup[_normalize_phrase(phrase)] = category
    return lookup


_ALIAS_LOOKUP = _build_lookup(_CATEGORY_ALIASES)
_HINT_LOOKUP = {
    _normalize_phrase(phrase): category
    for category, phrases in _SERVICE_CATEGORY_HINTS.items()
    for phrase in phrases
}


def _longest_phrase_match(text, lookup):
    padded = f" {text} "
    matches = [phrase for phrase in lookup if f" {phrase} " in padded]
    if not matches:
        return None
    return lookup[max(matches, key=len)]


def normalize_category(value):
    """Maps a loose category ('Entertainment', 'music', 'cloud & storage',
    'SaaS') to a canonical CATEGORIES value, or None if it can't be
    reasonably interpreted. Never returns anything outside CATEGORIES."""
    if not isinstance(value, str):
        return None
    phrase = _normalize_phrase(value)
    if not phrase:
        return None
    if phrase in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[phrase]
    # e.g. 'online music streaming' or 'developer software': accept it
    # only if the recognised words all agree on one category.
    categories = {_ALIAS_LOOKUP[word] for word in phrase.split() if word in _ALIAS_LOOKUP}
    return categories.pop() if len(categories) == 1 else None


def infer_category(service_name):
    """Best-effort category for a service the caller didn't categorise:
    a known service ('Netflix', 'Google One') first, then a category
    word in the name itself ('my gym membership'), else 'other'. The
    longest matching phrase wins, so 'Amazon Prime Video' (listed under
    entertainment) beats 'Amazon Prime' (shopping)."""
    if not isinstance(service_name, str):
        return "other"
    phrase = _normalize_phrase(service_name)
    return (
        _longest_phrase_match(phrase, _HINT_LOOKUP)
        or _longest_phrase_match(phrase, _ALIAS_LOOKUP)
        or "other"
    )


PAYMENT_METHODS = {
    "debit_card",
    "credit_card",
    "bank_account",
    "mobile_wallet",
    "direct_debit",
    "cash",
    "other",
}
STATUSES = {"active", "paused", "cancelled"}


def _require_positive_amount(value):
    number = require_number(value, "amount")
    if number <= 0:
        raise ValidationError(
            "amount must be greater than zero.", {"amount": "must be greater than zero"}
        )
    return number


def _require_billing_date(value):
    if not value:
        raise ValidationError(
            "next_billing_date is required.", {"next_billing_date": "required"}
        )
    return parse_date(value, "next_billing_date")


def list_subscriptions(user_id):
    return (
        Subscription.query.filter_by(user_id=user_id)
        .order_by(Subscription.next_billing_date.asc(), Subscription.id.asc())
        .all()
    )


def delete_subscription(subscription):
    db.session.delete(subscription)
    db.session.commit()


def subscription_to_dict(subscription):
    return {
        "id": subscription.id,
        "user_id": subscription.user_id,
        "name": subscription.name,
        "amount": subscription.amount,
        "currency": subscription.currency,
        "frequency": subscription.frequency,
        "next_billing_date": iso_date(subscription.next_billing_date),
        "category": subscription.category,
        "payment_method": subscription.payment_method,
        "website": subscription.website,
        "notes": subscription.notes,
        "status": subscription.status,
        "created_at": iso_datetime(subscription.created_at),
        "updated_at": iso_datetime(subscription.updated_at),
        "cancelled_at": iso_datetime(subscription.cancelled_at),
    }


def create_subscription(user_id, data):
    name = require_non_empty_string(data.get("name"), "name", 120)
    amount = _require_positive_amount(data.get("amount"))
    currency = require_currency(data.get("currency"))
    frequency = require_enum(data.get("frequency"), FREQUENCIES, "frequency")
    next_billing_date = _require_billing_date(data.get("next_billing_date"))

    category_value = data.get("category")
    category = require_enum(category_value, CATEGORIES, "category") if category_value else None

    payment_method_value = data.get("payment_method")
    payment_method = (
        require_enum(payment_method_value, PAYMENT_METHODS, "payment_method")
        if payment_method_value
        else None
    )

    website_value = data.get("website")
    website = require_non_empty_string(website_value, "website", 512) if website_value else None

    notes_value = data.get("notes")
    notes = require_non_empty_string(notes_value, "notes", 2000) if notes_value else None

    subscription = Subscription(
        user_id=user_id,
        name=name,
        amount=amount,
        currency=currency,
        frequency=frequency,
        next_billing_date=next_billing_date,
        category=category,
        payment_method=payment_method,
        website=website,
        notes=notes,
        status="active",
        cancelled_at=None,
    )
    db.session.add(subscription)
    db.session.commit()
    return subscription


def update_subscription(subscription, data):
    if "name" in data:
        subscription.name = require_non_empty_string(data["name"], "name", 120)

    if "amount" in data:
        subscription.amount = _require_positive_amount(data["amount"])

    if "currency" in data:
        subscription.currency = require_currency(data["currency"])

    if "frequency" in data:
        subscription.frequency = require_enum(data["frequency"], FREQUENCIES, "frequency")

    if "next_billing_date" in data:
        subscription.next_billing_date = _require_billing_date(data["next_billing_date"])

    if "category" in data:
        value = data["category"]
        subscription.category = require_enum(value, CATEGORIES, "category") if value else None

    if "payment_method" in data:
        value = data["payment_method"]
        subscription.payment_method = (
            require_enum(value, PAYMENT_METHODS, "payment_method") if value else None
        )

    if "website" in data:
        value = data["website"]
        subscription.website = require_non_empty_string(value, "website", 512) if value else None

    if "notes" in data:
        value = data["notes"]
        subscription.notes = require_non_empty_string(value, "notes", 2000) if value else None

    if "status" in data:
        new_status = require_enum(data["status"], STATUSES, "status")
        subscription.status = new_status
        if new_status == "cancelled":
            subscription.cancelled_at = datetime.utcnow()
        else:
            subscription.cancelled_at = None

    db.session.commit()
    return subscription
