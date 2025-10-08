import os
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """
    Application configuration settings.
    It's best practice to load sensitive values like salts from environment variables.
    """
    # A long, random, and secret string. Changing this will change all generated links.
    # For production, this should be set as an environment variable.
    HASHIDS_SALT: str = os.environ.get("HASHIDS_SALT", "a-long-and-secret-salt-for-your-shortener")
    HASHIDS_MIN_LENGTH: int = 5  # Ensures all generated IDs have at least this length.
    HASHIDS_ALPHABET: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"


settings = AppConfig()