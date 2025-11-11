import os
import secrets
import html
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

# --- NEW IMPORTS (for SSRF Fix) ---
import socket
import ipaddress
import asyncio
# --- END NEW IMPORTS ---

import io
import base64
import qrcode
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.staticfiles import StaticFiles

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from fastapi.templating import Jinja2Templates

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

# ---------------- CONFIG ----------------
BASE_URL = os.environ.get("BASE_URL", "https://shortlinks.art")
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 10

TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

# ---------------- FIREBASE ----------------
db: firestore.Client = None
APP_INSTANCE = None

import threading
import time

def start_cleanup_thread():
    thread = threading.Thread(target=cleanup_worker, daemon=True)
    thread.start()
    print("[CLEANUP] Background cleanup worker started.")

def cleanup_worker():
    while True:
        try:
            deleted = cleanup_expired_links()
            print(f"[CLEANUP] Deleted {deleted} expired links.")
        except Exception as e:
            print(f"[CLEANUP ERROR] {e}")
        time.sleep(1800)  # 30 minutes

def cleanup_expired_links():
    db = init_firebase()
    collection = db.collection("links")
    now = datetime.now(timezone.utc)
    expired_docs = (
        collection
        .where("expires_at", "<", now)
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
    global db, APP_INSTANCE
    if db:
        return db
    firebase_config_str = os.environ.get("FIREBASE_CONFIG")
    cred = None
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        cred = credentials.ApplicationDefault()
    elif firebase_config_str:
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        temp_file.write(firebase_config_str)
        temp_file.close()
        cred = credentials.Certificate(temp_file.name)
        os.remove(temp_file.name)
    if cred is None:
        raise RuntimeError("Firebase config missing.")
    try:
        APP_INSTANCE = get_app()
    except ValueError:
        APP_INSTANCE = firebase_admin.initialize_app(cred)
    db = firestore.client(app=APP_INSTANCE)
    return db

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

# --- UPDATED: create_link_in_db ---
def create_link_in_db(long_url: str, ttl: str = "24h", custom_code: Optional[str] = None) -> Dict[str, Any]:
    collection = init_firebase().collection("links")
    if custom_code:
        if not custom_code.isalnum() or len(custom_code) > 20:
            raise ValueError("Custom code must be alphanumeric and <=20 chars")
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
        "clicks_by_day": {}  # <-- NEW: Initialize daily click map
    }
    if expires_at:
        data["expires_at"] = expires_at
    collection.document(code).set(data)
    
    short_url_preview = f"{BASE_URL}/preview/{code}"
    stats_url = f"{BASE_URL}/stats/{code}"
    delete_url = f"{BASE_URL}/delete/{code}?token={deletion_token}"

    return {
        **data,
        "short_code": code,
        "short_url_preview": short_url_preview,
        "stats_url": stats_url,
        "delete_url": delete_url
    }
# --- END UPDATED HELPER ---

def get_link(code: str) -> Optional[Dict[str, Any]]:
    collection = init_firebase().collection("links")
    doc = collection.document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

def is_public_ip(ip_str: str) -> bool:
    """Checks if an IP address is public."""
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
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Shortlinks.art URL Shortener")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROUTES ----------------
ADSENSE_CLIENT_ID = "pub-6170587092427912"
ADSENSE_SCRIPT = f"""
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT_ID}"
     crossorigin="anonymous"></script>
"""

@app.get("/health")
async def health():
    try:
        init_firebase()
        return {"status": "ok", "database": "initialized"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

@app.post("/api/v1/links")
@limiter.limit("10/minute")
async def api_create_link(request: Request, payload: Dict[str, Any]):
    long_url = payload.get("long_url")
    ttl = payload.get("ttl", "24h")
    custom_code = payload.get("custom_code")
    utm_tags = payload.get("utm_tags")
    
    if not long_url:
        raise HTTPException(status_code=400, detail="Missing long_url")
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    if utm_tags:
        cleaned_tags = utm_tags.lstrip("?&")
        if cleaned_tags:
            if "?" in long_url:
                long_url = f"{long_url}&{cleaned_tags}"
            else:
                long_url = f"{long_url}?{cleaned_tags}"

    try:
        link = create_link_in_db(long_url, ttl, custom_code)
        qr_code_data_uri = generate_qr_code_data_uri(link["short_url_preview"])
        return {
            "short_url": link["short_url_preview"],
            "stats_url": link["stats_url"],
            "delete_url": link["delete_url"],
            "qr_code_data": qr_code_data_uri
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    context = {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT
    }
    return templates.TemplateResponse("index.html", context)

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    content = f"""User-agent: *
Disallow: /api/
Disallow: /r/
Disallow: /preview/
Disallow: /health
Sitemap: {BASE_URL}/sitemap.xml
"""
    return content

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(request: Request, short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    
    long_url = link["long_url"]
    
    if not long_url.startswith(("http://", "https://")):
        safe_href_url = "https://" + long_url
    else:
        safe_href_url = long_url
    
    meta = await fetch_metadata(safe_href_url)
    
    context = {
        "request": request,
        "short_code": short_code,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "escaped_long_url_href": html.escape(safe_href_url, quote=True),
        "escaped_long_url_display": html.escape(long_url),
        "meta_title": html.escape(meta.get("title") or "Title not found"),
        "meta_description": html.escape(meta.get("description") or "No description available."),
        "meta_image_url": html.escape(meta.get("image") or "", quote=True),
        "meta_favicon_url": html.escape(meta.get("favicon") or "", quote=True),
        "has_image": bool(meta.get("image")),
        "has_favicon": bool(meta.get("favicon")),
        "has_description": bool(meta.get("description"))
    }
    
    return templates.TemplateResponse("preview.html", context)

# --- UPDATED: /r/{short_code} route ---
@app.get("/r/{short_code}")
async def redirect_link(short_code: str):
    collection_ref = init_firebase().collection("links")
    doc_ref = collection_ref.document(short_code)
    
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Link not found")
    
    link = doc.to_dict()
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")

    try:
        # --- NEW: Track clicks by day ---
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_key = f"clicks_by_day.{today_str}"
        
        # Update both total count and daily count
        doc_ref.update({
            "click_count": firestore.Increment(1),
            day_key: firestore.Increment(1)
        })
        # --- END NEW ---
    except Exception as e:
        print(f"Error incrementing click count: {e}")

    long_url = link["long_url"]
    if not long_url.startswith(("http://", "https://")):
        absolute_url = "https://" + long_url
    else:
        absolute_url = long_url

    return RedirectResponse(url=absolute_url)
# --- END UPDATED ROUTE ---

@app.get("/stats/{short_code}", response_class=HTMLResponse)
async def stats(request: Request, short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    context = {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "link": link
    }
    return templates.TemplateResponse("stats.html", context)

@app.get("/delete/{short_code}", response_class=HTMLResponse)
async def delete(request: Request, short_code: str, token: Optional[str] = None):
    if not token:
        raise HTTPException(status_code=400, detail="Deletion token is missing")
    
    collection_ref = init_firebase().collection("links")
    doc_ref = collection_ref.document(short_code)
    
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Link not found")
    
    link = doc.to_dict()
    
    if link.get("deletion_token") == token:
        doc_ref.delete()
        context = {
            "request": request, 
            "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
            "success": True, 
            "message": "Link successfully deleted."
        }
    else:
        context = {
            "request": request,
            "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
            "success": False,
            "message": "Invalid deletion token. Link was not deleted."
        }
        
    return templates.TemplateResponse("delete_status.html", context)

class SecurityException(Exception):
    pass

start_cleanup_thread()
