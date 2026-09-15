from datetime import timedelta
import os

from dotenv import load_dotenv

load_dotenv()


class Config(object):
    # Database
    SQLALCHEMY_DATABASE_URI = 'sqlite:///mydatabase.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

# JWT
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)



# cloudflare R2
    # The bucket is private. Public r2.dev access is disabled; all
    # client-facing access to objects in it goes through short-lived
    # presigned URLs (see spaces.generate_signed_url), never a public URL.
    CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    R2_ACCESS_KEY_ID = os.environ.get("CLOUDFLARE_ACCESS_KEY")
    R2_SECRET_ACCESS_KEY = os.environ.get("CLOUDFLARE_SECRET_ACCESS_KEY")
    R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

# open ai ai key

    OPEN_AI_KEY = os.environ.get("OPEN_AI_KEY")
