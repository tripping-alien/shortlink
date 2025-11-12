# config.py

# Base Configuration
MAX_URL_LENGTH = 2048
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 50
BASE_URL = "http://shortlinks.art"
ALLOWED_SCHEMES = ["http", "https"]
BLOCKED_DOMAINS = ["127.0.0.1", "localhost", "0.0.0.0"] # Add more as needed
HTTP_TIMEOUT = 10.0
METADATA_FETCH_TIMEOUT = 5.0

# Rate Limiting
RATE_LIMIT_CREATE = "5/minute"
RATE_LIMIT_STATS = "10/minute"

# Cleaning Worker
CLEANUP_INTERVAL_SECONDS = 3600 # 1 hour
CLEANUP_BATCH_SIZE = 50

# AI Configuration (For summarization, if enabled)
HUGGINGFACE_API_KEY = "hf_..." # Replace with your actual key or leave blank to disable
SUMMARIZATION_MODEL = "facebook/bart-large-cnn"
SUMMARY_TIMEOUT = 30.0
SUMMARY_MAX_LENGTH = 10000

# Adsense (Replace with your script)
ADSENSE_SCRIPT = """
    """

# Language/Localization Configuration (10 Languages)
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "es", "fr", "de", "it", "pt", "ja", "zh", "ar", "ru"]
RTL_LOCALES = ["ar"] # Right-to-Left languages

LOCALE_TO_FLAG_CODE = {
    "en": "US", # English
    "es": "ES", # Spanish
    "fr": "FR", # French
    "de": "DE", # German
    "it": "IT", # Italian
    "pt": "PT", # Portuguese
    "ja": "JP", # Japanese
    "zh": "CN", # Chinese
    "ar": "SA", # Arabic
    "ru": "RU", # Russian
}

# Time To Live (TTL) Configuration (in seconds or a logical value)
TTL_MAP = {
    "1h": 3600,
    "24h": 86400,
    "1w": 604800,
    "never": None,
}

def validate():
    """Simple configuration validation"""
    if len(SUPPORTED_LOCALES) != 10:
        raise ValueError("SUPPORTED_LOCALES must contain exactly 10 language codes.")

