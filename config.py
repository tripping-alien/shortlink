import os
from datetime import timedelta 

# ============================================================================
# CONFIGURATION CLASS
# ============================================================================

class Config:
    """Centralized configuration with validation"""
    BASE_URL: str = os.getenv("BASE_URL", "https://shortlinks.art")
    
    # Core Constants
    SHORT_CODE_LENGTH: int = 6
    MAX_ID_RETRIES: int = 10
    
    # Security
    MAX_URL_LENGTH: int = 2048 
    ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")
    BLOCKED_DOMAINS: set[str] = {"localhost", "127.0.0.1", "0.0.0.0"}
    
    # Rate limiting
    RATE_LIMIT_CREATE: str = os.getenv("RATE_LIMIT_CREATE", "10/minute")
    RATE_LIMIT_STATS: str = os.getenv("RATE_LIMIT_STATS", "30/minute")
    
    # Database/Cleanup
    CLEANUP_INTERVAL_SECONDS: int = 1800  # 30 minutes
    CLEANUP_BATCH_SIZE: int = 100
    
    # External APIs
    HUGGINGFACE_API_KEY: str | None = os.getenv("HUGGINGFACE_API_KEY")
    SUMMARIZATION_MODEL: str = "facebook/bart-large-cnn"
    SUMMARY_MAX_LENGTH: int = 2000
    
    # Timeouts
    HTTP_TIMEOUT: float = 10.0
    METADATA_FETCH_TIMEOUT: float = 5.0
    SUMMARY_TIMEOUT: float = 15.0
    
    # Localization
    SUPPORTED_LOCALES: list[str] = ["en", "es", "zh", "hi", "pt", "fr", "de", "ar", "ru", "he", "ja", "it", "arr"]
    DEFAULT_LOCALE: str = "en"
    RTL_LOCALES: list[str] = ["ar", "he"]
    
    @classmethod
    def validate(cls):
        """Validate configuration on startup"""
        if not cls.BASE_URL:
            raise ValueError("BASE_URL must be set")
        if not cls.BASE_URL.startswith(("http://", "https://")):
            raise ValueError("BASE_URL must include http:// or https://")
        if cls.SHORT_CODE_LENGTH < 4 or cls.SHORT_CODE_LENGTH > 20:
            raise ValueError("SHORT_CODE_LENGTH must be between 4 and 20")

# ============================================================================
# SINGLETON INSTANCE & DERIVED CONSTANTS
# ============================================================================

config = Config()

# --- Expose class attributes as module constants for convenience ---
for attr in [a for a in dir(config) if not a.startswith('__') and not callable(getattr(config, a))]:
    globals()[attr] = getattr(config, attr)

# Time-To-Live Mapping (timedelta objects)
TTL_MAP: dict[str, timedelta | None] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

# ============================================================================
# LOCALIZATION CONSTANTS
# ============================================================================

# Maps locale code (en) to two-letter country code (gb)
LOCALE_TO_FLAG_CODE: dict[str, str] = {
    "en": "gb", "es": "es", "zh": "cn", 
    "hi": "in", "pt": "br", "fr": "fr", "de": "de", "ar": "sa", "ru": "ru", 
    "he": "il", 
    "ja": "jp", "it": "it",
    "arr": "pirate"
}

# Mapping of country codes to actual Unicode flag emojis
FLAG_CODE_TO_EMOJI: dict[str, str] = {
    "gb": "🇬🇧", "es": "🇪🇸", "cn": "🇨🇳",
    "in": "🇮🇳", "br": "🇧🇷", "fr": "🇫🇷", "de": "🇩🇪", "sa": "🇸🇦", "ru": "🇷🇺",
    "il": "🇮🇱", "jp": "🇯🇵", "it": "🇮🇹",
    "pirate": "🏴‍☠️",    # Pirate flag
    "default": "❓"       # Unknown
}

# Native language names for clarity in the dropdown
NATIVE_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Español",
    "zh": "中文",
    "hi": "हिन्दी",
    "pt": "Português",
    "fr": "Français",
    "de": "Deutsch",
    "ar": "العربية",
    "ru": "Русский",
    "he": "עברית",
    "ja": "日本語",
    "it": "Italiano",
    "arr": "Pirate Speak"
}


# Final, ready-to-use map: Locale Code -> Flag Emoji
LOCALE_TO_EMOJI: dict[str, str] = {
    locale: FLAG_CODE_TO_EMOJI.get(code, FLAG_CODE_TO_EMOJI["default"])
    for locale, code in LOCALE_TO_FLAG_CODE.items()
}

# Attach derived constants to the config object for unified access
config.TTL_MAP = TTL_MAP
config.LOCALE_TO_FLAG_CODE = LOCALE_TO_FLAG_CODE
config.NATIVE_LANGUAGE_NAMES = NATIVE_LANGUAGE_NAMES
config.FLAG_CODE_TO_EMOJI = FLAG_CODE_TO_EMOJI
config.LOCALE_TO_EMOJI = LOCALE_TO_EMOJI # FIX: Ensure this is attached correctly
