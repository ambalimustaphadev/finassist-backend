from datetime import timedelta
import os


class Config(object):
    # Database
    SQLALCHEMY_DATABASE_URI = 'sqlite:///mydatabase.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

# JWT
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)



# cloudflare R2
    CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    R2_ACCESS_KEY_ID = os.environ.get("CLOUDFLARE_ACCESS_KEY")
    R2_SECRET_ACCESS_KEY = os.environ.get("CLOUDFLARE_SECRET_ACCESS_KEY")
    R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")   

# open ai ai key

    OPEN_AI_KEY = os.environ.get("OPEN_AI_KEY")


# cloudflare url
DEVELOPMENT_URL = "https://pub-a01ec6ddbcee4e00818c122528614dbd.r2.dev"
