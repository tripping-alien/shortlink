import os
import secrets
import html
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

@app.on_event("startup")
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
        "created_at": datetime.now(timezone.utc)
    }
    if expires_at:
        data["expires_at"] = expires_at

    collection.document(code).set(data)
    return {**data, "short_code": code, "short_url": f"{BASE_URL}/preview/{code}"}

def get_link(code: str) -> Optional[Dict[str, Any]]:
    collection = init_firebase().collection("links")
    doc = collection.document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

# ---------------- APP ----------------
app = FastAPI(title="Shortlinks.art URL Shortener")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROUTES ----------------
# Google AdSense Publisher ID
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
async def api_create_link(payload: Dict[str, Any]):
    long_url = payload.get("long_url")
    ttl = payload.get("ttl", "24h")
    custom_code = payload.get("custom_code")
    
    if not long_url:
        raise HTTPException(status_code=400, detail="Missing long_url")

    # FIX 1: Normalize the URL before saving to the database
    # Add https:// if no scheme (http://, https://) is present
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    try:
        link = create_link_in_db(long_url, ttl, custom_code)
        return {"short_url": link["short_url"]}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def index():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shortlinks.art - URL Shortener</title>
    <meta name="description" content="Fast and simple URL shortener with previews.">
    {ADSENSE_SCRIPT} <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            background: #f3f4f6;
            color: #111827;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 1rem;
        }}
        .container {{
            background: #fff;
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 480px;
            text-align: center;
        }}
        input, select {{
            padding: 0.8rem;
            width: 100%;
            margin: 0.5rem 0;
            border-radius: 8px;
            border: 1px solid #d1d5db;
            font-size: 1rem;
            box-sizing: border-box;
        }}
        button {{
            background: #4f46e5;
            color: white;
            border: none;
            padding: 0.8rem 1.5rem;
            font-size: 1rem;
            border-radius: 8px;
            cursor: pointer;
            margin-top: 0.5rem;
            width: 100%;
        }}
        button:hover {{
            background: #6366f1;
        }}
        .short-link {{
            margin-top: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.6rem;
            background: #f9fafb;
            border-radius: 8px;
            word-break: break-word;
        }}
        .copy-btn {{
            background: #facc15;
            border: none;
            padding: 0.5rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            color: #111827;
        }}
        @media(max-width:500px){{
            .container {{ padding: 1rem; }}
            button {{ font-size: 0.9rem; }}
        }}
    </style>
    </head>
    <body>
    <div class="container">
      <h1>Shortlinks.art</h1>
      <input type="url" id="longUrl" placeholder="Enter your URL here">
      <select id="ttl">
        <option value="1h">1 Hour</option>
        <option value="24h" selected>24 Hours</option>
        <option value="1w">1 Week</option>
        <option value="never">Never</option>
      </select>
      <input type="text" id="customCode" placeholder="Custom code (optional)">
      <button id="shortenBtn">Shorten</button>
      <div id="result" style="display:none;">
        <div class="short-link">
          <span id="shortUrl"></span>
          <button class="copy-btn" id="copyBtn">Copy</button>
        </div>
      </div>
    </div>

    <script>
    const shortenBtn = document.getElementById("shortenBtn");
    const resultDiv = document.getElementById("result");
    const shortUrlSpan = document.getElementById("shortUrl");
    const copyBtn = document.getElementById("copyBtn");

    shortenBtn.addEventListener("click", async () => {{
        const longUrl = document.getElementById("longUrl").value.trim();
        const ttl = document.getElementById("ttl").value;
        const customCode = document.getElementById("customCode").value.trim() || undefined;
        if (!longUrl) {{ alert("Please enter a URL."); return; }}
        try {{
            const res = await fetch("/api/v1/links", {{
                method:"POST",
                headers:{{"Content-Type":"application/json"}},
                body: JSON.stringify({{long_url:longUrl, ttl:ttl, custom_code:customCode}})
            }});
            const data = await res.json();
            if (res.ok) {{
                shortUrlSpan.textContent = data.short_url;
                resultDiv.style.display = "block";
            }} else {{
                alert(data.detail || "Error creating short link");
            }}
        }} catch(err) {{ console.error(err); alert("Failed to connect to the server."); }}
    }});

    copyBtn.addEventListener("click", () => {{
        navigator.clipboard.writeText(shortUrlSpan.textContent)
            .then(() => alert("Copied!"))
            .catch(() => alert("Failed to copy."));
    }});
    </script>
    </body>
    </html>
    """

@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    
    long_url = link["long_url"]

    # FIX 2: Create an absolute URL for the 'href' attribute, handling old data
    if not long_url.startswith(("http://", "https://")):
        safe_href_url = "https://" + long_url
    else:
        safe_href_url = long_url
    
    # Escape the normalized URL for the 'href' attribute
    escaped_long_url_href = html.escape(safe_href_url, quote=True)
    # Escape the original URL for just displaying as text
    escaped_long_url_display = html.escape(long_url)

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Preview - {short_code}</title>
        <meta name="robots" content="noindex">
        <meta name="description" content="Preview link before visiting">
        {ADSENSE_SCRIPT} <style>
            body {{ font-family: Arial,sans-serif; margin:0; background:#f3f4f6; display:flex; justify-content:center; align-items:center; min-height:100vh; padding:1rem; box-sizing: border-box; }}
            .card {{ background:#fff; padding:2rem; border-radius:12px; box-shadow:0 8px 24px rgba(0,0,0,0.1); width:100%; max-width:500px; text-align:center; }}
            h1 {{ margin-top:0; color:#4f46e5; }}
            p.url {{ word-break: break-word; font-weight:bold; color:#111827; }}
            a.button {{ display:inline-block; margin-top:20px; padding:12px 24px; background:#4f46e5; color:white; text-decoration:none; border-radius:8px; font-weight:bold; }}
            a.button:hover {{ background:#6366f1; }}
            @media(max-width:500px){{ 
                .card {{ padding:1.5rem; }} 
                /* FIX: Added box-sizing to prevent overflow on mobile */
                a.button {{ width:100%; box-sizing: border-box; }} 
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Preview Link</h1>
            <p>Original URL:</p>
            <p class="url">{escaped_long_url_display}</p>
            <a class="button" href="{escaped_long_url_href}" target="_blank" rel="noopener noreferrer">Go to Link</a>
        </div>
    </body>
    </html>
    """

@app.get("/r/{short_code}")
async def redirect_link(short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")

    long_url = link["long_url"]

    # FIX 3: Ensure the redirect URL is absolute, handling old data
    if not long_url.startswith(("http://", "https://")):
        absolute_url = "https://" + long_url
    else:
        absolute_url = long_url

    return RedirectResponse(url=absolute_url)
