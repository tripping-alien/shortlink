"""
Configuration and constants.
"""
import os
from enum import Enum
from functools import lru_cache
from datetime import timedelta
import secrets
from pydantic_settings import BaseSettings

# --- Enums and Mappings ---

class TTL(str, Enum):
    """Time-to-live options for short links."""
    ONE_SECOND = "1s"  # Added for testing purposes
    ONE_HOUR = "1h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    NEVER = "never"

TTL_MAP = {
    TTL.ONE_HOUR: timedelta(hours=1),
    TTL.ONE_SECOND: timedelta(seconds=1),
    TTL.ONE_DAY: timedelta(days=1),
    TTL.ONE_WEEK: timedelta(weeks=1),
}

# --- Pydantic Settings Management ---

class Settings(BaseSettings):
    """
    Manages application configuration using environment variables.
    Pydantic-settings automatically reads from environment variables.
    """
    # In production, set this to your frontend's domain: "https://your-frontend.com"
    cors_origins: list[str] = ["*"]
    cleanup_interval_seconds: int = 3600  # Run cleanup task every hour

    # A long, random, and secret string. Changing this will change all generated links.
    # For production, this should be set as an environment variable for security.
    hashids_salt: str = os.environ.get("HASHIDS_SALT", secrets.token_hex(32))
    hashids_min_length: int = 5  # Ensures all generated IDs have at least this length.
    hashids_alphabet: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings class.
    Using lru_cache ensures the Settings are created only once, preventing
    the salt from being regenerated on every import or reload.
    """
    return Settings()