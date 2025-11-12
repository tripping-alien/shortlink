import os

# --- Configuration Constants ---

# Locales
SUPPORTED_LOCALES = ["en", "es", "fr", "de"]
DEFAULT_LOCALE = "en"
RTL_LOCALES = [] # Add locales like "ar", "he" if needed

# Flags: Mapped locale code to the ISO 3166-1 alpha-2 code for the flag emoji
# 'en' is mapped to 'US' as requested.
LOCALE_TO_FLAG_CODE = {
    "en": "US",  # United States Flag
    "es": "ES",  # Spain Flag
    "fr": "FR",  # France Flag
    "de": "DE",  # Germany Flag
}

# Application
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
MAX_URL_LENGTH = 2048
SHORT_CODE_LENGTH = 8
MAX_ID_RETRIES = 5

# Rate Limits
RATE_LIMIT_CREATE = "5/minute"
RATE_LIMIT_STATS = "30/minute"

# Time-To-Live (TTL)
TTL_MAP = {
    "1h": 1,
    "24h": 24,
    "1w": 168,
    "never": None,
}

# Cleanup
CLEANUP_INTERVAL_SECONDS = 3600
CLEANUP_BATCH_SIZE = 500

# Security
ALLOWED_SCHEMES = ["http", "https"]
BLOCKED_DOMAINS = ["127.0.0.1", "localhost"]

# Metadata and AI
METADATA_FETCH_TIMEOUT = 5.0
HTTP_TIMEOUT = 10.0
HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY")
SUMMARIZATION_MODEL = "facebook/bart-large-cnn"
SUMMARY_TIMEOUT = 30.0
SUMMARY_MAX_LENGTH = 1024 * 5 # 5KB of text for summarization

# Frontend (AdSense Script)
ADSENSE_SCRIPT = "" # Placeholder for actual AdSense script

# --- Validation ---
def validate():
    """Basic configuration validation"""
    if not BASE_URL.startswith("http"):
        raise ValueError("BASE_URL must start with http or https")
    
    # Check if all SUPPORTED_LOCALES have a flag code
    for locale in SUPPORTED_LOCALES:
        if locale not in LOCALE_TO_FLAG_CODE:
            raise ValueError(f"Missing flag code for locale: {locale}")
