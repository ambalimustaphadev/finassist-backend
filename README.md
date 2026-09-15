# FinAssist Backend

Backend API for FinAssist, an AI-first personal finance chat assistant. The core product
is AI financial chat: users converse with the AI, upload financial documents for it to
analyze, and keep conversation history. FinAssist does not maintain its own financial
dashboard, goal tracker, or transaction ledger — those are backed entirely by the AI
reading whatever the user uploads or types, not by app-managed financial records.

## Tech Stack

- Python
- Flask
- SQLAlchemy
- Flask-Migrate
- JWT Authentication
- Cloudflare R2
- OpenAI API
- SQLite for development

## Features

- User authentication (JWT access/refresh tokens)
- Profile, preferences, and onboarding state
- Conversations and AI chat, with per-conversation message history
- Financial document uploads with Cloudflare R2 storage and content-hash deduplication,
  analyzed by the AI directly (the backend does not parse or store transactions itself)
- Real application activity history (document activity, profile/preference changes, and
  client-logged calculator usage)
- Notifications

## Project Structure

```text
authroute/            Authentication routes
migrations/           Database migrations
server/               Flask application factory
services/             Business logic for profile/preferences/activity/notifications
chat_routes.py        AI chat routes (protected — see below)
conversation_routes.py
file_routes.py        Document upload/list/get/delete routes
profile_routes.py
preference_routes.py
activity_routes.py
notification_routes.py
models.py             Database models
utils.py              Shared validation/error/pagination helpers for the routes above
spaces.py             Cloudflare R2 client
config.py             Application configuration
tests/                Pytest suite (runs against an in-memory database only)
```

`chat_routes.py`, `conversation_routes.py`, the OpenAI integration, `SYSTEM.MD`, and the
document-attachment flow are intentionally left alone in this phase. Everything else
(profile, preferences, activity, notifications) is normal, deterministic backend logic
with no AI involved.

FinAssist previously included a financial dashboard, a manual goal tracker, and a
transaction ledger. Those have been removed: the product is AI-first chat, and financial
data now flows through AI document analysis rather than app-managed records. See the
migration `d1adc99c11a8_remove_legacy_goal_transaction_tracking.py` for the schema change.

## Setup

```bash
uv sync
cp .env.example .env   # fill in real values
uv run flask db upgrade
uv run python app.py
```

Schema changes are managed entirely through Flask-Migrate/Alembic — the app factory no
longer calls `db.create_all()` on boot, so `flask db upgrade` must be run after cloning or
pulling new migrations.

## Tests

```bash
uv run pytest
```

The test suite always runs against an in-memory SQLite database (enforced by an assertion
in `tests/conftest.py`) and mocks the OpenAI client and R2 client — it never touches your
local `.env` credentials or `instance/mydatabase.db`.

## API

All endpoints except register/login/refresh require `Authorization: Bearer <access_token>`.
Every endpoint below scopes data to the authenticated user (derived from the JWT) — a
client-supplied user id is never trusted.

### Auth

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/register` | none | `username, first_name, last_name, email, password` |
| POST | `/api/login` | none | `email, password` → access + refresh tokens |
| POST | `/api/refresh` | refresh token | Issues a new access token |
| GET | `/api/me` | required | Current user's basic identity |

### Profile

| Method | Path | Notes |
|---|---|---|
| GET | `/api/profile` | Full profile including financial-context fields |
| PATCH | `/api/profile` | Any subset of `first_name, last_name, country, currency, occupation, employment_status, income, income_frequency, onboarding_completed` |
| POST | `/api/profile/picture` | multipart `file` (JPEG/PNG/WEBP, ≤5MB) → uploads to R2, sets `profile_picture_url` |

### Preferences

| Method | Path | Notes |
|---|---|---|
| GET | `/api/preferences` | Created with defaults on first access |
| PATCH | `/api/preferences` | `currency, language, notifications_enabled, document_notifications` |

### Activity

Real events only — nothing here is synthesized to fill out the UI.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/activity` | `?page=&per_page=` |
| GET | `/api/activity/<id>` | |
| POST | `/api/activity` | Only for events the backend has no other way to observe: `currency_conversion, loan_calculation, savings_calculation, affordability_calculation` (client-side calculator usage). Everything else (`profile_updated`, `preferences_updated`, `document_uploaded`, `document_deleted`) is logged automatically by the relevant service. |

### Notifications

| Method | Path | Notes |
|---|---|---|
| GET | `/api/notifications` | `?page=&per_page=` |
| PATCH | `/api/notifications/<id>` | Marks one notification read |
| PATCH | `/api/notifications/read-all` | Marks all read |

Nothing currently creates notifications (no job/event yet triggers one) — the model,
serializer, and endpoints are in place for whichever future feature needs them first.

### Documents

| Method | Path | Notes |
|---|---|---|
| POST | `/api/files/upload` | multipart `file`, optional `document_type` (`bank_statement, loan_agreement, investment_document, insurance_document, financial_report, business_document, other`), optional `financial_period_start`/`financial_period_end` (`YYYY-MM-DD`). Identical content from the same user returns the existing record instead of creating a duplicate. |
| GET | `/api/files` | `?document_type=&page=&per_page=` |
| GET | `/api/files/<id>` | |
| GET | `/api/files/<id>/view` | Returns `{"url": "<temporary signed R2 URL>", "expires_in": 300}` for the authenticated owner. Never returns the internal R2 key or a permanent URL. |
| DELETE | `/api/files/<id>` | Removes the R2 object and the database record |

`financial_period_start`/`financial_period_end` describe when the money in the document
happened, independent of `created_at` (when it was uploaded). This metadata is informational
only — the AI reads the document's actual contents when analyzing it, rather than relying
on these fields.

Financial documents are stored privately in R2 under an internal object key that is never
returned to the client. The client references a document only by `id` (`file_id`); the
backend resolves that to a short-lived signed URL on demand, either for `GET
/api/files/<id>/view` or when attaching the file to a chat message.

### Conversations & Chat (protected — unchanged in this phase)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/conversations` | |
| POST | `/api/conversations` | |
| GET | `/api/conversations/<id>` | Includes full message history |
| DELETE | `/api/conversations/<id>` | |
| POST | `/api/chat` | `message, conversation_id, file_id?` → OpenAI response. `file_id` must belong to the authenticated user; the backend resolves it to a fresh signed URL internally and never accepts a client-supplied file URL. |

### Error format

New endpoints (everything except auth/chat/conversations/files, which keep their existing
flat `{"error": "..."}` shape for backward compatibility with the Flutter app) return:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "...", "details": {}}}
```

Collection endpoints return `{"items": [...], "pagination": {"page", "per_page", "total"}}`.
