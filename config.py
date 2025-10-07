from pydantic_settings import BaseSettings
import database


class Settings(BaseSettings):
    """Manages application configuration using environment variables."""
    # Use Render's persistent disk path. Default to local file for development.
    db_file: str = database.DB_FILE
    # In production, set this to your frontend's domain: "https://your-frontend.com"
    # The default ["*"] is insecure and for development only.
    cors_origins: list[str] = ["*"]
    cleanup_interval_seconds: int = 3600  # Run cleanup task every hour


settings = Settings()

# --- Shared Application State ---

TRANSLATIONS = {}
DEFAULT_LANGUAGE = "en"