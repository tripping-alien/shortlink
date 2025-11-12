# config.py

import os

# Base Configuration
MAX_URL_LENGTH = 2048
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 50
BASE_URL = os.environ.get("BASE_URL", "http://shortlinks.art")
ALLOWED_SCHEMES = ["http", "https"]
BLOCKED_DOMAINS = ["127.0.0.1", "localhost", "0.0.0.0"] 
HTTP_TIMEOUT = 10.0
METADATA_FETCH_TIMEOUT = 5.0

# Rate Limiting
RATE_LIMIT_CREATE = "5/minute"
RATE_LIMIT_STATS = "10/minute"

# Cleaning Worker
CLEANUP_INTERVAL_SECONDS = 3600 # 1 hour
CLEANUP_BATCH_SIZE = 50

# AI Configuration
HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY") 
SUMMARIZATION_MODEL = "facebook/bart-large-cnn"
SUMMARY_TIMEOUT = 30.0
SUMMARY_MAX_LENGTH = 10000

# Adsense (Replace with your script)
ADSENSE_SCRIPT = "" 

# Language/Localization Configuration (11 Languages)
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "es", "fr", "de", "it", "pt", "ja", "zh", "ar", "ru", "arr"]
RTL_LOCALES = ["ar"] 

LOCALE_TO_FLAG_CODE = {
    "en": "US", 
    "es": "ES", 
    "fr": "FR", 
    "de": "DE", 
    "it": "IT", 
    "pt": "PT", 
    "ja": "JP", 
    "zh": "CN", 
    "ar": "SA", 
    "ru": "RU", 
    "arr": "JM", # Pirate (Jamaica Flag)
}

# Time To Live (TTL) Configuration
TTL_MAP = {
    "1h": 3600,
    "24h": 86400,
    "1w": 604800,
    "never": None,
}

def validate():
    """Simple configuration validation"""
    if len(SUPPORTED_LOCALES) != 11:
        raise ValueError("SUPPORTED_LOCALES must contain exactly 11 language codes.")

