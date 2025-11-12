import os
import json
import logging
import threading
import time
import asyncio
import socket
import ipaddress
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse
from typing import Dict, Any, List, Tuple, Callable, Optional

import validators
from fastapi import Request, Depends, Path, HTTPException, status
from pydantic import BaseModel, Field, validator, constr

# Import local modules/constants
import config
from config import *
from db_manager import cleanup_expired_links as db_cleanup_expired_links # Import cleanup function
# NOTE: Necessary imports for MetadataFetcher/AISummarizer are handled inside the class bodies

# --- LOGGING SETUP ---

def setup_logging() -> logging.Logger:
    """Configure structured logging with rotation"""
    logger = logging.getLogger("url_shortener")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            maxBytes=10_485_760,
            backupCount=5
        )
        file_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# --- CUSTOM EXCEPTIONS (REQUIRED BY ROUTERS) ---

class SecurityException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

class ValidationException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

class ResourceNotFoundException(HTTPException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

class ResourceExpiredException(HTTPException):
    def __init__(self, detail: str = "Resource has expired"):
        super().__init__(status_code=status.HTTP_410_GONE, detail=detail)

# --- CLEANUP WORKER (Unchanged) ---

class CleanupWorker:
    """Background worker for cleaning expired links"""
    
    def __init__(self, interval: int = config.CLEANUP_INTERVAL_SECONDS):
        self.interval = interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        if self.running:
            logger.warning("Cleanup worker already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        logger.info("Cleanup worker started")
    
    def stop(self) -> None:
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Cleanup worker stopped")
    
    def _worker(self) -> None:
        while self.running:
            try:
                # Run the async cleanup function from db_manager.py in a synchronous thread
                deleted = asyncio.run(db_cleanup_expired_links(datetime.now(timezone.utc)))
                if deleted > 0:
                    logger.info(f"Cleanup: deleted {deleted} expired links")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            
            time.sleep(self.interval)

# --- GLOBAL LOCALIZATION SETUP (Unchanged) ---

translations: Dict[str, Dict[str, str]] = {}

def load_translations_from_json() -> None:
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
    if locale in translations and key in translations[locale]:
        return translations[locale][key]
    
    if key in translations.get(config.DEFAULT_LOCALE, {}):
        return translations[config.DEFAULT_LOCALE][key]
    
    return f"[{key}]"

# --- LOCALE & TRANSLATOR DEPENDENCIES (Unchanged) ---

def get_browser_locale(request: Request) -> str:
    lang_cookie = request.cookies.get("lang")
    if lang_cookie and lang_cookie in config.SUPPORTED_LOCALES:
        return lang_cookie
    
    try:
        lang_header = request.headers.get("accept-language", "")
        if lang_header:
            primary_lang = lang_header.split(',')[0].split('-')[0].lower()
            if primary_lang in config.SUPPORTED_LOCALES:
                return primary_lang
    except Exception:
        pass
    
    return config.DEFAULT_LOCALE


def get_current_locale(request: Request) -> str:
    lang_cookie = request.cookies.get("lang")
    if lang_cookie and lang_cookie in config.SUPPORTED_LOCALES:
        return lang_cookie
    
    try:
        lang_header = request.headers.get("accept-language", "")
        if lang_header:
            primary_lang = lang_header.split(',')[0].split('-')[0].lower()
            if primary_lang in config.SUPPORTED_LOCALES:
                return primary_lang
    except Exception:
        pass
    
    return config.DEFAULT_LOCALE


def get_translator_and_locale(
    request: Request, 
    locale: str = Path(..., description="The language code")
) -> Tuple[Callable[[str], str], str]:
    valid_locale = locale if locale in config.SUPPORTED_LOCALES else config.DEFAULT_LOCALE
    
    def translate(key: str) -> str:
        return get_translation(valid_locale, key)
    
    return translate, valid_locale

def get_translator(tr: Tuple = Depends(get_translator_and_locale)) -> Callable[[str], str]:
    return tr[0]

def get_current_locale(tr: Tuple = Depends(get_translator_and_locale)) -> str:
    return tr[1]

def get_api_translator(request: Request) -> Callable[[str], str]:
    locale = get_browser_locale(request)
    return lambda key: get_translation(locale, key)

# --- URL VALIDATION / SANITIZATION (Unchanged) ---

class URLValidator:
    """Comprehensive URL validation and security checks"""
    
    @staticmethod
    def is_public_ip(ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_global
        except ValueError:
            return False
    
    @staticmethod
    async def resolve_hostname(hostname: str) -> str:
        try:
            # NOTE: asyncio and socket imports must be available
            import asyncio
            import socket
            ip_address = await asyncio.to_thread(socket.gethostbyname, hostname)
            
            if not URLValidator.is_public_ip(ip_address):
                raise SecurityException(f"Blocked request to non-public IP: {ip_address}")
            
            return ip_address
        
        except socket.gaierror as e:
            raise ValidationException(f"Could not resolve hostname: {hostname}")
    
    @staticmethod
    def validate_url_structure(url: str) -> str:
        if not url or not url.strip():
             raise ValidationException("URL cannot be empty") 
        url = url.strip()
        
        if len(url) > config.MAX_URL_LENGTH:
            raise ValidationException(f"URL exceeds maximum length of {config.MAX_URL_LENGTH}")
        
        parsed_test = urlparse(url)
        if not parsed_test.scheme:
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
        return validators.url(url, public=True)
    
    @classmethod
    async def validate_and_sanitize(cls, url: str) -> str:
        url = cls.validate_url_structure(url)
        
        if not cls.validate_url_public(url):
            raise ValidationException("URL must be publicly accessible")
        
        parsed = urlparse(url)
        hostname = parsed.netloc.split(':')[0]
        await cls.resolve_hostname(hostname)
        
        return url

# --- QR CODE GENERATION ---

def generate_qr_code_data_uri(text: str, box_size: int = 10, border: int = 2) -> str:
    """Generate QR code as base64 data URI"""
    try:
        # NOTE: qrcode, io, base64 imports must be available
        import qrcode
        import io
        import base64
        img = qrcode.make(text, box_size=box_size, border=border)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64_str}"
    except Exception as e:
        logger.error(f"Failed to generate QR code: {e}")
        # Re-raise or handle appropriately
        raise

# --- METADATA FETCHER ---

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
            # NOTE: httpx, urllib.parse, bs4 imports must be available
            import httpx
            from urllib.parse import urljoin, urlparse
            from bs4 import BeautifulSoup
            
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

# --- AI SUMMARIZER ---

class AISummarizer:
    """AI-powered content summarization using Hugging Face"""
    
    def __init__(self, model: str = config.SUMMARIZATION_MODEL, api_url_base: str = "https://api-inference.huggingface.co/models/"):
        self.api_key = config.HUGGINGFACE_API_KEY
        self.model = model
        self.api_url = f"{api_url_base}{self.model}"
        self.timeout = config.SUMMARY_TIMEOUT
        self.enabled = bool(self.api_key)
        
        if not self.enabled:
            logger.warning("HUGGINGFACE_API_KEY not set - AI summarization disabled")
    
    async def query_api(self, text: str, max_length: int = 150, min_length: int = 30) -> Optional[str]:
        if not self.enabled: return None
        
        try:
            import httpx
            headers = {"Authorization": f"Bearer {self.api_key}"}
            payload = {"inputs": text[:config.SUMMARIZATION_MODEL],
                       "parameters": {"max_length": max_length, "min_length": min_length}}
            
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
        if not self.enabled: return None
        
        try:
            import httpx
            from bs4 import BeautifulSoup
            
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
    
    async def summarize_in_background(self, doc_ref, url: str) -> None:
        if not self.enabled:
            return
        
        try:
            summary = await self.fetch_and_summarize(url)
            
            if summary:
                # Placeholder for Async DB Update
                pass
            
        except Exception as e:
            logger.error(f"Summary generation failed for {doc_ref.id if hasattr(doc_ref, 'id') else 'link'}: {e}")
            pass

# --- TEMPLATE CONTEXT DEPENDENCY (Unchanged) ---

BOOTSTRAP_CDN = '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">'
BOOTSTRAP_JS = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>'

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

async def get_common_context(
    request: Request,
    translator: Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale),
    hreflang_tags: List = Depends(get_hreflang_tags)
) -> Dict:
    """Get common template context"""
    return {
        "request": request,
        "ADSENSE_SCRIPT": config.ADSENSE_SCRIPT,
        "_": translator,
        "locale": locale,
        "hreflang_tags": hreflang_tags,
        "current_year": datetime.now(timezone.utc).year,
        "RTL_LOCALES": config.RTL_LOCALES,
        "LOCALE_TO_FLAG_CODE": config.LOCALE_TO_FLAG_CODE,
        "FLAG_EMOJIS": config.LOCALE_TO_EMOJI,
        "BOOTSTRAP_CDN": BOOTSTRAP_CDN,
        "BOOTSTRAP_JS": BOOTSTRAP_JS,
        # 🟢 CORRECTED LINE: Pass the instance directly
        "config": config, 
    }
