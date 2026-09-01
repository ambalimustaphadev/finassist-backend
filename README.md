# FinAssist Backend

Backend API for FinAssist, a personal financial assistant.

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

- User authentication
- JWT access and refresh tokens
- Conversations
- AI chat
- Financial document uploads
- Cloudflare R2 file storage
- Financial statement storage

## Project Structure

```text
authroute/       Authentication routes
migrations/      Database migrations
server/          Flask application factory
chat_routes.py   AI chat routes
conversation_routes.py
file_routes.py   File upload routes
models.py        Database models
spaces.py        Cloudflare R2 client
config.py        Application configuration