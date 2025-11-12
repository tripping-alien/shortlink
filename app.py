import os
import secrets
import html
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Literal, Callable

import socket
import ipaddress
import asyncio
import io
import base64
import tempfile
import logging
import json
import threading
import time

import validators
from pydantic import BaseModel, constr
from firebase_admin.firestore import transactional

import qrcode
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.staticfiles import StaticFiles

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from fastapi.templating import Jinja2Templates

from fastapi import FastAPI, HTTPException, Request, Depends, Path, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.query import Query

# ---------------- CONFIG ----------------
BASE_URL = os.environ.get("BASE_URL", "https://shortlinks.art")
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 10
logger = logging.getLogger(__name__)

TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

# ---------------- LOCALIZATION (i18n) ----------------

SUPPORTED_LOCALES = ["en", "es", "zh", "hi", "pt", "fr", "de", "ar", "ru", "he"]
DEFAULT_LOCALE = "en"
RTL_LOCALES = ["ar", "he"]

LOCALE_TO_FLAG_CODE = {
    "en": "gb", "es": "es", "zh": "cn", "hi": "in", "pt": "br",
    "fr": "fr", "de": "de", "ar": "sa", "ru": "ru", "he": "il",
}

translations: Dict[str, Dict[str, str]] = {}

def load_translations_from_json():
    """Loads all translation data from the external JSON file."""
    global translations
    try:
        file_path = os.path.join(os.path.dirname(__file__), "translations.json")
        if not os.path.exists(file_path):
            logger.error("translations.json not found! Using empty dictionary.")
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            translations = json.load(f)
        logger.info("Translations loaded successfully from JSON file.")

    except Exception as e:
        logger.error(f"Failed to load or parse translations.json: {e}")
        raise RuntimeError("Translation file loading failed.") from e


# ---------------- LLM Summarizer Setup (Hugging Face API) ----------------
HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY")
SUMMARIZATION_MODEL = "facebook/bart-large-cnn" 
HF_API_URL = f"https://api-inference.huggingface.co/models/{SUMMARIZATION_MODEL}"
HF_HEADERS = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"} if HUGGINGFACE_API_KEY else {}

if not HUGGINGFACE_API_KEY:
    logger.warning("HUGGINGFACE_API_KEY is not set. AI summarizer will be disabled.")


async def query_huggingface(payload: dict) -> Optional[str]:
    if not HUGGINGFACE_API_KEY: 
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(HF_API_URL, headers=HF_HEADERS, json=payload)
            response.raise_for_status()
            
            result = response.json()
            if result and isinstance(result, list) and 'summary_text' in result[0]:
                return result[0]['summary_text'].strip()
            
            logger.error(f"Hugging Face API returned unexpected format: {result}")
            return None

    except httpx.HTTPStatusError as e:
        logger.error(f"Hugging Face API HTTP Error: {e.response.status_code}. Response: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Error querying Hugging Face: {e}")
        return None


async def generate_summary_background(doc_ref: firestore.DocumentReference, url: str):
    """Background task to fetch, summarize using Hugging Face, and save."""
    if not HUGGINGFACE_API_KEY:
        doc_ref.update({"summary_status": "failed"})
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True, timeout=10.0)
            response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "lxml")
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()
        page_text = soup.get_text(separator=" ", strip=True)
        
        if not page_text:
            raise ValueError("No text content found on page.")
        
        # Truncate content to 2000 characters for safety and model limits
        payload = {
            "inputs": page_text[:2000], 
            "parameters": {"max_length": 150, "min_length": 30}
        }
        
        summary = await query_huggingface(payload)

        if summary:
            doc_ref.update({
                "summary_status": "complete",
                "summary_text": summary
            })
            logger.info(f"Successfully generated and saved summary for {doc_ref.id} using {SUMMARIZATION_MODEL}")
        else:
            raise Exception("Hugging Face summary was empty or failed.")

    except Exception as e:
        logger.error(f"Failed to generate summary for {doc_ref.id}: {e}")
        doc_ref.update({"summary_status": "failed"})

# --- i18n Functions ---

def get_browser_locale(request: Request) -> str:
    lang_cookie = request.cookies.get("lang")
    if lang_cookie and lang_cookie in SUPPORTED_LOCALES:
        return lang_cookie
            
    try:
        lang_header = request.headers.get("accept-language")
        if lang_header:
            primary_lang = lang_header.split(',')[0].split('-')[0].lower()
            if primary_lang in SUPPORTED_LOCALES:
                return primary_lang
    except Exception:
        pass
    return DEFAULT_LOCALE

def get_translator_and_locale(
    request: Request, 
    locale: str = Path(..., description="The language code, e.g., 'en', 'es'")
) -> (Callable[[str], str], str):
    valid_locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    
    def _(key: str) -> str:
        translated = translations.get(valid_locale, {}).get(key)
        if translated:
            return translated
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback:
            return fallback
        return f"[{key}]"
        
    return _, valid_locale

def get_api_translator(request: Request) -> Callable[[str], str]:
    locale = get_browser_locale(request)
    def _(key: str) -> str:
        translated = translations.get(locale, {}).get(key)
        if translated:
            return translated
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback:
            return fallback
        return f"[{key}]"
    return _

def get_translator(tr: tuple = Depends(get_translator_and_locale)) -> Callable[[str], str]:
    return tr[0]

def get_current_locale(tr: tuple = Depends(get_translator_and_locale)) -> str:
    return tr[1]

def get_hreflang_tags(request: Request, locale: str = Depends(get_current_locale)) -> list[dict]:
    tags = []
    current_path = request.url.path
    
    base_path = current_path.replace(f"/{locale}", "", 1)
    if not base_path: 
        base_path = "/"
        
    for lang in SUPPORTED_LOCALES:
        lang_path = f"/{lang}{base_path}"
        if lang_path.startswith('//'):
            lang_path = lang_path[1:]
            
        tags.append({
            "rel": "alternate",
            "hreflang": lang,
            "href": str(request.url.replace(path=lang_path))
        })
    
    default_path = f"/{DEFAULT_LOCALE}{base_path}"
    if default_path.startswith('//'):
            default_path = default_path[1:]

    tags.append({
        "rel": "alternate",
        "hreflang": "x-default",
        "href": str(request.url.replace(path=default_path))
    })
    return tags

# BOOTSTRAP CONFIG
BOOTSTRAP_CDN = '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">'
BOOTSTRAP_JS = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>'

async def get_common_context(
    request: Request,
    _: Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale),
    hreflang_tags: list = Depends(get_hreflang_tags)
) -> dict:
    return {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": _,
        "locale": locale,
        "hreflang_tags": hreflang_tags,
        "current_year": datetime.now(timezone.utc).year,
        "RTL_LOCALES": RTL_LOCALES,
        "LOCALE_TO_FLAG_CODE": LOCALE_TO_FLAG_CODE,
        "BOOTSTRAP_CDN": BOOTSTRAP_CDN,
        "BOOTSTRAP_JS": BOOTSTRAP_JS,
    }

# ---------------- FIREBASE ----------------
db: firestore.Client = None
APP_INSTANCE = None
_firebase_temp_file_path = None

def start_cleanup_thread():
    import threading
    import time

    def cleanup_worker():
        while True:
            try:
                local_logger = logging.getLogger(__name__) 
                deleted = cleanup_expired_links()
                local_logger.info(f"[CLEANUP] Deleted {deleted} expired links.")
            except Exception as e:
                local_logger.error(f"[CLEANUP ERROR] {e}")
            time.sleep(1800) 

    thread = threading.Thread(target=cleanup_worker, daemon=True)
    thread.start()
    logger.info("[CLEANUP] Background cleanup worker started.")

def cleanup_expired_links():
    db = init_firebase()
    collection = db.collection("links")
    now = datetime.now(timezone.utc)
    expired_docs = (
        collection
        .where(filter=FieldFilter("expires_at", "<", now))
        .limit(100)
        .stream()
    )
    batch = db.batch()
    count = 0
    for doc in expired_docs:
        batch.delete(doc.reference)
        count += 1
    if count > 0:
        batch.commit()
    return count

def init_firebase():
    global db, APP_INSTANCE, _firebase_temp_file_path
    if db:
        return db

    firebase_config_str = os.environ.get("FIREBASE_CONFIG")
    cred = None

    try:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.ApplicationDefault()
            logger.info("Using GOOGLE_APPLICATION_CREDENTIALS path.")
        elif firebase_config_str:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
                tmp_file.write(firebase_config_str)
                _firebase_temp_file_path = tmp_file.name
            
            cred = credentials.Certificate(_firebase_temp_file_path)
            logger.info(f"Using FIREBASE_CONFIG JSON string via temporary file: {_firebase_temp_file_path}")
        
        if cred is None:
            logger.error("FIREBASE_CONFIG or GOOGLE_APPLICATION_CREDENTIALS is not set.")
            raise RuntimeError("Firebase configuration is missing.")

        try:
            APP_INSTANCE = get_app()
            logger.info("Reusing existing Firebase App instance.")
        except ValueError:
            APP_INSTANCE = firebase_admin.initialize_app(cred)
            logger.info("Initialized new Firebase App instance.")
        
        db = firestore.client(app=APP_INSTANCE)
        logger.info("Firebase Firestore client initialized successfully.")
        return db

    except Exception as e:
        logger.error(f"Error initializing Firebase or Firestore: {e}")
        raise RuntimeError("Database connection failure.") from e

def cleanup_firebase_temp_file():
    global _firebase_temp_file_path
    if _firebase_temp_file_path and os.path.exists(_firebase_temp_file_path):
        try:
            os.remove(_firebase_temp_file_path)
            logger.debug(f"Cleaned up temporary credential file at {_firebase_temp_file_path}")
        except Exception as cleanup_e:
            logger.warning(f"Failed to clean up temporary credential file: {cleanup_e}")

# ---------------- HELPERS ----------------
def _generate_short_code(length=SHORT_CODE_LENGTH) -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_short_code() -> str:
    collection = init_firebase().collection("links")
    for _ in range(MAX_ID_RETRIES):
        code = _generate_short_code()
        doc = collection.document(code).get()
        if not doc.exists:
            return code
    raise RuntimeError("Could not generate unique short code.")

def calculate_expiration(ttl: str) -> Optional[datetime]:
    delta = TTL_MAP.get(ttl, TTL_MAP["24h"])
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def generate_qr_code_data_uri(text: str) -> str:
    img = qrcode.make(text, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"

def create_link_in_db(long_url: str, ttl: str, custom_code: Optional[str] = None, owner_id: Optional[str] = None) -> Dict[str, Any]:
    collection = init_firebase().collection("links")
    if custom_code:
        doc = collection.document(custom_code).get()
        if doc.exists:
            raise ValueError("Custom code already exists")
        code = custom_code
    else:
        code = generate_unique_short_code()
        
    expires_at = calculate_expiration(ttl)
    deletion_token = secrets.token_urlsafe(32)
    data = {
        "long_url": long_url,
        "deletion_token": deletion_token,
        "created_at": datetime.now(timezone.utc),
        "click_count": 0,
        "clicks_by_day": {},
        "meta_fetched": False,
        "meta_title": None,
        "meta_description": None,
        "meta_image": None,
        "meta_favicon": None,
        "owner_id": owner_id,
        "summary_status": "pending",
        "summary_text": None
    }
    if expires_at:
        data["expires_at"] = expires_at
    collection.document(code).set(data)
    
    return {
        **data,
        "short_code": code,
    }

def get_link(code: str) -> Optional[Dict[str, Any]]:
    collection = init_firebase().collection("links")
    doc = collection.document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

def is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_global
    except ValueError:
        return False

async def fetch_metadata(url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    meta = {
        "title": None,
        "description": None,
        "image": None,
        "favicon": None
    }
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        if not hostname:
            raise ValueError("Invalid hostname")

        try:
            ip_address = await asyncio.to_thread(socket.gethostbyname, hostname)
        except socket.gaierror:
            raise ValueError("Could not resolve hostname")

        if not is_public_ip(ip_address):
            raise SecurityException(f"Blocked request to non-public IP: {ip_address}")

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=5.0)
            response.raise_for_status()
            
            final_url = str(response.url)
            soup = BeautifulSoup(response.text, "lxml")

            if og_title := soup.find("meta", property="og:title"):
                meta["title"] = og_title.get("content")
            elif title := soup.find("title"):
                meta["title"] = title.string
            if og_desc := soup.find("meta", property="og:description"):
                meta["description"] = og_desc.get("content")
            elif desc := soup.find("meta", name="description"):
                meta["description"] = desc.get("content")
            if og_image := soup.find("meta", property="og:image"):
                meta["image"] = urljoin(final_url, og_image.get("content"))
            if favicon := soup.find("link", rel="icon") or soup.find("link", rel="shortcut icon"):
                meta["favicon"] = urljoin(final_url, favicon.get("href"))
            else:
                parsed_url_fallback = urlparse(final_url)
                meta["favicon"] = f"{parsed_url_fallback.scheme}://{parsed_url_fallback.netloc}/favicon.ico"

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error fetching metadata for {url}: {e}")
    except SecurityException as e:
        print(f"SSRF Prevention: {e}")
    except Exception as e:
        print(f"Error parsing or validating URL for {url}: {e}")
    return meta


# ---------------- APP ----------------
app = FastAPI(title="Shortlinks.art URL Shortener")
i18n_router = FastAPI()

# Load translations immediately after defining the global placeholder
load_translations_from_json()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class LinkCreatePayload(BaseModel):
    long_url: str
    ttl: Literal["1h", "24h", "1w", "never"] = "24h"
    custom_code: Optional[constr(pattern=r'^[a-zA-Z0-9]*$', max_length=20)] = None
    utm_tags: Optional[str] = None
    owner_id: Optional[str] = None

# ---------------- ROUTES ----------------
ADSENSE_CLIENT_ID = "pub-6170587092427912"
ADSENSE_SCRIPT = f"""
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT_ID}"
     crossorigin="anonymous"></script>
"""

# === NON-LOCALIZED ROUTES (Mounted on main 'app') ===

@app.on_event("startup")
def on_startup():
    init_firebase()
    start_cleanup_thread()

@app.on_event("shutdown")
def on_shutdown():
    cleanup_firebase_temp_file()

@app.get("/")
async def root_redirect(request: Request):
    locale = get_browser_locale(request)
    response = RedirectResponse(url=f"/{locale}", status_code=307) 
    response.set_cookie("lang", locale, max_age=365*24*60*60, samesite="lax")
    return response

@app.get("/health")
async def health():
    try:
        init_firebase()
        return {"status": "ok", "database": "initialized"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

@app.post("/api/v1/links")
@limiter.limit("10/minute")
async def api_create_link(
    request: Request, 
    payload: LinkCreatePayload,
    _ : Callable = Depends(get_api_translator)
):
    long_url = payload.long_url.strip()
    
    if not long_url:
        raise HTTPException(status_code=400, detail=_("invalid_url"))

    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    try:
        parsed = urlparse(long_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Missing scheme or domain")
        
        if '.' not in parsed.netloc:
            try:
                ipaddress.ip_address(parsed.netloc)
            except ValueError:
                raise ValueError("Invalid domain, no TLD")
                
    except ValueError as e:
        logger.warning(f"Invalid URL format submitted: {long_url} ({e})")
        raise HTTPException(status_code=400, detail=_("invalid_url"))

    if not validators.url(long_url, public=True):
        logger.warning(f"Blocked non-public or invalid URL: {long_url}")
        raise HTTPException(status_code=400, detail=_("invalid_url"))

    if payload.utm_tags:
        cleaned_tags = payload.utm_tags.lstrip("?&")
        if cleaned_tags:
            if "?" in long_url:
                long_url = f"{long_url}&{cleaned_tags}"
            else:
                long_url = f"{long_url}?{cleaned_tags}"

    try:
        link = create_link_in_db(long_url, payload.ttl, payload.custom_code, payload.owner_id)
        
        locale = get_browser_locale(request)
        short_code = link['short_code']
        token = link['deletion_token']

        localized_preview_url = f"{BASE_URL}/{locale}/preview/{short_code}"
        
        qr_code_data_uri = generate_qr_code_data_uri(localized_preview_url)
        return {
            "short_url": f"{BASE_URL}/r/{short_code}",
            "stats_url": f"{BASE_URL}/{locale}/stats/{short_code}",
            "delete_url": f"{BASE_URL}/{locale}/delete/{short_code}?token={token}",
            "qr_code_data": qr_code_data_uri
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=_("custom_code_exists"))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/my-links")
async def get_my_links(
    owner_id: str,
    _ : Callable = Depends(get_api_translator)
):
    if not owner_id:
        raise HTTPException(status_code=400, detail=_("owner_id_required"))

    db = init_firebase()
    links_query = (
        db.collection("links")
        .where(filter=FieldFilter("owner_id", "==", owner_id))
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(100)
    )
    docs = links_query.stream()
    
    links_list = []
    for doc in docs:
        data = doc.to_dict()
        short_code = doc.id
        data["short_code"] = short_code
        data["short_url_preview"] = f"{BASE_URL}/preview/{short_code}" 
        data["stats_url"] = f"{BASE_URL}/stats/{short_code}"
        data["delete_url"] = f"{BASE_URL}/delete/{short_code}?token={data['deletion_token']}"
        data["created_at"] = data["created_at"].isoformat()
        if "expires_at" in data and data["expires_at"]:
            data["expires_at"] = data["expires_at"].isoformat()
            
        links_list.append(data)
        
    return {"links": links_list}

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    content = f"""User-agent: *
Disallow: /api/
Disallow: /r/
Disallow: /health
Disallow: /stats/
Disallow: /delete/
Sitemap: {BASE_URL}/sitemap.xml
"""
    return content

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
"""
    for lang in SUPPORTED_LOCALES:
        xml_content += f"""
  <url>
    <loc>{BASE_URL}/{lang}</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{BASE_URL}/{lang}/about</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>{BASE_URL}/{lang}/dashboard</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>0.7</priority>
  </url>
"""
    xml_content += "</urlset>"
    return Response(content=xml_content, media_type="application/xml")

@transactional
def update_clicks_in_transaction(transaction, doc_ref, get_text: Callable) -> str:
    doc = doc_ref.get(transaction=transaction)
    if not doc.exists:
        raise HTTPException(status_code=404, detail=get_text("link_not_found"))

    link = doc.to_dict()
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=get_text("link_expired"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_key = f"clicks_by_day.{today_str}"
    
    transaction.update(doc_ref, {
        "click_count": firestore.Increment(1),
        day_key: firestore.Increment(1)
    })
    
    return link["long_url"]

@app.get("/r/{short_code}")
async def redirect_link(
    short_code: str,
    _ : Callable = Depends(get_api_translator)
):
    """
    FIXED SECURITY FLOW: This route redirects to the localized Preview page (301)
    to enforce the security check.
    """
    db = init_firebase()
    doc_ref = db.collection("links").document(short_code)
    
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
        
    link = doc.to_dict()
    expires_at = link.get("expires_at")
    
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=_("link_expired"))

    locale = get_browser_locale(Request(scope={"type": "http", "headers": []}))
    
    preview_url = f"/{locale}/preview/{short_code}"
    full_redirect_url = f"{BASE_URL}{preview_url}"

    return RedirectResponse(url=full_redirect_url, status_code=301)


@app.get("/{locale}/preview/{short_code}/redirect", response_class=RedirectResponse)
async def continue_to_link(
    short_code: str,
    _ : Callable = Depends(get_translator) 
):
    """
    NEW ENDPOINT: Handles the click count and final redirect.
    """
    db = init_firebase()
    doc_ref = db.collection("links").document(short_code)
    long_url = None
    
    try:
        transaction = db.transaction()
        long_url = update_clicks_in_transaction(transaction, doc_ref, get_text=_)
        
    except HTTPException as e:
        raise e 
    except Exception as e:
        logger.warning(f"Click count transaction for {short_code} failed: {e}. Retrying non-atomically.")
        
        try:
            link_doc = doc_ref.get() 
            if not link_doc.exists:
                 raise HTTPException(status_code=404, detail=_("link_not_found"))
            
            link = link_doc.to_dict()
            expires_at = link.get("expires_at")
            if expires_at and expires_at < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail=_("link_expired"))
            
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            day_key = f"clicks_by_day.{today_str}"
            doc_ref.update({
                "click_count": firestore.Increment(1),
                day_key: firestore.Increment(1)
            })
            
            long_url = link["long_url"]
            
        except HTTPException as he:
            raise he
        except Exception as e2:
            logger.error(f"Non-transactional update for {short_code} failed: {e2}. Redirecting without count.")
            if 'link' in locals() and link:
                long_url = link.get("long_url")
            
            if long_url is None:
                try:
                    link_doc = doc_ref.get()
                    if link_doc.exists:
                        long_url = link_doc.to_dict().get("long_url")
                    else:
                        raise HTTPException(status_code=404, detail=_("link_not_found"))
                except Exception as e3:
                     logger.error(f"Final attempt to get long_url for {short_code} failed: {e3}.")
                     raise HTTPException(status_code=404, detail=_("link_not_found"))

    if not long_url:
        raise HTTPException(status_code=404, detail=_("link_not_found"))

    if not long_url.startswith(("http://", "https")):
        absolute_url = "https://" + long_url
    else:
        absolute_url = long_url

    return RedirectResponse(url=absolute_url, status_code=302)


# === LOCALIZED PAGE ROUTES (Mounted on 'i18n_router') ===

@i18n_router.get("/", response_class=HTMLResponse)
async def index(common_context: dict = Depends(get_common_context)):
    return templates.TemplateResponse("index.html", common_context)
    
@i18n_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(common_context: dict = Depends(get_common_context)):
    return templates.TemplateResponse("dashboard.html", common_context)

@i18n_router.get("/about", response_class=HTMLResponse)
async def about(common_context: dict = Depends(get_common_context)):
    return templates.TemplateResponse("about.html", common_context)

@i18n_router.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(
    short_code: str,
    common_context: dict = Depends(get_common_context),
    background_tasks: BackgroundTasks # FIX: Removed Depends()
):
    _ = common_context["_"]
    db_client = init_firebase()
    doc_ref = db_client.collection("links").document(short_code)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    link = doc.to_dict()
    link["short_code"] = doc.id
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=_("link_expired"))
    
    long_url = link["long_url"]
    
    if not long_url.startswith(("http://", "https")):
        safe_href_url = "https://" + long_url
    else:
        safe_href_url = long_url
    
    # Initialize variables for template
    meta_title = link.get("meta_title")
    meta_description = link.get("meta_description")
    meta_image = link.get("meta_image")
    meta_favicon = link.get("meta_favicon")
    summary = link.get("summary_text")
    summary_status = link.get("summary_status", "pending")
    
    # 1. Fetch Metadata (if needed)
    if not link.get("meta_fetched"):
        meta = await fetch_metadata(safe_href_url)
        try:
            doc_ref.update({
                "meta_fetched": True,
                "meta_title": meta.get("title"),
                "meta_description": meta.get("description"),
                "meta_image": meta.get("image"),
                "meta_favicon": meta.get("favicon")
            })
            meta_title = meta.get("title")
            meta_description = meta.get("description")
            meta_image = meta.get("image")
            meta_favicon = meta.get("favicon")
        except Exception as e:
            logger.error(f"Error updating cache for {short_code}: {e}")
    
    # 2. Trigger LLM Summary (if pending)
    if summary_status == "pending" and HUGGINGFACE_API_KEY:
        try:
            background_tasks.add_task(generate_summary_background, doc_ref, safe_href_url)
            doc_ref.update({"summary_status": "in_progress"})
            logger.info(f"Background summary task scheduled for {short_code}.")
        except Exception as e:
            logger.error(f"Failed to schedule background task for {short_code}: {e}")

    # 3. Determine Final Display Description
    if summary_status == "complete" and summary:
        display_description = summary
    elif summary_status in ["pending", "in_progress"]:
        display_description = _("preview_summary_pending")
    elif summary_status == "failed":
        display_description = _("preview_summary_failed")
    else:
        display_description = meta_description or "No description available."
    
    context = {
        **common_context,
        "short_code": short_code,
        "escaped_long_url_href": html.escape(safe_href_url, quote=True),
        "escaped_long_url_display": html.escape(long_url),
        "meta_title": html.escape(meta_title or "Title not found"),
        "meta_description": html.escape(display_description),
        "meta_image_url": html.escape(meta_image or "", quote=True),
        "meta_favicon_url": html.escape(meta_favicon or "", quote=True),
        "has_image": bool(meta_image),
        "has_favicon": bool(meta_favicon),
        "has_description": bool(display_description)
    }
    
    return templates.TemplateResponse("preview.html", context)

@i18n_router.get("/stats/{short_code}", response_class=HTMLResponse)
async def stats(
    short_code: str,
    common_context: dict = Depends(get_common_context)
):
    _ = common_context["_"]
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    context = { **common_context, "link": link }
    return templates.TemplateResponse("stats.html", context)

@i18n_router.get("/delete/{short_code}", response_class=HTMLResponse)
async def delete(
    short_code: str,
    token: Optional[str] = None,
    common_context: dict = Depends(get_common_context)
):
    _ = common_context["_"]
    if not token:
        raise HTTPException(status_code=400, detail=_("token_missing"))
    
    collection_ref = init_firebase().collection("links")
    doc_ref = collection_ref.document(short_code)
    
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    link = doc.to_dict()
    
    if link.get("deletion_token") == token:
        doc_ref.delete()
        context = {
            **common_context, 
            "success": True, 
            "message": _("delete_success")
        }
    else:
        context = {
            **common_context,
            "success": False,
            "message": _("delete_invalid_token")
        }
        
    return templates.TemplateResponse("delete_status.html", context)


class SecurityException(Exception):
    pass

# --- Mount the localized router ---
app.mount("/{locale}", i18n_router, name="localized")
