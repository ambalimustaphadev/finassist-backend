# FinAssist Backend API

FinAssist is an AI-first personal finance chat application. The backend is a Flask API providing authentication, AI chat, conversation history, financial document storage, user profile, preferences, activity logging, and notifications.

This document describes the API exactly as implemented in the current backend. It does not describe planned features or removed features.

## Base URL

There is no production deployment configured anywhere in the codebase. The app runs as a local development server ([app.py](app.py)):

```
http://localhost:5002
```

## Authentication

Authentication uses JWT, sent as a bearer token:

```
Authorization: Bearer <access_token>
```

- `POST /api/login` returns an access token (valid 1 hour) and a refresh token (valid 30 days).
- `POST /api/refresh` exchanges a valid refresh token for a new access token.
- Every endpoint listed below requires the access token unless stated otherwise.
- No custom JWT error handlers are registered in the app. Missing, malformed, or expired tokens are handled entirely by `flask-jwt-extended`'s default error responses, not by application code.
- There is no logout, password reset, or token revocation endpoint.

## Response and Error Format

There is no single response envelope across the whole API — each endpoint shapes its own success body. Error bodies take one of two shapes, depending on which part of the app handles the request.

Authentication, Conversations, Chat, and most of the Financial Files API return a flat shape:

```json
{
  "error": "Human readable message"
}
```

Profile, Preferences, Activity, Notifications, Subscriptions, Tools, and file-upload validation errors return a structured shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human readable message",
    "details": {
      "field": "reason"
    }
  }
}
```

Each endpoint below lists only the errors that endpoint can actually return.

---

## Authentication API

### POST `/api/register`

Creates a new user account.

**Authentication**

None.

**Request**

```json
{
  "username": "jane_doe",
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane@example.com",
  "password": "plain-text-password"
}
```

**Request fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | Yes | Must be unique. |
| `first_name` | string | Yes | |
| `last_name` | string | Yes | |
| `email` | string | Yes | Must be unique. No email-format check is performed. |
| `password` | string | Yes | Stored as a `werkzeug` password hash. No strength requirement is enforced. |

**Success**

`201` with the created user's basic fields:

```json
{
  "message": "User created successfully",
  "user": {
    "id": 1,
    "username": "jane_doe",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com"
  }
}
```

**Validation**

All five fields must be present and truthy. There is no separate length, format, or password-strength validation beyond that.

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | No JSON body, or one of the required fields is missing/empty. |
| 409 | The username or email is already taken. |
| 500 | Unexpected server error. |

### POST `/api/login`

Authenticates a user and issues tokens.

**Authentication**

None.

**Request**

```json
{
  "email": "jane@example.com",
  "password": "plain-text-password"
}
```

**Success**

`200`:

```json
{
  "message": "Login successful",
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "user": {
    "id": 1,
    "username": "jane_doe",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com"
  }
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | Missing email or password. |
| 401 | No user with that email, or the password does not match. Both cases return the same message. |
| 500 | Unexpected server error. |

### POST `/api/refresh`

Issues a new access token from a valid refresh token.

**Authentication**

Required — the refresh token, not the access token, sent as the bearer token.

**Success**

`200`:

```json
{
  "access_token": "<new jwt>"
}
```

### GET `/api/me`

Returns the authenticated user's basic account fields.

**Authentication**

Required.

**Success**

`200`:

```json
{
  "user": {
    "id": 1,
    "username": "jane_doe",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com"
  }
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | The user referenced by the token no longer exists. |
| 500 | Unexpected server error. |

---

## Chat API

### POST `/api/chat`

Sends a message to the AI assistant inside a conversation, optionally with a previously uploaded financial document attached, and returns the assistant's reply.

**Authentication**

Required.

**Request**

```json
{
  "message": "Can you summarize this statement?",
  "conversation_id": 12,
  "file_id": 34
}
```

**Request fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `conversation_id` | integer | Yes | Must belong to the caller. |
| `message` | string | Conditional | Required unless `file_id` is present — a file with no accompanying text is a valid turn. Maximum 20,000 characters. |
| `file_id` | integer | No | Must belong to the caller if present. |

**Success**

`200`:

```json
{
  "conversation_id": 12,
  "response": "Here is a summary...",
  "message": {
    "id": 102,
    "conversation_id": 12,
    "role": "assistant",
    "content": "Here is a summary...",
    "created_at": "2026-09-15T10:00:00Z"
  }
}
```

**AI and context behavior**

- The AI model is `gpt-5.6-luna`, called through the OpenAI Responses API.
- Only the most recent 20 messages in the conversation are sent to OpenAI as context — the full history is not resent on every turn.
- Attachments from earlier turns in that context window are not re-sent to the model. They are replaced with a short text placeholder noting that a document was attached at that point. Only the file attached in the *current* request is resolved to a signed URL and sent to OpenAI.
- The signed URL for the current attachment expires after 300 seconds and is never persisted — only the file's database ID is stored with the message.
- The conversation title is generated from the first message on the conversation's first turn.
- There is no web search, function calling, tool calling, autonomous agent behavior, or persistent AI memory. Each request is a single call to the Responses API with the recent message window as input.

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | No JSON body; `message` is not a string; neither `message` nor `file_id` provided; missing or invalid `conversation_id`; invalid `file_id`. |
| 401 | JWT identity could not be parsed as a user ID. |
| 404 | `conversation_id` does not exist or is not owned by the caller; `file_id` does not exist or is not owned by the caller. |
| 413 | `message` exceeds 20,000 characters. |
| 500 | The system prompt file (`SYSTEM.MD`) could not be loaded, or generating the signed URL for the attached file failed. |
| 502 | The OpenAI request failed, or returned an empty response. |

---

## Conversations API

Every endpoint is scoped to the caller's own conversations. A conversation owned by a different user returns `404`, not `403`. The list endpoint is not paginated — it returns every conversation the user has.

### GET `/api/conversations`

Lists the caller's conversations, newest-updated first.

**Authentication**

Required.

**Success**

`200`:

```json
{
  "conversations": [
    {
      "id": 12,
      "title": "Loan payoff plan",
      "created_at": "2026-09-15T10:00:00Z",
      "updated_at": "2026-09-15T10:05:00Z"
    }
  ]
}
```

### POST `/api/conversations`

Creates a new, empty conversation.

**Authentication**

Required.

**Request**

```json
{
  "title": "Optional title"
}
```

`title` is optional and defaults to `"New Conversation"` if omitted or blank.

**Success**

`201` with the created conversation object.

### GET `/api/conversations/<conversation_id>`

Returns a conversation with its full message history, oldest first, with no limit.

**Authentication**

Required.

**Success**

`200`:

```json
{
  "conversation": {
    "id": 12,
    "title": "Loan payoff plan",
    "created_at": "2026-09-15T10:00:00Z",
    "updated_at": "2026-09-15T10:05:00Z"
  },
  "messages": [
    {
      "id": 101,
      "conversation_id": 12,
      "role": "user",
      "content": "Can you summarize this statement?",
      "created_at": "2026-09-15T10:00:00Z"
    }
  ]
}
```

A user message that included a file attachment has `content` shaped as `{"text": "...", "file_id": 34}` instead of a plain string. No signed URL is included in this response — call `GET /api/files/<file_id>/view` separately to get one.

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | Conversation not found, or not owned by the caller. |

### DELETE `/api/conversations/<conversation_id>`

Deletes one conversation and all of its messages.

**Authentication**

Required.

**Behavior**

Deleting a conversation cascades to its messages (`Message` rows are removed via the model's cascade relationship). It does not delete any financial documents referenced by those messages — files are independent records the client must delete separately, if desired, through the Financial Files API.

**Success**

`200`:

```json
{
  "message": "Conversation deleted successfully"
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | Conversation not found, or not owned by the caller. |

---

## Financial Files API

Financial documents are stored as private objects in a Cloudflare R2 bucket. There is no public URL for them — public `r2.dev` access is disabled on the bucket. Every read of file contents goes through a signed URL generated on demand; the client only ever works with a numeric `file_id`, never an R2 object key or a permanent URL. Every endpoint below enforces per-user ownership and returns `404` for a file that exists but belongs to another user.

### POST `/api/files/upload`

Uploads a financial document.

**Authentication**

Required, `multipart/form-data`.

**Request fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | Must be non-empty. No file size limit or content-type restriction is enforced by this endpoint. |
| `document_type` | string | No | Defaults to `other`. Must be one of `bank_statement`, `loan_agreement`, `investment_document`, `insurance_document`, `financial_report`, `business_document`, `other`. |
| `financial_period_start` | string | No | ISO date, `YYYY-MM-DD`. |
| `financial_period_end` | string | No | ISO date, `YYYY-MM-DD`. |

**Duplicate detection**

The backend computes a SHA-256 hash of the uploaded file's content. If the same user has already uploaded a file with the same hash, no new object is written to R2 and no new database row is created — the existing file record is returned with status `200` instead of `201`. Duplicate detection is scoped per user; two different users uploading the same physical file each get their own record.

**Storage**

New files are written to `statement/{user_id}/{uuid}{extension}` in the private R2 bucket. The client never receives this key.

**Success**

`201` for a new file, or `200` for a deduplicated one:

```json
{
  "message": "File uploaded successfully",
  "file": {
    "id": 34,
    "filename": "statement.pdf",
    "size": 128332,
    "content_type": "application/pdf",
    "document_type": "bank_statement",
    "financial_period_start": "2026-08-01",
    "financial_period_end": "2026-08-31",
    "processing_status": "uploaded",
    "created_at": "2026-09-15T10:00:00Z"
  }
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | No `file` part in the request, an empty filename, an empty file body, an invalid `document_type`, or a malformed date. |
| 500 | The upload to R2 failed, or the database record could not be created (in which case the newly written R2 object is cleaned up). |

### GET `/api/files`

Lists the caller's financial documents.

**Authentication**

Required.

**Query parameters**

| Parameter | Description |
|---|---|
| `page` | Defaults to 1. |
| `per_page` | Defaults to 20, capped at 100. |
| `document_type` | Optional filter, must be a valid document type. |

Results are ordered by `created_at` descending.

**Success**

`200`:

```json
{
  "items": [ { "id": 34, "filename": "statement.pdf", "...": "..." } ],
  "pagination": { "page": 1, "per_page": 20, "total": 3 }
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | `document_type` filter is not a recognized value. |
| 500 | Unexpected server error. |

### GET `/api/files/<file_id>`

Returns metadata for one file. Never returns file contents or a signed URL.

**Authentication**

Required.

**Success**

`200` — `{"file": {...}}`, same shape as the upload response's `file` object.

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | File not found, or not owned by the caller. |

### GET `/api/files/<file_id>/view`

Generates a temporary signed URL for reading the file's contents directly from R2.

**Authentication**

Required.

**Behavior**

A fresh signed URL is generated on every call. It is not cached or stored anywhere in the database, and it expires after 300 seconds.

**Success**

`200`:

```json
{
  "url": "https://<signed-r2-url>",
  "expires_in": 300
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | File not found, or not owned by the caller. |
| 500 | Signing the URL failed. |

### DELETE `/api/files/<file_id>`

Deletes one financial document. This removes only the single file identified by `file_id` — it does not delete any other document, any conversation, the user's profile, or any other financial information.

**Authentication**

Required.

**Behavior**

The endpoint attempts to delete the R2 object, then deletes the `UploadFile` database row and logs a `document_deleted` activity. The R2 delete call (`spaces.delete_object`) silently swallows any exception it encounters internally — it never raises, even if the underlying request to R2 fails. In practice this means the database record is always removed once this endpoint reaches that step, whether or not the R2 object was actually deleted; there is no code path in which the R2 delete failing leaves the file record in place.

**Success**

`200`:

```json
{
  "message": "File deleted successfully"
}
```

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | File not found, or not owned by the caller. |
| 500 | The database delete raised an exception (the R2 delete step cannot trigger this, per the behavior above). |

---

## Profile API

### GET `/api/profile`

Returns the authenticated user's profile.

**Authentication**

Required.

**Success**

`200`:

```json
{
  "id": 1,
  "username": "jane_doe",
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane@example.com",
  "country": "Nigeria",
  "currency": "NGN",
  "occupation": "Engineer",
  "employment_status": "employed",
  "income": 500000.0,
  "income_frequency": "monthly",
  "profile_picture_url": "https://<signed-url>",
  "onboarding_completed": true,
  "created_at": "2026-09-15T10:00:00Z",
  "updated_at": "2026-09-15T10:00:00Z"
}
```

`profile_picture_url` is resolved to a fresh 300-second signed URL on every call, or `null` if the user has not set a picture.

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | User behind the token no longer exists. |

### PATCH `/api/profile`

Partially updates the profile. Only the fields present in the request body are changed.

**Authentication**

Required.

**Request fields**

| Field | Validation |
|---|---|
| `first_name` | Non-empty string, max 80 characters. |
| `last_name` | Non-empty string, max 80 characters. |
| `country` | Non-empty string (max 80 characters), or `null`/empty to clear. |
| `currency` | Must be one of the supported currency codes (see Preferences API). Case-insensitive, normalized to uppercase. |
| `occupation` | Non-empty string (max 120 characters), or `null`/empty to clear. |
| `employment_status` | One of `employed`, `self_employed`, `unemployed`, `student`, `retired`, `other`, or `null`/empty to clear. |
| `income` | Number, `>= 0`, or `null` to clear. |
| `income_frequency` | One of `weekly`, `biweekly`, `monthly`, `yearly`, or `null`/empty to clear. |
| `onboarding_completed` | Boolean. |

`username` and `email` are returned in the response but are not accepted by this endpoint — there is no code path that updates either field here.

**Success**

`200` with the full, updated profile object (same shape as `GET /api/profile`).

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | A field failed validation (structured error with `code: "VALIDATION_ERROR"`). |
| 404 | User behind the token no longer exists. |
| 500 | Unexpected server error. |

### POST `/api/profile/picture`

Uploads a new profile picture.

**Authentication**

Required, `multipart/form-data`, field `file`.

**Validation**

| Rule | Detail |
|---|---|
| Content type | Must be `image/jpeg`, `image/png`, or `image/webp`. |
| Size | Must be 5 MB or smaller. |

**Behavior**

The image is stored privately in R2 at `profile-pictures/{user_id}/{uuid}{extension}`. Only the object key is persisted on the user record — never a public URL. If the user already had a picture, its old R2 object is deleted after the new key is saved; that cleanup call also silently swallows failures, so an old, orphaned image never causes this endpoint to report an error.

**Success**

`200` with the full, updated profile object. `profile_picture_url` is a fresh signed URL pointing at the new picture.

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | No file provided, empty filename, unsupported content type, or file larger than 5 MB (structured error). |
| 404 | User behind the token no longer exists. |
| 500 | The upload to R2 failed. |

---

## Preferences API

### GET `/api/preferences`

Returns the authenticated user's preferences. If no preferences row exists yet, a default one is created on first access.

**Authentication**

Required.

**Success**

`200`:

```json
{
  "currency": "NGN",
  "language": "en",
  "notifications_enabled": true,
  "document_notifications": true,
  "financial_experience": "beginner",
  "interests": ["understanding_documents"],
  "response_style": "balanced",
  "proactive_suggestions": true,
  "updated_at": "2026-09-15T10:00:00Z"
}
```

### PATCH `/api/preferences`

Partially updates preferences. Only the fields present in the request body are changed.

**Authentication**

Required.

**Request fields**

| Field | Valid values |
|---|---|
| `currency` | `NGN`, `USD`, `EUR`, `GBP`, `CAD`, `AUD`, `ZAR`, `GHS`, `KES`, `INR`, `JPY`, `CNY`, `CHF`, `SEK`, `NOK`, `DKK`, `AED`, `SAR`, `EGP`, `XOF`, `XAF`, `BRL`, `MXN`, `SGD`, `HKD`, `NZD` (case-insensitive). |
| `language` | `en`, `fr`, `es`, `pt`, `sw`. |
| `notifications_enabled` | Boolean. |
| `document_notifications` | Boolean. |
| `proactive_suggestions` | Boolean. |
| `financial_experience` | `beginner`, `some_knowledge`, `moderate`, `advanced`, or `null` to clear. |
| `response_style` | `simple`, `balanced`, `detailed`, or `null` to clear. |
| `interests` | Array of `general_money_questions`, `understanding_documents`, `planning_life_decisions`, `financial_concepts`, `comparing_options`, `tax_questions`, `other`, or `null` to clear. |

Duplicate values sent in `interests` are dropped, keeping the first occurrence's position; any value outside the fixed set is rejected.

**Success**

`200` with the full, updated preferences object.

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | A field failed validation (structured error). |
| 500 | Unexpected server error. |

---

## Activity API

A read-only log of account events for the client to display, plus one endpoint that lets the client record events the backend has no other way to observe. There is no update or delete endpoint.

### GET `/api/activity`

Lists the caller's activity, newest first.

**Authentication**

Required.

**Query parameters**

`page` (default 1), `per_page` (default 20, capped at 100).

**Success**

`200`:

```json
{
  "items": [
    {
      "id": 1,
      "type": "document_uploaded",
      "title": "Uploaded statement.pdf",
      "description": null,
      "metadata": { "file_id": 34, "document_type": "bank_statement" },
      "created_at": "2026-09-15T10:00:00Z",
      "read_at": null
    }
  ],
  "pagination": { "page": 1, "per_page": 20, "total": 1 }
}
```

### GET `/api/activity/<activity_id>`

Returns a single activity record.

**Authentication**

Required.

**Success**

`200` with the activity object.

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | Activity not found, or not owned by the caller. |

### POST `/api/activity`

Lets the client log an event the backend cannot otherwise observe, such as a calculator that runs entirely inside the app.

**Authentication**

Required.

**Request**

```json
{
  "type": "loan_calculation",
  "title": "Calculated loan payment",
  "description": "Optional",
  "metadata": { "amount": 1000 }
}
```

**Request fields**

| Field | Required | Description |
|---|---|---|
| `type` | Yes | Must be one of `currency_conversion`, `loan_calculation`, `savings_calculation`, `affordability_calculation`. Server-generated types such as `document_uploaded`, `document_deleted`, `profile_updated`, or `preferences_updated` cannot be submitted through this endpoint — those are only ever written by backend logic. |
| `title` | Yes | Non-empty string, max 120 characters. |
| `description` | No | Free text. |
| `metadata` | No | Arbitrary JSON, stored as-is. |

Note: the four client-loggable calculator types predate the [Tools API](#tools-api), from when those calculators ran entirely in the app. They still compute server-side now, so this endpoint is no longer their only record of use — it remains available and unchanged for the client to log its own local usage if it wants to, but is not required by the Tools flow.

**Success**

`201` with the created activity object.

**Possible errors**

| Status | Meaning |
|---|---|
| 400 | `type` is missing or not in the client-loggable set, or `title` is missing/empty/too long (structured error). |

---

## Tools API

Seven deterministic financial calculators. Every calculation happens in Flask, using `Decimal` arithmetic — the AI never performs or repeats these calculations itself; it only explains a result already computed here (see [AI and Document Flow](#ai-and-document-flow)).

All monetary and rate figures in requests and responses are decimal strings (for example `"91679.99"`), never JSON floats, so precision is never lost to a binary float round-trip. Every successful response shares one envelope:

```json
{
  "tool": "<tool_identifier>",
  "version": "1",
  "inputs": { "...": "the validated, normalized request" },
  "result": { "...": "the calculation output" },
  "metadata": { "calculated_at": "2026-09-18T12:00:00.000000Z", "...": "tool-specific notes" }
}
```

`version` lets old calculations stay interpretable if a formula changes later. This same envelope (with `type: "financial_tool_result"` added) is what the chat `tool_context` handoff sends to the AI — see below.

Validation errors always use the structured shape (`code: "VALIDATION_ERROR"`, with a tool-specific code such as `INVALID_AMOUNT`, `INVALID_CURRENCY`, `INVALID_INTEREST_RATE`, `INVALID_DURATION`, `INVALID_FREQUENCY`, or `INVALID_PAYMENT` inside `error.details.<field>`). Errors specific to one tool are listed under it below.

### GET `/api/tools/currency/currencies`

Returns the backend's supported currency list — the source of truth for currency metadata; Flutter should not maintain its own copy.

**Authentication:** Required.

**Success `200`**

```json
{ "currencies": [{ "code": "USD", "name": "United States Dollar" }, { "code": "NGN", "name": "Nigerian Naira" }] }
```

### POST `/api/tools/currency/convert`

**Request**

```json
{ "amount": "1000.00", "from_currency": "USD", "to_currency": "NGN" }
```

Currency codes are case-insensitive and normalized to uppercase. If `from_currency` equals `to_currency`, the rate is `1` and no external provider call is made.

**Success `200`**

```json
{
  "tool": "currency_converter",
  "version": "1",
  "inputs": { "amount": "1000.00", "from_currency": "USD", "to_currency": "NGN" },
  "result": { "rate": "1546.500000", "converted_amount": "1546500.00" },
  "metadata": { "calculated_at": "...", "rate_date": "2026-09-17", "source": "frankfurter" }
}
```

`source` is `"same_currency"` (and `rate_date` is `null`) when no conversion was needed.

**Possible errors**

| Status | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Invalid/missing `amount`, or `from_currency`/`to_currency` not a supported code. |
| 502 | `CURRENCY_PROVIDER_UNAVAILABLE` | The exchange rate provider timed out, was unreachable, or returned an invalid/malformed response. |

**Provider architecture:** conversions go through a `CurrencyRateProvider` interface (`services/tools/currency/providers/base.py`); the current implementation, `FrankfurterProvider` (`services/tools/currency/providers/frankfurter.py`), calls the free, keyless Frankfurter API (base URL configurable via `FRANKFURTER_BASE_URL`, defaults to `https://api.frankfurter.dev/v2`). `CurrencyService` and this endpoint depend only on the interface, so a future provider can replace Frankfurter without changing this contract.

### POST `/api/tools/loan/calculate`

Standard fixed-payment amortizing loan.

**Request**

```json
{
  "loan_amount": "1000000",
  "annual_interest_rate": "18",
  "duration": 12,
  "duration_unit": "months",
  "repayment_frequency": "monthly",
  "currency": "NGN"
}
```

`duration_unit`: `months` or `years`. `repayment_frequency`: `weekly`, `biweekly`, `monthly`, or `quarterly`. A `0` interest rate is valid (payments split the principal evenly).

**Success `200` — `result`**

```json
{ "periodic_payment": "91679.99", "total_repayment": "1100159.91", "total_interest": "100159.91", "number_of_payments": 12 }
```

`metadata.is_estimate` is always `true`; `metadata.assumptions` states this is not a lender quote.

### POST `/api/tools/savings/calculate`

Supply exactly one of `target_amount` or `monthly_contribution` (not both, not neither).

**Request**

```json
{ "target_amount": "500000", "duration_months": 12, "annual_return_rate": "5", "currency": "NGN" }
```

`annual_return_rate` is optional; if omitted, no growth is assumed (`0`).

**Success `200` — `result`**

```json
{
  "required_monthly_contribution": "40720.41",
  "projected_amount": "500000.00",
  "total_contributions": "488644.89",
  "estimated_growth": "11355.11"
}
```

`metadata.mode` is `"target_based"` or `"contribution_based"` depending on which input was supplied.

### POST `/api/tools/affordability/calculate`

**Request**

```json
{
  "monthly_income": "500000",
  "existing_commitments": "150000",
  "purchase_price": "2000000",
  "payment_method": "installment",
  "duration_months": 12,
  "currency": "NGN"
}
```

`payment_method`: `cash` (no recurring payment; `duration_months` not required) or `installment` (price split evenly across `duration_months`, no interest modeled; `duration_months` required).

**Success `200` — `result`**

```json
{
  "estimated_monthly_payment": "166666.67",
  "total_monthly_commitments": "316666.67",
  "commitment_ratio": "0.6333",
  "remaining_income": "183333.33"
}
```

`commitment_ratio` is a fraction of monthly income (not a percentage). `metadata.within_threshold` compares it against `metadata.commitment_ratio_threshold` (currently `0.40`) — a configurable guideline surfaced for context, not an absolute affordability verdict.

### POST `/api/tools/debt-payoff/calculate`

**Request**

```json
{
  "current_debt": "1500000",
  "annual_interest_rate": "20",
  "minimum_monthly_payment": "50000",
  "extra_monthly_payment": "50000",
  "currency": "NGN"
}
```

`extra_monthly_payment` is optional, defaults to `0`.

**Success `200` — `result`**

```json
{
  "months_to_payoff": 18,
  "total_interest": "240636.07",
  "total_repayment": "1740636.07",
  "minimum_only": { "payable": true, "months_to_payoff": 42, "total_interest": "596747.73", "total_repayment": "..." },
  "interest_saved": "356111.66",
  "months_saved": 24
}
```

`minimum_only` simulates paying only `minimum_monthly_payment` (ignoring the extra amount) for comparison. If that alone wouldn't cover the monthly interest, `minimum_only.payable` is `false`, its other fields are `null`, and so are `interest_saved`/`months_saved`.

**Possible errors**

| Status | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` (`details.minimum_monthly_payment: "DEBT_PAYMENT_TOO_LOW"`) | `minimum_monthly_payment + extra_monthly_payment` does not exceed the first month's interest, so the debt could never be paid off. |

### POST `/api/tools/investment/calculate`

**Request**

```json
{
  "initial_amount": "500000",
  "monthly_contribution": "100000",
  "expected_annual_return": "12",
  "duration_years": 10,
  "compounding_frequency": "monthly",
  "currency": "NGN"
}
```

`monthly_contribution` is optional, defaults to `0`. `compounding_frequency`: `monthly`, `quarterly`, or `annually`.

**Success `200` — `result`**

```json
{
  "future_value": "24654062.39",
  "total_contributions": "12500000.00",
  "estimated_growth": "12154062.39",
  "initial_amount": "500000.00",
  "contribution_amount": "100000.00"
}
```

`metadata.assumptions` states returns are not guaranteed and this is not investment advice.

### POST `/api/tools/subscription-cost/calculate`

Computes totals from the caller's own tracked subscriptions (`Subscription` rows created via the [Subscriptions](#endpoint-summary) endpoints) — it never accepts a client-supplied amount for an existing subscription.

**Request**

```json
{ "subscription_ids": [1, 2, 3] }
```

`subscription_ids` is optional. If omitted, all of the caller's `active` subscriptions are used. If supplied, every id must belong to the caller (see errors below); paused/cancelled subscriptions among the supplied ids are excluded from totals and listed in `result.excluded_subscriptions`.

**Success `200` — `result`**

```json
{
  "currency": "NGN",
  "total_monthly_cost": "41333.33",
  "total_yearly_cost": "496000.00",
  "subscription_count": 4,
  "subscriptions": [
    { "id": 1, "name": "Netflix", "amount": "7000.00", "currency": "NGN", "frequency": "monthly", "monthly_cost": "7000.00", "yearly_cost": "84000.00" }
  ],
  "totals_by_currency": [{ "currency": "NGN", "total_monthly_cost": "41333.33", "total_yearly_cost": "496000.00" }],
  "excluded_subscriptions": []
}
```

Billing frequencies (`weekly`, `monthly`, `quarterly`, `semiannual`, `yearly`) are normalized to monthly/yearly equivalents (weekly ×52/12, quarterly ÷3, semiannual ÷6, yearly ÷12). If the included subscriptions span more than one currency, `currency`/`total_monthly_cost`/`total_yearly_cost` are `null` and `totals_by_currency` holds the per-currency breakdown instead — amounts in different currencies are never added together.

**Possible errors**

| Status | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` (`details.subscription_ids: "INVALID_SUBSCRIPTION_ID"`) | `subscription_ids` is not a non-empty array of positive integers. |
| 404 | `SUBSCRIPTION_NOT_FOUND` (`details.subscription_ids`: the missing ids) | One or more requested ids don't exist, or belong to a different user — both cases return the same response, consistent with the rest of the API never confirming another user's resource exists. |

### Chat tool_context handoff

`POST /api/chat` accepts an optional `tool_context` field alongside `message`/`conversation_id`/`file_id`: the exact envelope one of the endpoints above returned, with `"type": "financial_tool_result"` added. The user can send it with a typed question, or with an empty `message` — the app never sends a synthetic message on the user's behalf.

```json
{
  "message": "Is this affordable for me?",
  "conversation_id": 12,
  "tool_context": {
    "type": "financial_tool_result",
    "tool": "affordability_calculator",
    "version": "1",
    "inputs": { "...": "..." },
    "result": { "...": "..." },
    "metadata": { "...": "..." }
  }
}
```

The AI treats `tool_context.result` as authoritative and does not recalculate it (see [AI and Document Flow](#ai-and-document-flow) and `SYSTEM.MD`'s "TOOL RESULTS" section). Like a file attachment, the full `tool_context` is only sent to the model on the turn it's attached; later turns see a short placeholder instead of the raw JSON. A malformed `tool_context` (missing `type`/`tool`/`version`/`inputs`/`result`, wrong `type`, or over 20 KB) returns `400 {"error": "..."}`, matching the rest of the Chat API's error shape.

## Notifications API

The backend currently has no active trigger that automatically creates a notification from an application event — the write path for that exists in `services/notification_service.py` but nothing in the current codebase calls it. These endpoints only list and mark existing rows; any rows visible today were inserted directly (e.g. in tests or ad-hoc data), not by live product logic.

### GET `/api/notifications`

Lists the caller's notifications, newest first.

**Authentication**

Required.

**Query parameters**

`page` (default 1), `per_page` (default 20, capped at 100).

**Success**

`200`:

```json
{
  "items": [
    {
      "id": 1,
      "type": "document_uploaded",
      "title": "Statement ready",
      "body": "Your statement has finished processing.",
      "read": false,
      "metadata": null,
      "created_at": "2026-09-15T10:00:00Z"
    }
  ],
  "pagination": { "page": 1, "per_page": 20, "total": 1 }
}
```

### PATCH `/api/notifications/<notification_id>`

Marks a single notification as read.

**Authentication**

Required.

**Success**

`200` with the updated notification object.

**Possible errors**

| Status | Meaning |
|---|---|
| 404 | Notification not found, or not owned by the caller. |

### PATCH `/api/notifications/read-all`

Marks all of the caller's unread notifications as read.

**Authentication**

Required.

**Success**

`200`:

```json
{
  "message": "All notifications marked as read"
}
```

---

## Data Ownership and Security

Every user-owned resource — conversations, messages, financial documents, profile, preferences, activities, and notifications — is scoped to the authenticated user on every read and write. Queries filter on the JWT identity's user ID, not just the resource ID.

Where a resource exists but belongs to a different user, the API returns `404 Not Found`, not `403 Forbidden`. This is deliberate: it avoids confirming to a caller that a given ID exists at all for another account.

Financial documents and profile pictures are stored as private objects in a single Cloudflare R2 bucket, with public `r2.dev` access disabled. No endpoint ever returns an R2 object key or a permanent URL to the client. Reading either type of file goes through a signed URL generated fresh on each request (300 seconds for financial documents and profile pictures alike); these URLs are never stored in the database or reused across requests.

## AI and Document Flow

Chat runs on the OpenAI Responses API using the model `gpt-5.6-luna`. Each `POST /api/chat` call sends the system prompt from `SYSTEM.MD`, the most recent 20 messages of the conversation, and the current turn's message.

A financial document is only ever sent to the model in the turn where it is actually attached. Once that turn scrolls out of the live conversation or a later turn is processed, the document is not resent — its place in the historical context is a short placeholder noting a document was attached there, not the document itself. This bounds both the number of documents reprocessed per request and the token cost of long conversations. A `tool_context` (see [Tools API](#tools-api)) follows the same rule: sent in full only on the turn it's attached, replaced by a short placeholder afterward.

Tool results are never computed by the model. The seven Tools endpoints perform their calculations deterministically in Flask before the user ever reaches chat; if the user taps "Ask FinAssist" on a result, that structured result — not a recalculation — is what the model reasons about. `SYSTEM.MD`'s "TOOL RESULTS" section instructs the model accordingly.

There is no web search, autonomous task execution, or persistent memory across conversations beyond the `tool_context` handoff described above. The Tools endpoints are conventional, directly-called Flask routes, not AI function/tool calling — the assistant does not invoke them itself. The assistant's knowledge of a conversation is limited to what is in that conversation's recent message window.

## Current Product Scope

FinAssist's current product surface is chat-first: Chat, Quick (activity/preferences-driven shortcuts), Tools (seven deterministic calculators computed server-side — see [Tools API](#tools-api) — with results optionally handed to chat via `tool_context`), Subscriptions, and Profile. It is not a transaction-tracking or dashboard-style finance app.

Manual financial-goal tracking and transaction-ledger tracking existed earlier in this backend's history but have been removed. Migration `d1adc99c11a8_remove_legacy_goal_transaction_tracking.py` dropped the `financial_goal` and `transaction` tables and their related `user_preference` columns. There are no `/api/goals`, `/api/transactions`, or `/api/dashboard` endpoints in the current backend, and none of the active route files reference them. Any historical mentions of these features found elsewhere in the repository describe removed functionality, not current behavior.

---

## Endpoint Summary

| Method | Endpoint | Authentication | Purpose |
|---|---|---|---|
| POST | `/api/register` | None | Create a user account |
| POST | `/api/login` | None | Authenticate and issue tokens |
| POST | `/api/refresh` | Refresh token | Issue a new access token |
| GET | `/api/me` | Required | Get the authenticated user's basic info |
| POST | `/api/chat` | Required | Send a message to the AI assistant |
| GET | `/api/conversations` | Required | List the caller's conversations |
| POST | `/api/conversations` | Required | Create a conversation |
| GET | `/api/conversations/<conversation_id>` | Required | Get a conversation and its messages |
| DELETE | `/api/conversations/<conversation_id>` | Required | Delete a conversation |
| POST | `/api/files/upload` | Required | Upload a financial document |
| GET | `/api/files` | Required | List the caller's financial documents |
| GET | `/api/files/<file_id>` | Required | Get one file's metadata |
| GET | `/api/files/<file_id>/view` | Required | Get a temporary signed URL for a file |
| DELETE | `/api/files/<file_id>` | Required | Delete one financial document |
| GET | `/api/profile` | Required | Get the caller's profile |
| PATCH | `/api/profile` | Required | Update the caller's profile |
| POST | `/api/profile/picture` | Required | Upload a profile picture |
| GET | `/api/preferences` | Required | Get the caller's preferences |
| PATCH | `/api/preferences` | Required | Update the caller's preferences |
| GET | `/api/activity` | Required | List the caller's activity |
| GET | `/api/activity/<activity_id>` | Required | Get one activity record |
| POST | `/api/activity` | Required | Log a client-side activity event |
| GET | `/api/notifications` | Required | List the caller's notifications |
| PATCH | `/api/notifications/<notification_id>` | Required | Mark one notification as read |
| PATCH | `/api/notifications/read-all` | Required | Mark all notifications as read |
| GET | `/api/subscriptions` | Required | List the caller's tracked subscriptions |
| POST | `/api/subscriptions` | Required | Create a tracked subscription |
| GET | `/api/subscriptions/<subscription_id>` | Required | Get one subscription |
| PATCH | `/api/subscriptions/<subscription_id>` | Required | Update one subscription |
| DELETE | `/api/subscriptions/<subscription_id>` | Required | Delete one subscription |
| GET | `/api/tools/currency/currencies` | Required | List supported currencies |
| POST | `/api/tools/currency/convert` | Required | Convert an amount between two currencies |
| POST | `/api/tools/loan/calculate` | Required | Calculate an amortizing loan |
| POST | `/api/tools/savings/calculate` | Required | Calculate a savings plan |
| POST | `/api/tools/affordability/calculate` | Required | Calculate purchase affordability |
| POST | `/api/tools/debt-payoff/calculate` | Required | Calculate a debt payoff plan |
| POST | `/api/tools/investment/calculate` | Required | Calculate investment growth |
| POST | `/api/tools/subscription-cost/calculate` | Required | Total the caller's tracked subscription costs |

38 active endpoints across 10 blueprints (`auth`, `chat`, `conversations`, `files`, `profile`, `preferences`, `activity`, `notifications`, `subscriptions`, `tools`).

## Development Status

The backend runs against a local SQLite database (`instance/mydatabase.db`) in every environment — there is no separate staging or production database configured. Database schema changes are managed with Flask-Migrate/Alembic in `migrations/`. There is no CI configuration, deployment script, or WSGI production entry point in the repository; `app.py` starts the Flask development server directly.
