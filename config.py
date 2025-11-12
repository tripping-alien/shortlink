import os
from datetime import timedelta 
from typing import Optional, List, Dict, Tuple
from functools import lru_cache

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
    ALLOWED_SCHEMES: Tuple[str, ...] = ("http", "https")
    BLOCKED_DOMAINS: set = {"localhost", "127.0.0.1", "0.0.0.0"}
    
    # Rate limiting
    RATE_LIMIT_CREATE: str = os.getenv("RATE_LIMIT_CREATE", "10/minute")
    RATE_LIMIT_STATS: str = os.getenv("RATE_LIMIT_STATS", "30/minute")
    
    # Database/Cleanup
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
    SUPPORTED_LOCALES: List[str] = ["en", "es", "zh", "hi", "pt", "fr", "de", "ar", "ru", "he", "arr"]
    DEFAULT_LOCALE: str = "en"
    RTL_LOCALES: List[str] = ["ar", "he"]
    
    # Google AdSense
    ADSENSE_CLIENT_ID: str = os.getenv("ADSENSE_CLIENT_ID", "pub-6170587092427912")
    
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
# MODULE LEVEL CONSTANTS (Exported for imports)
# ============================================================================

# Initialize the config instance
config = Config()

# --- CRITICAL FIX: Expose class attributes as module constants ---
SHORT_CODE_LENGTH = config.SHORT_CODE_LENGTH
MAX_ID_RETRIES = config.MAX_ID_RETRIES 
MAX_URL_LENGTH = config.MAX_URL_LENGTH 

# Time-To-Live Mapping (timedelta objects)
TTL_MAP: Dict[str, Optional[timedelta]] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

# AdSense Script (uses the client ID from Config)
ADSENSE_SCRIPT: str = f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={config.ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>'


# ============================================================================
# LOCALIZATION CONSTANTS
# ============================================================================

# Maps locale code (en) to two-letter country code (gb)
LOCALE_TO_FLAG_CODE: Dict[str, str] = {
    "en": "gb", "es": "es", "zh": "cn", 
    "hi": "in", "pt": "br", "fr": "fr", "de": "de", "ar": "sa", "ru": "ru", 
    "he": "il", 
    "arr": "pirate" 
}

# Mapping of country codes to actual Unicode flag emojis
FLAG_CODE_TO_EMOJI: Dict[str, str] = {
    "gb": "🇬🇧", "es": "🇪🇸", "cn": "🇨🇳", 
    "in": "🇮🇳", "br": "🇧🇷", "fr": "🇫🇷", "de": "🇩🇪", "sa": "🇸🇦", "ru": "🇷🇺", 
    "il": "🇮🇱",  
    "pirate": "🏴‍☠️", 
    "default": "❓" 
}

# Final, ready-to-use map: Locale Code -> Flag Emoji
LOCALE_TO_EMOJI: Dict[str, str] = {
    locale: FLAG_CODE_TO_EMOJI.get(code, FLAG_CODE_TO_EMOJI["default"])
    for locale, code in LOCALE_TO_FLAG_CODE.items()
}
