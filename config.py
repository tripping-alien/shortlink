"""
Configuration and constants.
"""
import os
from enum import Enum
from functools import lru_cache
from datetime import timedelta
from pathlib import Path
import secrets
from pydantic import HttpUrl
from pydantic_settings import BaseSettings

# --- Enums and Mappings ---
# These are used in database.py for direct short code generation.
SHORT_CODE_LENGTH = 6
MAX_ID_GENERATION_RETRIES = 10 # Max attempts to find a unique ID

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
    hashids_salt: str
    hashids_min_length: int = 5  # Ensures all generated IDs have at least this length.
    hashids_alphabet: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"

    # The public-facing base URL of the application.
    # Used for generating canonical URLs in API responses and sitemaps.
    # For local development, it defaults to localhost. For production, set this env var.
    base_url: HttpUrl = "https://shortlinks.art"
    BASE_URL = "https://shortlinks.art"

@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings class.
    Using lru_cache ensures the Settings are created only once, preventing
    the settings from being reloaded on every import. Pydantic-settings
    will automatically load variables from a .env file.
    """
    # Use an absolute path relative to this config file to ensure stability
    # across different execution environments (pytest vs. uvicorn).
    base_dir = Path(__file__).resolve().parent
    salt_file = base_dir / ".salt"

    # Check for environment variable first (for production)
    salt = os.environ.get("HASHIDS_SALT")

    if not salt:
        # If no env var, check for the .salt file (for stable development)
        if os.path.exists(salt_file):
            with open(salt_file, "r") as f:
                salt = f.read().strip()
        else:
            # If no file, generate a new salt and save it
            salt = secrets.token_hex(32)
            with open(salt_file, "w") as f:
                f.write(salt)

    return Settings(hashids_salt=salt)
