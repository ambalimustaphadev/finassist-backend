import os
import boto3
from config import Config





def get_spaces_client():
    return boto3.client(
        "s3",
        region_name="auto",
        endpoint_url=(f"https://{Config.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"),
        aws_access_key_id=Config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,

        
    )

def public_url(key: str) -> str:
    base = Config.DEVELOPMENT_URL.rstrip("/")
    return f"{base}/{key}"


def delete_object(key: str) -> None:
    """Delete a single object from R2, Silently ignores NoSuchKey"""
    client = get_spaces_client()
    try:
        client.delete_object(Bucket=Config.CLOUDFLARE_ACCOUNT_ID, key=key)
    except Exception:
        pass
