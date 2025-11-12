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
import json      # For loading translations
import threading # For the cleanup thread
import time      # For the cleanup thread

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

#
# =====================================================================
#  Configuration for Hugging Face Inference API
# =====================================================================
#
# Your HF Token (MUST be set as an environment variable)
HF_TOKEN = os.environ.get("HF_TOKEN") 
# The lightweight summarization model we'll use
HF_MODEL_ENDPOINT = "https://api-inference.huggingface.co/models/distilbart-cnn-12-6"
# Max characters to send for summarization
MAX_TEXT_FOR_LLM = 4000 


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
translations = {}
TRANSLATIONS_FILE = "translations.json"

def load_translations():
    """Loads translation strings from the JSON file."""
    global translations
    if not os.path.exists(TRANSLATIONS_FILE):
        logger.critical(f"FATAL: Translations file not found at {TRANSLATIONS_FILE}")
        raise RuntimeError(f"Translations file not found: {TRANSLATIONS_FILE}")
    try:
        with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
            translations = json.load(f)
        logger.info(f"Successfully loaded translations from {TRANSLATIONS_FILE}")
    except json.JSONDecodeError as e:
        logger.critical(f"FATAL: Failed to decode {TRANSLATIONS_FILE}: {e}")
        raise RuntimeError(f"Invalid JSON in translations file: {e}")
    except Exception as e:
        logger.critical(f"FATAL: Could not read {TRANSLATIONS_FILE}: {e}")
        raise RuntimeError(f"Could not read translations file: {e}")
# Load translations on startup
load_translations()


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
        if translated: return translated
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback: return fallback
        return key
    return _, valid_locale

def get_api_translator(request: Request) -> Callable[[str], str]:
    locale = get_browser_locale(request)
    def _(key: str) -> str:
        translated = translations.get(locale, {}).get(key)
        if translated: return translated
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback: return fallback
        return key
    return _

def get_translator(tr: tuple = Depends(get_translator_and_locale)) -> Callable[[str], str]:
    return tr[0]
def get_current_locale(tr: tuple = Depends(get_translator_and_locale)) -> str:
    return tr[1]

def get_hreflang_tags(request: Request, locale: str = Depends(get_current_locale)) -> list[dict]:
    tags = []
    current_path = request.url.path
    base_path = current_path.replace(f"/{locale}", "", 1)
    if not base_path: base_path = "/"
    for lang in SUPPORTED_LOCALES:
        lang_path = f"/{lang}{base_path}"
        if lang_path.startswith('//'): lang_path = lang_path[1:]
        tags.append({"rel": "alternate", "hreflang": lang, "href": str(request.url.replace(path=lang_path))})
    default_path = f"/{DEFAULT_LOCALE}{base_path}"
    if default_path.startswith('//'): default_path = default_path[1:]
    tags.append({"rel": "alternate", "hreflang": "x-default", "href": str(request.url.replace(path=default_path))})
    return tags

async def get_common_context(
    request: Request,
    _: Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale),
    hreflang_tags: list = Depends(get_hreflang_tags)
) -> dict:
    return {
        "request": request, "ADSENSE_SCRIPT": ADSENSE_SCRIPT, "_": _, "locale": locale,
        "hreflang_tags": hreflang_tags, "current_year": datetime.now(timezone.utc).year,
        "RTL_LOCALES": RTL_LOCALES, "LOCALE_TO_FLAG_CODE": LOCALE_TO_FLAG_CODE
    }

# ---------------- FIREBASE ----------------
db: firestore.Client = None
APP_INSTANCE = None
def init_firebase():
    global db, APP_INSTANCE
    if db: return db
    firebase_config_str = os.environ.get("FIREBASE_CONFIG")
    temp_file_path = None
    cred = None
    try:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.ApplicationDefault()
            logger.info("Using GOOGLE_APPLICATION_CREDENTIALS path.")
        elif firebase_config_str:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
                tmp_file.write(firebase_config_str)
                temp_file_path = tmp_file.name
            cred = credentials.Certificate(temp_file_path)
            logger.info(f"Using FIREBASE_CONFIG JSON string via temporary file: {temp_file_path}")
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
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try: os.remove(temp_file_path)
            except Exception as cleanup_e: logger.warning(f"Failed to clean up temporary credential file: {cleanup_e}")

# ---------------- HELPERS ----------------
def _generate_short_code(length=SHORT_CODE_LENGTH) -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_short_code() -> str:
    collection = init_firebase().collection("links")
    for _ in range(MAX_ID_RETRIES):
        code = _generate_short_code()
        doc = collection.document(code).get()
        if not doc.exists: return code
    raise RuntimeError("Could not generate unique short code.")

def calculate_expiration(ttl: str) -> Optional[datetime]:
    delta = TTL_MAP.get(ttl, TTL_MAP["24h"])
    if delta is None: return None
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
        if doc.exists: raise ValueError("Custom code already exists")
        code = custom_code
    else:
        code = generate_unique_short_code()
    expires_at = calculate_expiration(ttl)
    deletion_token = secrets.token_urlsafe(32)
    data = {
        "long_url": long_url, "deletion_token": deletion_token,
        "created_at": datetime.now(timezone.utc), "click_count": 0,
        "clicks_by_day": {}, "clicks_by_country": {},
        "meta_fetched": False, "meta_title": None, "meta_description": None,
        "meta_image": None, "meta_favicon": None, "owner_id": owner_id,
        "meta_summary": None, "summary_fetched": False # Summary fields
    }
    if expires_at:
        data["expires_at"] = expires_at
    collection.document(code).set(data)
    return { **data, "short_code": code }

def get_link(code: str) -> Optional[Dict[str, Any]]:
    collection = init_firebase().collection("links")
    doc = collection.document(code).get()
    if not doc.exists: return None
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    meta = {"title": None, "description": None, "image": None, "favicon": None}
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        if not hostname: raise ValueError("Invalid hostname")
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
            if og_title := soup.find("meta", property="og:title"): meta["title"] = og_title.get("content")
            elif title := soup.find("title"): meta["title"] = title.string
            if og_desc := soup.find("meta", property="og:description"): meta["description"] = og_desc.get("content")
            elif desc := soup.find("meta", name="description"): meta["description"] = desc.get("content")
            if og_image := soup.find("meta", property="og:image"): meta["image"] = urljoin(final_url, og_image.get("content"))
            if favicon := soup.find("link", rel="icon") or soup.find("link", rel="shortcut icon"):
                meta["favicon"] = urljoin(final_url, favicon.get("href"))
            else:
                parsed_url_fallback = urlparse(final_url)
                meta["favicon"] = f"{parsed_url_fallback.scheme}://{parsed_url_fallback.netloc}/favicon.ico"
    except (httpx.RequestError, httpx.HTTPStatusError) as e: print(f"Error fetching metadata for {url}: {e}")
    except SecurityException as e: print(f"SSRF Prevention: {e}")
    except Exception as e: print(f"Error parsing or validating URL for {url}: {e}")
    return meta

async def update_country_stats(short_code: str, ip_address: str):
    """BG Task: Update country stats based on IP"""
    if not is_public_ip(ip_address):
        logger.debug(f"Skipping country lookup for non-public IP: {ip_address}")
        return
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://ipinfo.io/{ip_address}/json", timeout=2.0)
            response.raise_for_status()
            data = response.json()
            country_code = data.get("country")
            if country_code:
                db_client = init_firebase() 
                doc_ref = db_client.collection("links").document(short_code)
                country_key = f"clicks_by_country.{country_code}"
                doc_ref.update({country_key: firestore.Increment(1)})
                logger.debug(f"Logged click from {country_code} for {short_code}")
    except Exception as e:
        logger.warning(f"Failed to get/update country stats for {short_code} (IP: {ip_address}): {e}")

async def get_llm_summary(text: str) -> Optional[str]:
    """Calls the Hugging Face Inference API to get a summary."""
    if not text:
        return None
    if not HF_TOKEN:
        logger.error("HF_TOKEN environment variable not set. Cannot get summary.")
        return None

    payload = {
        "inputs": text,
        "parameters": {"min_length": 25, "max_length": 100}
    }
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(HF_MODEL_ENDPOINT, json=payload, headers=headers, timeout=30.0)
            
            if response.status_code == 503: # Handle 503: Model is loading
                logger.warning("Hugging Face model is loading (503). Retrying after wait...")
                retry_data = response.json()
                wait_time = retry_data.get("estimated_time", 20.0)
                await asyncio.sleep(wait_time)
                response = await client.post(HF_MODEL_ENDPOINT, json=payload, headers=headers, timeout=30.0)

            response.raise_for_status()
            data = response.json()
            
            if data and isinstance(data, list) and data[0] and "summary_text" in data[0]:
                summary = data[0]["summary_text"]
                return summary.strip()
            else:
                logger.error(f"Unexpected API response from Hugging Face: {data}")
        
    except httpx.RequestError as e:
        logger.error(f"Could not connect to Hugging Face API at {HF_MODEL_ENDPOINT}: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Hugging Face API returned error: {e.response.status_code} {e.response.text}")
    except Exception as e:
        logger.error(f"Error getting LLM summary: {e}")
    return None

async def generate_and_cache_summary(short_code: str, url: str):
    """BG Task: Fetch, summarize, and cache the summary."""
    logger.debug(f"Starting summary task for {short_code} ({url})")
    full_text = None
    try:
        # 1. Fetch the full page content
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=5.0)
            response.raise_for_status()
            
            # 2. Extract and truncate text
            soup = BeautifulSoup(response.text, "lxml")
            if body := soup.find("body"):
                full_text = body.get_text(separator=" ", strip=True)
            if not full_text:
                logger.warning(f"Could not extract text for summary: {short_code}")
                return

            truncated_text = full_text[:MAX_TEXT_FOR_LLM]
            
            # 3. Get summary from LLM
            summary = await get_llm_summary(truncated_text)
            
            # 4. Save to Firestore
            db_client = init_firebase()
            doc_ref = db_client.collection("links").document(short_code)
            
            if summary:
                doc_ref.update({"meta_summary": summary, "summary_fetched": True})
                logger.info(f"Successfully generated and cached summary for {short_code}")
            else:
                doc_ref.update({"summary_fetched": True}) # Mark as fetched even if summary failed
                logger.warning(f"LLM failed to provide summary for {short_code}")

    except Exception as e:
        logger.error(f"Failed generate_and_cache_summary task for {short_code}: {e}")
        try:
            db_client = init_firebase()
            doc_ref = db_client.collection("links").document(short_code)
            doc_ref.update({"summary_fetched": True}) # Mark as tried
        except Exception as db_e:
            logger.error(f"Failed to update summary_fetched status for {short_code}: {db_e}")

# ---------------- APP ----------------
app = FastAPI(title="Shortlinks.art URL Shortener")
i18n_router = FastAPI()
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
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
    background_tasks: BackgroundTasks, # Added
    _ : Callable = Depends(get_api_translator)
):
    long_url = payload.long_url.strip()
    if not long_url:
        raise HTTPException(status_code=400, detail=_("invalid_url"))
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url
    try:
        parsed = urlparse(long_url)
        if not parsed.scheme or not parsed.netloc: raise ValueError("Missing scheme or domain")
        if '.' not in parsed.netloc:
            try: ipaddress.ip_address(parsed.netloc)
            except ValueError: raise ValueError("Invalid domain, no TLD")
    except ValueError as e:
        logger.warning(f"Invalid URL format submitted: {long_url} ({e})")
        raise HTTPException(status_code=400, detail=_("invalid_url"))
    if not validators.url(long_url, public=True):
        logger.warning(f"Blocked non-public or invalid URL: {long_url}")
        raise HTTPException(status_code=400, detail=_("invalid_url"))
    if payload.utm_tags:
        cleaned_tags = payload.utm_tags.lstrip("?&")
        if cleaned_tags:
            long_url = f"{long_url}{'&' if '?' in long_url else '?'}{cleaned_tags}"
    try:
        link = create_link_in_db(long_url, payload.ttl, payload.custom_code, payload.owner_id)
        
        locale = get_browser_locale(request)
        short_code = link['short_code']
        token = link['deletion_token']

        # Trigger the summary task immediately in the background
        background_tasks.add_task(generate_and_cache_summary, short_code, long_url)

        localized_preview_url = f"{BASE_URL}/{locale}/preview/{short_code}"
        qr_code_data_uri = generate_qr_code_data_uri(localized_preview_url)
        return {
            "short_url": f"{BASE_URL}/r/{short_code}",
            "stats_url": f"{BASE_URL}/{locale}/stats/{short_code}",
            "delete_url": f"{BASE_URL}/{locale}/delete/{short_code}?token={token}",
            "qr_code_data": qr_code_data_uri
        }
    except ValueError as e: raise HTTPException(status_code=409, detail=_("custom_code_exists"))
    except RuntimeError as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/my-links")
async def get_my_links(owner_id: str, _ : Callable = Depends(get_api_translator)):
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
    content = f"User-agent: *\nDisallow: /api/\nDisallow: /r/\nDisallow: /health\nSitemap: {BASE_URL}/sitemap.xml\n"
    return content

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for lang in SUPPORTED_LOCALES:
        xml_content += f"""
  <url><loc>{BASE_URL}/{lang}</loc><lastmod>{last_mod}</lastmod><priority>1.0</priority></url>
  <url><loc>{BASE_URL}/{lang}/about</loc><lastmod>{last_mod}</lastmod><priority>0.8</priority></url>
  <url><loc>{BASE_URL}/{lang}/dashboard</loc><lastmod>{last_mod}</lastmod><priority>0.7</priority></url>
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
    transaction.update(doc_ref, {"click_count": firestore.Increment(1), day_key: firestore.Increment(1)})
    return link["long_url"]

@app.get("/r/{short_code}")
async def redirect_link(
    short_code: str, 
    request: Request,
    background_tasks: BackgroundTasks,
    _ : Callable = Depends(get_api_translator)
):
    db = init_firebase()
    doc_ref = db.collection("links").document(short_code)
    long_url = None
    try:
        transaction = db.transaction()
        long_url = update_clicks_in_transaction(transaction, doc_ref, get_text=_)
    except HTTPException as e: raise e 
    except Exception as e:
        logger.warning(f"Click count transaction for {short_code} failed: {e}. Retrying non-atomically.")
        try:
            link_doc = doc_ref.get() 
            if not link_doc.exists: raise HTTPException(status_code=404, detail=_("link_not_found"))
            link = link_doc.to_dict()
            expires_at = link.get("expires_at")
            if expires_at and expires_at < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail=_("link_expired"))
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            day_key = f"clicks_by_day.{today_str}"
            doc_ref.update({"click_count": firestore.Increment(1), day_key: firestore.Increment(1)})
            long_url = link["long_url"]
        except HTTPException as he: raise he
        except Exception as e2:
            logger.error(f"Non-transactional update for {short_code} failed: {e2}. Redirecting without count.")
            if 'link' in locals() and link: long_url = link.get("long_url")
            if long_url is None:
                try:
                    link_doc = doc_ref.get()
                    if link_doc.exists: long_url = link_doc.to_dict().get("long_url")
                    else: raise HTTPException(status_code=404, detail=_("link_not_found"))
                except Exception as e3:
                     logger.error(f"Final attempt to get long_url for {short_code} failed: {e3}.")
                     raise HTTPException(status_code=404, detail=_("link_not_found"))
    if not long_url:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    # Trigger country stats task
    try:
        ip_address = get_remote_address(request)
        background_tasks.add_task(update_country_stats, short_code, ip_address)
    except Exception as e:
        logger.warning(f"Failed to schedule country stats task for {short_code}: {e}")
    
    absolute_url = "https://" + long_url if not long_url.startswith(("http://", "https")) else long_url
    return RedirectResponse(url=absolute_url)

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
    common_context: dict = Depends(get_common_context)
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
    safe_href_url = "https://" + long_url if not long_url.startswith(("http://", "https")) else long_url
    
    if link.get("meta_fetched"):
        meta = {
            "title": link.get("meta_title"), "description": link.get("meta_description"),
            "image": link.get("meta_image"), "favicon": link.get("meta_favicon")
        }
    else:
        meta = await fetch_metadata(safe_href_url)
        try:
            doc_ref.update({
                "meta_fetched": True, "meta_title": meta.get("title"),
                "meta_description": meta.get("description"),
                "meta_image": meta.get("image"), "meta_favicon": meta.get("favicon")
            })
        except Exception as e:
            print(f"Error updating cache for {short_code}: {e}")
    
    # Get summary status
    summary = link.get("meta_summary")
    summary_fetched = link.get("summary_fetched", False)
            
    context = {
        **common_context, "short_code": short_code,
        "escaped_long_url_href": html.escape(safe_href_url, quote=True),
        "escaped_long_url_display": html.escape(long_url),
        "meta_title": html.escape(meta.get("title") or "Title not found"),
        "meta_description": html.escape(meta.get("description") or "No description available."),
        "meta_image_url": html.escape(meta.get("image") or "", quote=True),
        "meta_favicon_url": html.escape(meta.get("favicon") or "", quote=True),
        "has_image": bool(meta.get("image")), "has_favicon": bool(meta.get("favicon")),
        "has_description": bool(meta.get("description")),
        "summary": html.escape(summary or ""),
        "has_summary": bool(summary),
        "summary_fetched": summary_fetched # Pass status to template
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
    short_code: str, token: Optional[str] = None,
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
        context = {**common_context, "success": True, "message": _("delete_success")}
    else:
        context = {**common_context, "success": False, "message": _("delete_invalid_token")}
    return templates.TemplateResponse("delete_status.html", context)

class SecurityException(Exception):
    pass

# --- Mount the localized router ---
app.mount("/{locale}", i18n_router, name="localized")

# --- Background Cleanup Thread ---
def _cleanup_loop():
    logger.info("🧹 Cleanup thread started. Will check for expired links every 10 minutes.")
    time.sleep(30) 
    while True:
        try:
            db = init_firebase() 
            if not db:
                logger.error("Cleanup thread: DB not initialized. Retrying in 60s.")
                time.sleep(60)
                continue
            now = datetime.now(timezone.utc)
            links_ref = db.collection("links")
            query = links_ref.where(filter=FieldFilter("expires_at", "<", now)).limit(50)
            docs = query.stream()
            count = 0
            for doc in docs:
                logger.info(f"Cleanup: Deleting expired link {doc.id}...")
                doc.reference.delete()
                count += 1
            if count > 0: logger.info(f"Cleanup: Successfully deleted {count} expired links.")
            else: logger.debug("Cleanup: No expired links found this cycle.")
            time.sleep(600) # 10 minutes
        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")
            time.sleep(60)

def start_cleanup_thread():
    logger.info("Starting background cleanup thread...")
    cleanup_thread = threading.Thread(target=_cleanup_loop)
    cleanup_thread.daemon = True 
    cleanup_thread.start()
    logger.info("Cleanup thread is now running in the background.")

# --- Start background tasks ---
start_cleanup_thread()
