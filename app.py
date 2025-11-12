You got it. Ensuring the server-side logic is robust is the highest priority.
Here is the complete, final version of your app.py file, which includes all fixes discussed:
 * Firebase Database Fixes: Correctly using await asyncio.to_thread() for all synchronous Firestore calls in LinkManager and ShortCodeGenerator.
 * Localization/Config Fixes: Full support for all declared locales (hi, he, arr), including correct flag data.
 * PWA Cleanup: All PWA soft-ask cookie logic has been removed from the root_redirect and index functions.
 * Reserved Codes: Updated to include all new locale codes.
This file should replace your existing app.py in its entirety.
📄 Complete and Corrected app.py
import os
import secrets
import html
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Literal, Callable, List, Tuple
from contextlib import asynccontextmanager

import socket
import ipaddress
import asyncio
import io
import base64
import tempfile
import logging
from logging.handlers import RotatingFileHandler
import json
import threading
import time
from functools import lru_cache

import validators
from pydantic import BaseModel, Field, validator, constr
from firebase_admin.firestore import transactional

import qrcode
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.staticfiles import StaticFiles

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, parse_qs, urlunparse
from fastapi.templating import Jinja2Templates

from fastapi import FastAPI, HTTPException, Request, Depends, Path, BackgroundTasks, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.query import Query

# Import all constants and the final emoji map.
import config
from config import *
from config import LOCALE_TO_EMOJI 
# Note: Exceptions are NOT imported here.

# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging() -> logging.Logger:
    """Configure structured logging with rotation"""
    logger = logging.getLogger("url_shortener")
    logger.setLevel(logging.INFO)
    
    # Console handler
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # File handler with rotation
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=10_485_760,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# ============================================================================
# CUSTOM EXCEPTIONS (Defined locally, used globally)
# ============================================================================

class SecurityException(HTTPException):
    """Raised when security validation fails"""
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

class ValidationException(HTTPException):
    """Raised when input validation fails"""
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

class ResourceNotFoundException(HTTPException):
    """Raised when a resource is not found"""
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

class ResourceExpiredException(HTTPException):
    """Raised when a resource has expired"""
    def __init__(self, detail: str = "Resource has expired"):
        super().__init__(status_code=status.HTTP_410_GONE, detail=detail)


# ============================================================================
# PYDANTIC MODELS (Used for type hinting and response validation)
# ============================================================================

class LinkResponse(BaseModel):
    """Response model for created links"""
    short_url: str
    stats_url: str
    delete_url: str
    qr_code_data: str

class LinkCreatePayload(BaseModel):
    """Request model for creating links"""
    long_url: str = Field(..., min_length=1, max_length=config.MAX_URL_LENGTH) 
    ttl: Literal["1h", "24h", "1w", "never"] = "24h"
    custom_code: Optional[constr(pattern=r'^[a-zA-Z0-9]{4,20}$')] = None
    utm_tags: Optional[str] = Field(None, max_length=500)
    owner_id: Optional[str] = Field(None, max_length=100)
    
    @validator('long_url')
    def validate_url(cls, v):
        """Validate URL format"""
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        return v.strip()
    
    @validator('utm_tags')
    def validate_utm_tags(cls, v):
        """Validate UTM tags"""
        if v:
            v = v.strip()
            if v and not v.startswith(('utm_', '?utm_', '&utm_')):
                pass 
        return v

# ============================================================================
# LOCALIZATION
# ============================================================================

translations: Dict[str, Dict[str, str]] = {}

def load_translations_from_json() -> None:
    """Load translation data with error handling"""
    global translations
    try:
        file_path = os.path.join(os.path.dirname(__file__), "translations.json")
        if not os.path.exists(file_path):
            logger.warning("translations.json not found, creating empty translations")
            translations = {locale: {} for locale in config.SUPPORTED_LOCALES}
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            translations = json.load(f)
        
        missing_locales = set(config.SUPPORTED_LOCALES) - set(translations.keys())
        if missing_locales:
            logger.warning(f"Missing translations for locales: {missing_locales}")
            for locale in missing_locales:
                translations[locale] = {}
        
        logger.info(f"Translations loaded successfully for {len(translations)} locales")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse translations.json: {e}")
        raise RuntimeError("Translation file is malformed") from e
    except Exception as e:
        logger.error(f"Failed to load translations.json: {e}")
        raise RuntimeError("Translation file loading failed") from e

@lru_cache(maxsize=128)
def get_translation(locale: str, key: str) -> str:
    """Get translation with caching and fallback"""
    if locale in translations and key in translations[locale]:
        return translations[locale][key]
    
    if key in translations.get(config.DEFAULT_LOCALE, {}):
        return translations[config.DEFAULT_LOCALE][key]
    
    logger.debug(f"Missing translation: {locale}.{key}")
    return f"[{key}]"

def get_browser_locale(request: Request) -> str:
    """Extract locale from cookie or Accept-Language header"""
    lang_cookie = request.cookies.get("lang")
    if lang_cookie and lang_cookie in config.SUPPORTED_LOCALES:
        return lang_cookie
    
    try:
        lang_header = request.headers.get("accept-language", "")
        if lang_header:
            primary_lang = lang_header.split(',')[0].split('-')[0].lower()
            if primary_lang in config.SUPPORTED_LOCALES:
                return primary_lang
    except Exception as e:
        logger.debug(f"Error parsing Accept-Language header: {e}")
    
    return config.DEFAULT_LOCALE

def get_translator_and_locale(
    request: Request, 
    locale: str = Path(..., description="The language code")
) -> Tuple[Callable[[str], str], str]:
    """Dependency for getting translator function and locale"""
    valid_locale = locale if locale in config.SUPPORTED_LOCALES else config.DEFAULT_LOCALE
    
    def translate(key: str) -> str:
        return get_translation(valid_locale, key)
    
    return translate, valid_locale

def get_translator(tr: Tuple = Depends(get_translator_and_locale)) -> Callable[[str], str]:
    """Get translator function"""
    return tr[0]

def get_current_locale(tr: Tuple = Depends(get_translator_and_locale)) -> str:
    """Get current locale"""
    return tr[1]

def get_api_translator(request: Request) -> Callable[[str], str]:
    """Get translator for API endpoints"""
    locale = get_browser_locale(request)
    return lambda key: get_translation(locale, key)

def get_hreflang_tags(request: Request, locale: str = Depends(get_current_locale)) -> List[Dict]:
    """Generate hreflang tags for SEO"""
    tags = []
    current_path = request.url.path
    
    base_path = current_path.replace(f"/{locale}", "", 1) or "/"
    
    for lang in config.SUPPORTED_LOCALES:
        lang_path = f"/{lang}{base_path}".replace("//", "/")
        tags.append({
            "rel": "alternate",
            "hreflang": lang,
            "href": str(request.url.replace(path=lang_path))
        })
    
    default_path = f"/{config.DEFAULT_LOCALE}{base_path}".replace("//", "/")
    tags.append({
        "rel": "alternate",
        "hreflang": "x-default",
        "href": str(request.url.replace(path=default_path))
    })
    
    return tags

# ============================================================================
# FIREBASE INITIALIZATION
# ============================================================================

class FirebaseManager:
    """Manage Firebase connection and cleanup"""
    
    def __init__(self):
        self.db: Optional[firestore.Client] = None
        self.app: Optional[firebase_admin.App] = None
        self._temp_file_path: Optional[str] = None
        self._lock = threading.Lock()
    
    def initialize(self) -> firestore.Client:
        """Initialize Firebase with proper error handling"""
        with self._lock:
            if self.db:
                return self.db
            
            try:
                cred = self._get_credentials()
                self.app = self._initialize_app(cred)
                self.db = firestore.client(app=self.app)
                logger.info("Firebase initialized successfully")
                return self.db
            
            except Exception as e:
                logger.error(f"Failed to initialize Firebase: {e}")
                raise RuntimeError("Database connection failure") from e
    
    def _get_credentials(self) -> credentials.Certificate:
        """Get Firebase credentials from environment"""
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.info("Using GOOGLE_APPLICATION_CREDENTIALS")
            return credentials.ApplicationDefault()
        
        firebase_config_str = os.getenv("FIREBASE_CONFIG")
        if firebase_config_str:
            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp_file:
                    tmp_file.write(firebase_config_str)
                    self._temp_file_path = tmp_file.name
                
                logger.info(f"Using FIREBASE_CONFIG via temp file: {self._temp_file_path}")
                return credentials.Certificate(self._temp_file_path)
            
            except Exception as e:
                logger.error(f"Failed to create temp credential file: {e}")
                raise
        
        raise ValueError("Neither GOOGLE_APPLICATION_CREDENTIALS nor FIREBASE_CONFIG is set")
    
    def _initialize_app(self, cred: credentials.Certificate) -> firebase_admin.App:
        """Initialize or reuse Firebase app"""
        try:
            app = get_app()
            logger.info("Reusing existing Firebase app")
            return app
        except ValueError:
            app = firebase_admin.initialize_app(cred)
            logger.info("Initialized new Firebase app")
            return app
    
    def cleanup(self) -> None:
        """Cleanup temporary credential file"""
        if self._temp_file_path and os.path.exists(self._temp_file_path):
            try:
                os.remove(self._temp_file_path)
                logger.info(f"Cleaned up temp credential file: {self._temp_file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")

firebase_manager = FirebaseManager()

def get_db() -> firestore.Client:
    """Dependency for getting database client"""
    return firebase_manager.initialize()

# ============================================================================
# URL VALIDATION & SECURITY
# ============================================================================

class URLValidator:
    """Comprehensive URL validation and security checks"""
    
    @staticmethod
    def is_public_ip(ip_str: str) -> bool:
        """Check if IP is public (not private/reserved)"""
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_global
        except ValueError:
            return False
    
    @staticmethod
    async def resolve_hostname(hostname: str) -> str:
        """Resolve hostname to IP with security checks"""
        try:
            ip_address = await asyncio.to_thread(socket.gethostbyname, hostname)
            
            if not URLValidator.is_public_ip(ip_address):
                raise SecurityException(f"Blocked request to non-public IP: {ip_address}")
            
            return ip_address
        
        except socket.gaierror as e:
            raise ValidationException(f"Could not resolve hostname: {hostname}")
    
    @staticmethod
    def validate_url_structure(url: str) -> str:
        """Validate URL structure and format"""
        if not url or not url.strip():
             raise ValidationException("URL cannot be empty")
        url = url.strip()
        
        if len(url) > config.MAX_URL_LENGTH:
            raise ValidationException(f"URL exceeds maximum length of {config.MAX_URL_LENGTH}")
        
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        
        try:
            parsed = urlparse(url)
            
            if parsed.scheme not in config.ALLOWED_SCHEMES:
                raise ValidationException(f"URL scheme must be one of: {config.ALLOWED_SCHEMES}")
            
            if not parsed.netloc:
                raise ValidationException("URL must include a domain")
            
            hostname = parsed.netloc.split(':')[0].lower()
            if hostname in config.BLOCKED_DOMAINS:
                raise SecurityException(f"Domain is blocked: {hostname}")
            
            if '.' not in hostname:
                try:
                    ipaddress.ip_address(hostname)
                except ValueError:
                    raise ValidationException("Invalid domain: no TLD found")
            
            return url
        
        except ValueError as e:
            raise ValidationException(f"Invalid URL format: {e}")
    
    @staticmethod
    def validate_url_public(url: str) -> bool:
        """Validate URL points to public resource"""
        return validators.url(url, public=True)
    
    @classmethod
    async def validate_and_sanitize(cls, url: str) -> str:
        """Complete URL validation pipeline"""
        url = cls.validate_url_structure(url)
        
        if not cls.validate_url_public(url):
            raise ValidationException("URL must be publicly accessible")
        
        parsed = urlparse(url)
        hostname = parsed.netloc.split(':')[0]
        await cls.resolve_hostname(hostname)
        
        return url

# ============================================================================
# SHORT CODE GENERATION
# ============================================================================

class ShortCodeGenerator:
    """Generate unique short codes"""
    
    def __init__(self, length: int = config.SHORT_CODE_LENGTH):
        self.length = length
        self.charset = string.ascii_lowercase + string.digits
    
    def generate(self) -> str:
        """Generate a random short code"""
        return ''.join(random.choice(self.charset) for _ in range(self.length))
    
    async def generate_unique(self, db: firestore.Client) -> str:
        """Generate unique short code with collision checking"""
        collection = db.collection("links")
        
        for attempt in range(config.MAX_ID_RETRIES):
            code = self.generate()
            
            # CRITICAL FIX: The synchronous Firebase call is correctly wrapped.
            doc = await asyncio.to_thread(collection.document(code).get)
            
            if not doc.exists:
                return code
            
            logger.debug(f"Short code collision on attempt {attempt + 1}: {code}")
        
        raise RuntimeError(f"Could not generate unique short code after {config.MAX_ID_RETRIES} attempts")

code_generator = ShortCodeGenerator()

# ============================================================================
# QR CODE GENERATION
# ============================================================================

def generate_qr_code_data_uri(text: str, box_size: int = 10, border: int = 2) -> str:
    """Generate QR code as base64 data URI"""
    try:
        img = qrcode.make(text, box_size=box_size, border=border)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64_str}"
    except Exception as e:
        logger.error(f"Failed to generate QR code: {e}")
        raise

# ============================================================================
# METADATA FETCHER
# ============================================================================

class MetadataFetcher:
    """Fetch and parse webpage metadata"""
    
    def __init__(self, timeout: float = config.METADATA_FETCH_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    async def fetch(self, url: str) -> Dict[str, Optional[str]]:
        """Fetch metadata from URL"""
        meta = {
            "title": None,
            "description": None,
            "image": None,
            "favicon": None
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self.headers, follow_redirects=True)
                response.raise_for_status()
                
                final_url = str(response.url)
                soup = BeautifulSoup(response.text, "lxml")
                
                if og_title := soup.find("meta", property="og:title"):
                    meta["title"] = og_title.get("content")
                elif title_tag := soup.find("title"):
                    meta["title"] = title_tag.string
                
                if og_desc := soup.find("meta", property="og:description"):
                    meta["description"] = og_desc.get("content")
                elif desc := soup.find("meta", attrs={"name": "description"}):
                    meta["description"] = desc.get("content")
                
                if og_image := soup.find("meta", property="og:image"):
                    meta["image"] = urljoin(final_url, og_image.get("content"))
                
                if favicon := (soup.find("link", rel="icon") or soup.find("link", rel="shortcut icon")):
                    meta["favicon"] = urljoin(final_url, favicon.get("href"))
                else:
                    parsed = urlparse(final_url)
                    meta["favicon"] = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
                
                logger.info(f"Successfully fetched metadata for {url}")
                return meta
        
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching metadata for {url}")
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error fetching metadata for {url}: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error fetching metadata for {url}: {e}")
        
        return meta

metadata_fetcher = MetadataFetcher()

# ============================================================================
# AI SUMMARIZATION (HUGGING FACE)
# ============================================================================

class AISummarizer:
    """AI-powered content summarization using Hugging Face"""
    
    def __init__(self):
        self.api_key = config.HUGGINGFACE_API_KEY
        self.model = config.SUMMARIZATION_MODEL
        self.api_url = f"https://api-inference.huggingface.co/models/{self.model}"
        self.timeout = config.SUMMARY_TIMEOUT
        self.enabled = bool(self.api_key)
        
        if not self.enabled:
            logger.warning("HUGGINGFACE_API_KEY not set - AI summarization disabled")
    
    async def query_api(self, text: str, max_length: int = 150, min_length: int = 30) -> Optional[str]:
        """Query Hugging Face API for summarization"""
        if not self.enabled:
            return None
        
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload = {
                "inputs": text[:config.SUMMARY_MAX_LENGTH],
                "parameters": {
                    "max_length": max_length,
                    "min_length": min_length
                }
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                
                result = response.json()
                if isinstance(result, list) and result and 'summary_text' in result[0]:
                    return result[0]['summary_text'].strip()
                
                logger.error(f"Unexpected API response format: {result}")
                return None
        
        except httpx.TimeoutException:
            logger.error("Timeout querying Hugging Face API")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Hugging Face: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"Error querying Hugging Face API: {e}")
        
        return None
    
    async def fetch_and_summarize(self, url: str) -> Optional[str]:
        """Fetch webpage content and generate summary"""
        if not self.enabled:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
                headers = {"User-Agent": "Mozilla/5.0"}
                response = await client.get(url, headers=headers, follow_redirects=True)
                response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            
            page_text = soup.get_text(separator=" ", strip=True)
            if not page_text:
                raise ValueError("No text content found")
            
            summary = await self.query_api(page_text)
            return summary
        
        except Exception as e:
            logger.error(f"Failed to fetch and summarize {url}: {e}")
            return None
    
    async def summarize_in_background(self, doc_ref: firestore.DocumentReference, url: str) -> None:
        """Background task for summarization"""
        if not self.enabled:
            await asyncio.to_thread(doc_ref.update, {"summary_status": "failed"})
            return
        
        try:
            summary = await self.fetch_and_summarize(url)
            
            if summary:
                # Store summary and completion time
                await asyncio.to_thread(doc_ref.update, {
                    "summary_status": "complete",
                    "summary_text": summary,
                    "summary_updated_at": datetime.now(timezone.utc)
                })
                logger.info(f"Summary completed for {doc_ref.id}")
            else:
                raise Exception("Empty summary returned")
        
        except Exception as e:
            logger.error(f"Summary generation failed for {doc_ref.id}: {e}")
            await asyncio.to_thread(doc_ref.update, {"summary_status": "failed"})

summarizer = AISummarizer()

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

# Define reserved codes globally (includes all supported locales)
RESERVED_CODES = {'api', 'health', 'static', 'r', 'robots', 'sitemap', 
                  'en', 'es', 'fr', 'de', 'it', 'pt', 'ja', 'zh', 'ar', 'ru', 'he', 'hi', 'arr', 'preview', 'dashboard'}

class LinkManager:
    """Manage link CRUD operations"""
    
    def __init__(self, db: firestore.Client):
        self.db = db
        self.collection = db.collection("links")
    
    async def create(
        self,
        long_url: str,
        ttl: str,
        custom_code: Optional[str] = None,
        owner_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create new shortened link"""
        if custom_code:
            # Check against reserved codes
            if custom_code.lower() in RESERVED_CODES:
                 raise ValidationException(f"'{custom_code}' is a reserved code and cannot be used.")
            
            # CRITICAL FIX: Ensure blocking Firebase call is wrapped
            doc = await asyncio.to_thread(self.collection.document(custom_code).get)
            if doc.exists:
                raise ValidationException("Custom code already exists")
            code = custom_code
        else:
            # Uses the corrected generate_unique method
            code = await code_generator.generate_unique(self.db) 
        
        expires_at = self._calculate_expiration(ttl)
        
        data = {
            "long_url": long_url,
            "deletion_token": secrets.token_urlsafe(32),
            "created_at": datetime.now(timezone.utc),
            "click_count": 0,
            "clicks_by_day": {},
            "meta_fetched": False,
            "meta_title": None,
            "meta_description": None,
            "meta_image": None,
            "meta_favicon": None,
            "owner_id": owner_id,
            "summary_status": "pending" if summarizer.enabled else "disabled",
            "summary_text": None,
            "summary_updated_at": None
        }
        
        if expires_at:
            data["expires_at"] = expires_at
        
        # CRITICAL FIX: Ensure the set operation is wrapped correctly
        await asyncio.to_thread(self.collection.document(code).set, data) 
        
        logger.info(f"Created link {code} -> {long_url}")
        return {**data, "short_code": code}
    
    async def get(self, code: str) -> Optional[Dict[str, Any]]:
        """Retrieve link by short code"""
        doc = await asyncio.to_thread(self.collection.document(code).get)
        
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        data["short_code"] = doc.id
        return data
    
    async def increment_clicks(self, code: str) -> str:
        """Increment click count and return long URL"""
        doc_ref = self.collection.document(code)
        
        @transactional
        def update_transaction(transaction, doc_ref):
            doc = doc_ref.get(transaction=transaction)
            
            if not doc.exists:
                raise ResourceNotFoundException("Link not found")
            
            link = doc.to_dict()
            
            expires_at = link.get("expires_at")
            if expires_at and expires_at < datetime.now(timezone.utc):
                raise ResourceExpiredException("Link has expired")
            
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            day_key = f"clicks_by_day.{today_str}"
            
            transaction.update(doc_ref, {
                "click_count": firestore.Increment(1),
                day_key: firestore.Increment(1)
            })
            
            return link["long_url"]
        
        try:
            transaction = self.db.transaction()
            return await asyncio.to_thread(update_transaction, transaction, doc_ref)
        
        except (ResourceNotFoundException, ResourceExpiredException) as e:
            raise e
        except Exception as e:
            logger.warning(f"Transaction failed for {code}: {e}, falling back to non-atomic update")
            
            # Fallback to non-atomic update
            try:
                doc = await asyncio.to_thread(doc_ref.get)
                
                if not doc.exists:
                    raise ResourceNotFoundException("Link not found")
                
                link = doc.to_dict()
                
                expires_at = link.get("expires_at")
                if expires_at and expires_at < datetime.now(timezone.utc):
                    raise ResourceExpiredException("Link has expired")
                
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                day_key = f"clicks_by_day.{today_str}"
                
                await asyncio.to_thread(doc_ref.update, {
                    "click_count": firestore.Increment(1),
                    day_key: firestore.Increment(1)
                })
                
                return link["long_url"]
            
            except Exception as e2:
                logger.error(f"Fallback update failed for {code}: {e2}")
                
                # Last resort: just return URL without incrementing
                doc = await asyncio.to_thread(doc_ref.get)
                if doc.exists:
                    return doc.to_dict().get("long_url")
                raise ResourceNotFoundException("Link not found")
    
    async def delete(self, code: str, token: str) -> bool:
        """Delete link if token matches"""
        doc_ref = self.collection.document(code)
        doc = await asyncio.to_thread(doc_ref.get)
        
        if not doc.exists:
            raise ResourceNotFoundException("Link not found")
        
        link = doc.to_dict()
        
        if link.get("deletion_token") != token:
            raise ValidationException("Invalid deletion token")
        
        await asyncio.to_thread(doc_ref.delete)
        logger.info(f"Deleted link {code}")
        return True
    
    async def get_by_owner(self, owner_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all links for an owner"""
        query = (
            self.collection
            .where(filter=FieldFilter("owner_id", "==", owner_id))
            .order_by("created_at", direction=Query.DESCENDING)
            .limit(limit)
        )
        
        docs = await asyncio.to_thread(query.stream)
        
        links = []
        for doc in docs:
            data = doc.to_dict()
            data["short_code"] = doc.id
            
            if "created_at" in data and data["created_at"]:
                data["created_at"] = data["created_at"].isoformat()
            if "expires_at" in data and data["expires_at"]:
                data["expires_at"] = data["expires_at"].isoformat()
            
            links.append(data)
        
        return links
    
    @staticmethod
    def _calculate_expiration(ttl: str) -> Optional[datetime]:
        """Calculate expiration datetime from TTL"""
        delta = TTL_MAP.get(ttl)
        if delta is None:
            return None
        return datetime.now(timezone.utc) + delta

# ============================================================================
# CLEANUP WORKER
# ============================================================================

class CleanupWorker:
    """Background worker for cleaning expired links"""
    
    def __init__(self, db: firestore.Client, interval: int = config.CLEANUP_INTERVAL_SECONDS):
        self.db = db
        self.interval = interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start cleanup worker thread"""
        if self.running:
            logger.warning("Cleanup worker already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        logger.info("Cleanup worker started")
    
    def stop(self) -> None:
        """Stop cleanup worker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Cleanup worker stopped")
    
    def _worker(self) -> None:
        """Worker loop"""
        while self.running:
            try:
                deleted = self._cleanup_expired()
                if deleted > 0:
                    logger.info(f"Cleanup: deleted {deleted} expired links")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            
            time.sleep(self.interval)
    
    def _cleanup_expired(self) -> int:
        """Delete expired links"""
        collection = self.db.collection("links")
        now = datetime.now(timezone.utc)
        
        expired_docs = (
            collection
            .where(filter=FieldFilter("expires_at", "<", now))
            .limit(config.CLEANUP_BATCH_SIZE)
            .stream()
        )
        
        batch = self.db.batch()
        count = 0
        
        for doc in expired_docs:
            batch.delete(doc.reference)
            count += 1
        
        if count > 0:
            batch.commit()
        
        return count

# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

worker_instance: Optional[CleanupWorker] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global worker_instance
    # Startup
    try:
        config.validate()
        load_translations_from_json()
        db = firebase_manager.initialize()
        
        cleanup_worker = CleanupWorker(db)
        worker_instance = cleanup_worker
        cleanup_worker.start()
        
        logger.info("Application started successfully")
        yield
        
    finally:
        # Shutdown
        if worker_instance:
            worker_instance.stop()
        firebase_manager.cleanup()
        logger.info("Application shutdown complete")

# Main app
app = FastAPI(
    title="Shortlinks.art - Professional URL Shortener",
    description="A secure, scalable URL shortening service with AI summarization",
    version="2.0.0",
    lifespan=lifespan
)

# Localized router
i18n_router = FastAPI()

# Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ============================================================================
# TEMPLATE CONTEXT
# ============================================================================

BOOTSTRAP_CDN = '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">'
BOOTSTRAP_JS = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>'

async def get_common_context(
    request: Request,
    translator: Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale),
    hreflang_tags: List = Depends(get_hreflang_tags)
) -> Dict:
    """Get common template context"""
    return {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": translator,
        "locale": locale,
        "hreflang_tags": hreflang_tags,
        "current_year": datetime.now(timezone.utc).year,
        "RTL_LOCALES": config.RTL_LOCALES,
        "LOCALE_TO_FLAG_CODE": LOCALE_TO_FLAG_CODE,
        "FLAG_EMOJIS": LOCALE_TO_EMOJI,
        "BOOTSTRAP_CDN": BOOTSTRAP_CDN,
        "BOOTSTRAP_JS": BOOTSTRAP_JS,
        "config": config,
    }

# ============================================================================
# NON-LOCALIZED ROUTES
# ============================================================================

@app.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    """Redirect to localized homepage"""
    locale = get_browser_locale(request)
    
    # 1. Prepare initial response
    # Use 302 Found after ditching PWA logic
    response = RedirectResponse(url=f"/{locale}", status_code=status.HTTP_302_FOUND)
    
    # 2. Set preferred language cookie
    response.set_cookie("lang", locale, max_age=365*24*60*60, samesite="lax")
    
    # PWA Soft-Ask Logic REMOVED
    
    return response

@app.get("/health")
async def health_check(db: firestore.Client = Depends(get_db)):
    """Health check endpoint"""
    try:
        # Test database connection
        test_doc = db.collection("_health").document("test")
        await asyncio.to_thread(test_doc.set, {"timestamp": datetime.now(timezone.utc)})
        
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "error",
                "error": str(e)
            }
        )

@app.post("/api/v1/links", response_model=LinkResponse)
@limiter.limit(config.RATE_LIMIT_CREATE)
async def api_create_link(
    request: Request,
    payload: LinkCreatePayload,
    translator: Callable = Depends(get_api_translator),
    db: firestore.Client = Depends(get_db)
):
    """Create a new shortened link"""
    try:
        # Validate and sanitize URL
        long_url = await URLValidator.validate_and_sanitize(payload.long_url)
        
        # Add UTM tags if provided
        if payload.utm_tags:
            cleaned_tags = payload.utm_tags.lstrip("?&")
            if cleaned_tags:
                separator = "&" if "?" in long_url else "?"
                long_url = f"{long_url}{separator}{cleaned_tags}"
        
        # Create link
        link_manager = LinkManager(db)
        link = await link_manager.create(
            long_url=long_url,
            ttl=payload.ttl,
            custom_code=payload.custom_code,
            owner_id=payload.owner_id
        )
        
        # Generate URLs
        locale = get_browser_locale(request)
        short_code = link['short_code']
        token = link['deletion_token']
        
        localized_preview_url = f"{config.BASE_URL}/{locale}/preview/{short_code}"
        qr_code_data = generate_qr_code_data_uri(localized_preview_url)
        
        return LinkResponse(
            short_url=f"{config.BASE_URL}/r/{short_code}",
            stats_url=f"{config.BASE_URL}/{locale}/stats/{short_code}",
            delete_url=f"{config.BASE_URL}/{locale}/delete/{short_code}?token={token}",
            qr_code_data=qr_code_data
        )
    
    except (ValidationException, SecurityException) as e:
        # Pass the exception detail (which is a translation key) to the client
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error creating link: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("error_creating_link")
        )

@app.get("/api/v1/my-links")
@limiter.limit(config.RATE_LIMIT_STATS)
async def api_get_my_links(
    request: Request,
    owner_id: str,
    translator: Callable = Depends(get_api_translator),
    db: firestore.Client = Depends(get_db)
):
    """Get all links for an owner"""
    if not owner_id:
        raise ValidationException(translator("owner_id_required"))
    
    try:
        link_manager = LinkManager(db)
        links = await link_manager.get_by_owner(owner_id)
        
        # Add URLs to each link
        for link in links:
            short_code = link["short_code"]
            link["short_url_preview"] = f"{config.BASE_URL}/preview/{short_code}"
            link["stats_url"] = f"{config.BASE_URL}/stats/{short_code}"
            link["delete_url"] = f"{config.BASE_URL}/delete/{short_code}?token={link['deletion_token']}"
        
        return {"links": links, "count": len(links)}
    
    except Exception as e:
        logger.error(f"Error fetching links for owner {owner_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("error_fetching_links")
        )

@app.get("/r/{short_code}")
async def redirect_short_code(
    short_code: str,
    request: Request, # FIX Bug #2: Added request parameter
    translator: Callable = Depends(get_api_translator)
):
    """Redirect short code to preview page"""
    try:
        if not short_code.isalnum() or len(short_code) < 4:
            raise ValidationException(translator("invalid_short_code"))
        
        # FIX Bug #2: Use the real request object to get the browser locale
        locale = get_browser_locale(request) 
        preview_url = f"/{locale}/preview/{short_code}"
        
        full_redirect_url = f"{config.BASE_URL}{preview_url}"
        
        return RedirectResponse(url=full_redirect_url, status_code=status.HTTP_301_MOVED_PERMANENTLY)
    
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error redirecting {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("redirect_error")
        )

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Robots.txt for SEO"""
    return f"""User-agent: *
Allow: /
Disallow: /api/
Disallow: /r/
Disallow: /health
Disallow: /*/delete/
Sitemap: {config.BASE_URL}/sitemap.xml
"""

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    """Generate sitemap for SEO"""
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    urls = []
    pages = ["", "/about", "/dashboard"]
    
    for locale in config.SUPPORTED_LOCALES:
        for page in pages:
            urls.append(f"""  <url>
    <loc>{config.BASE_URL}/{locale}{page}</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>{1.0 if not page else 0.8}</priority>
  </url>""")
    
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    
    return Response(content=xml, media_type="application/xml")

# ============================================================================
# LOCALIZED ROUTES
# ============================================================================

@i18n_router.get("/", response_class=HTMLResponse)
async def index(request: Request, common_context: Dict = Depends(get_common_context)):
    """Homepage"""
    
    # PWA Soft-Ask Logic REMOVED from context passing
    
    context = {
        **common_context,
    }
    
    return templates.TemplateResponse("index.html", context)

@i18n_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(common_context: Dict = Depends(get_common_context)):
    """Dashboard page"""
    return templates.TemplateResponse("dashboard.html", common_context)

@i18n_router.get("/about", response_class=HTMLResponse)
async def about(common_context: Dict = Depends(get_common_context)):
    """About page"""
    return templates.TemplateResponse("about.html", common_context)

@i18n_router.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(
    short_code: str,
    background_tasks: BackgroundTasks,
    common_context: Dict = Depends(get_common_context),
    db: firestore.Client = Depends(get_db)
):
    """Preview page with metadata and security warning"""
    translator = common_context["_"]
    
    try:
        link_manager = LinkManager(db)
        link = await link_manager.get(short_code)
        
        if not link:
            # Passes translation key to be handled by exception handler
            raise ResourceNotFoundException(translator("link_not_found")) 
        
        expires_at = link.get("expires_at")
        if expires_at and expires_at < datetime.now(timezone.utc):
            raise ResourceExpiredException(translator("link_expired"))
        
        long_url = link["long_url"]
        safe_href_url = long_url if long_url.startswith(("http://", "https://")) else f"https://{long_url}"
        
        doc_ref = db.collection("links").document(short_code)
        
        meta_title = link.get("meta_title")
        meta_description = link.get("meta_description")
        meta_image = link.get("meta_image")
        meta_favicon = link.get("meta_favicon")
        summary = link.get("summary_text")
        summary_status = link.get("summary_status", "pending")
        
        # 1. Fetch Metadata if needed
        if not link.get("meta_fetched"):
            meta = await metadata_fetcher.fetch(safe_href_url)
            await asyncio.to_thread(doc_ref.update, {
                "meta_fetched": True,
                "meta_title": meta.get("title"),
                "meta_description": meta.get("description"),
                "meta_image": meta.get("image"),
                "meta_favicon": meta.get("favicon")
            })
            link.update(meta)
            meta_title = meta.get("title")
            meta_description = meta.get("description")
            meta_image = meta.get("image")
            meta_favicon = meta.get("favicon")
        
        # 2. Schedule Summarization if pending
        if summary_status == "pending" and summarizer.enabled:
            background_tasks.add_task(summarizer.summarize_in_background, doc_ref, safe_href_url)
            await asyncio.to_thread(doc_ref.update, {"summary_status": "in_progress"})
        
        # 3. Determine display description
        if summary_status == "complete" and summary:
            display_description = summary
        elif summary_status in ["pending", "in_progress"]:
            display_description = translator("preview_summary_pending")
        elif summary_status == "failed":
            display_description = translator("preview_summary_failed")
        else:
            display_description = meta_description or translator("no_description")
        
        context = {
            **common_context,
            "short_code": short_code,
            "escaped_long_url_href": html.escape(safe_href_url, quote=True),
            "escaped_long_url_display": html.escape(long_url),
            "meta_title": html.escape(meta_title or translator("no_title")),
            "meta_description": html.escape(display_description),
            "meta_image_url": html.escape(meta_image or "", quote=True),
            "meta_favicon_url": html.escape(meta_favicon or "", quote=True),
            "has_image": bool(meta_image),
            "has_favicon": bool(meta_favicon),
            "has_description": bool(display_description)
        }
        
        return templates.TemplateResponse("preview.html", context)
    
    except (ResourceNotFoundException, ResourceExpiredException) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error in preview for {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("preview_error")
        )

@i18n_router.get("/preview/{short_code}/redirect", response_class=RedirectResponse)
async def continue_to_link(
    short_code: str,
    translator: Callable = Depends(get_translator),
    db: firestore.Client = Depends(get_db)
):
    """Continue to final destination and increment clicks"""
    try:
        link_manager = LinkManager(db)
        long_url = await link_manager.increment_clicks(short_code)
        
        if not long_url.startswith(("http://", "https://")):
            long_url = f"https://{long_url}"
        
        return RedirectResponse(url=long_url, status_code=status.HTTP_302_FOUND)
    
    except (ResourceNotFoundException, ResourceExpiredException) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error redirecting {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("redirect_error")
        )

@i18n_router.get("/stats/{short_code}", response_class=HTMLResponse)
@limiter.limit(config.RATE_LIMIT_STATS)
async def stats(
    request: Request,
    short_code: str,
    common_context: Dict = Depends(get_common_context),
    db: firestore.Client = Depends(get_db)
):
    """Statistics page"""
    translator = common_context["_"]
    
    try:
        link_manager = LinkManager(db)
        link = await link_manager.get(short_code)
        
        if not link:
            raise ResourceNotFoundException(translator("link_not_found"))
        
        context = {**common_context, "link": link}
        return templates.TemplateResponse("stats.html", context)
    
    except ResourceNotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error fetching stats for {short_code}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("stats_error")
        )

@i18n_router.get("/delete/{short_code}", response_class=HTMLResponse)
async def delete_link(
    short_code: str,
    token: Optional[str] = None,
    common_context: Dict = Depends(get_common_context),
    db: firestore.Client = Depends(get_db)
):
    """Delete link page"""
    translator = common_context["_"]
    
    if not token:
        context = {
            **common_context,
            "success": False,
            "message": translator("token_missing")
        }
        return templates.TemplateResponse("delete_status.html", context)
    
    try:
        link_manager = LinkManager(db)
        await link_manager.delete(short_code, token)
        
        context = {
            **common_context,
            "success": True,
            "message": translator("delete_success")
        }
    
    except (ResourceNotFoundException, ValidationException) as e:
        context = {
            **common_context,
            "success": False,
            "message": str(e.detail)
        }
    except Exception as e:
        logger.error(f"Error deleting {short_code}: {e}")
        context = {
            **common_context,
            "success": False,
            "message": translator("delete_error")
        }
    
    return templates.TemplateResponse("delete_status.html", context)

# Mount localized router
app.mount("/{locale}", i18n_router, name="localized")

# ============================================================================
# ERROR HANDLERS
# ============================================================================

def is_localized_route(path: str) -> bool:
    """Checks if the path is intended for a localized HTML page."""
    if not path.startswith('/'):
        return False
    
    segments = path.split('/')
    if len(segments) < 2:
        return False
    
    first_segment = segments[1]
    return first_segment in config.SUPPORTED_LOCALES

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Renders custom HTML error page for localized routes (404, 410)
    and falls back to JSON for APIs.
    """
    # 1. Check if the error is a 404 or 410 AND if the route is a localized page.
    if exc.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_410_GONE] and is_localized_route(request.url.path):
        
        try:
            locale = request.url.path.split('/')[1]
            if locale not in config.SUPPORTED_LOCALES:
                 locale = config.DEFAULT_LOCALE
        except:
            locale = config.DEFAULT_LOCALE
            
        translator = lambda key: get_translation(locale, key)
        
        context = {
            "request": request,
            "status_code": exc.status_code,
            "message": translator(exc.detail), # CRITICAL: Translate the error detail here
            "_": translator,
            "locale": locale,
            "BOOTSTRAP_CDN": BOOTSTRAP_CDN,
            "BOOTSTRAP_JS": BOOTSTRAP_JS,
            "current_year": datetime.now(timezone.utc).year,
            "RTL_LOCALES": config.RTL_LOCALES
        }
        
        return templates.TemplateResponse(
            "error.html", 
            context, 
            status_code=exc.status_code
        )

    # 2. For all other errors, return JSON.
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail or translator("generic_error_message")}
    )

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

