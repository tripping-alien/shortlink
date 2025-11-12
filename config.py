# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================
import os


class Config:
    """Centralized configuration with validation"""
    BASE_URL: str = os.getenv("BASE_URL", "https://shortlinks.art")
    SHORT_CODE_LENGTH: int = 6
    MAX_ID_RETRIES: int = 10
    
    # Security
    MAX_URL_LENGTH: int = 2048
    ALLOWED_SCHEMES: tuple = ("http", "https")
    BLOCKED_DOMAINS: set = {"localhost", "127.0.0.1", "0.0.0.0"}
    
    # Rate limiting
    RATE_LIMIT_CREATE: str = "10/minute"
    RATE_LIMIT_STATS: str = "30/minute"
    
    # Database
    CLEANUP_INTERVAL_SECONDS: int = 1800  # 30 minutes
    CLEANUP_BATCH_SIZE: int = 100
    
    # External APIs
    HUGGINGFACE_API_KEY: Optional[str] = os.getenv("HUGGINGFACE_API_KEY")
    SUMMARIZATION_MODEL: str = "facebook/bart-large-cnn"
    SUMMARY_MAX_LENGTH: int = 2000
    
    # Timeouts
    HTTP_TIMEOUT: float = 10.0
    METADATA_FETCH_TIMEOUT: float = 5.0
    SUMMARY_TIMEOUT: float = 15.0
    
    # Localization
    SUPPORTED_LOCALES: List[str] = ["en", "es", "zh", "hi", "pt", "fr", "de", "ar", "ru", "he"]
    DEFAULT_LOCALE: str = "en"
    RTL_LOCALES: List[str] = ["ar", "he"]
    
    # Google AdSense
    ADSENSE_CLIENT_ID: str = "pub-6170587092427912"
    
    @classmethod
    def validate(cls):
        """Validate configuration on startup"""
        if not cls.BASE_URL:
            raise ValueError("BASE_URL must be set")
        if not cls.BASE_URL.startswith(("http://", "https://")):
            raise ValueError("BASE_URL must include http:// or https://")
        if cls.SHORT_CODE_LENGTH < 4 or cls.SHORT_CODE_LENGTH > 20:
            raise ValueError("SHORT_CODE_LENGTH must be between 4 and 20")

config = Config()

# Derived Constants (used immediately by the application setup)

# Time-To-Live Mapping
TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

# AdSense Script (uses the client ID from Config)
ADSENSE_SCRIPT = f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={config.ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>'

# Flag Code Mapping (Used for display in templates)
LOCALE_TO_FLAG_CODE = {
    "en": "gb", "es": "es", "zh": "cn", "hi": "in", "pt": "br",
    "fr": "fr", "de": "de", "ar": "sa", "ru": "ru", "he": "il",
}
