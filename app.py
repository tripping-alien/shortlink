import os
import secrets
import logging
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

# ------------------ CONFIG ------------------
BASE_URL = os.environ.get("BASE_URL", "https://shortlinks.art")
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 10
TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------ FIREBASE ------------------
db: firestore.client = None
APP_INSTANCE = None

def init_firebase():
    global db, APP_INSTANCE
    if db:
        return db
    firebase_config_str = os.environ.get("FIREBASE_CONFIG")
    cred = None
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        cred = credentials.ApplicationDefault()
    elif firebase_config_str:
        import tempfile, json
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

def get_links_collection():
    return init_firebase().collection("links")

# ------------------ HELPERS ------------------
def _generate_short_code(length=SHORT_CODE_LENGTH):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_short_code():
    for _ in range(MAX_ID_RETRIES):
        code = _generate_short_code()
        doc = get_links_collection().document(code).get()
        if not doc.exists:
            return code
    raise RuntimeError("Could not generate unique code.")

def calculate_expiration(ttl: str) -> Optional[datetime]:
    delta = TTL_MAP.get(ttl, TTL_MAP["24h"])
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def create_link_in_db(long_url: str, ttl: str, custom_code: Optional[str] = None):
    code = custom_code or generate_unique_short_code()
    if custom_code:
        if not custom_code.isalnum():
            raise ValueError("Custom code must be alphanumeric.")
        doc = get_links_collection().document(custom_code).get()
        if doc.exists:
            raise ValueError("Custom code already exists.")
    expires_at = calculate_expiration(ttl)
    data = {
        "long_url": long_url,
        "deletion_token": secrets.token_urlsafe(32),
        "created_at": datetime.now(timezone.utc)
    }
    if expires_at:
        data["expires_at"] = expires_at
    get_links_collection().document(code).set(data)
    return {**data, "short_code": code}

def get_link(code: str) -> Optional[Dict[str, Any]]:
    doc = get_links_collection().document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

# ------------------ APP ------------------
app = FastAPI(title="Shortlinks.art URL Shortener")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ ROUTES ------------------
@app.get("/health")
async def health():
    try:
        init_firebase()
        return {"status": "ok", "database": "initialized"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

@app.get("/api/v1/links/{short_code}")
async def get_link_info(short_code: str):
    if not DB_INITIALIZED:
        raise HTTPException(status_code=503, detail="Database not initialized.")
    link_data = database.get_link_by_id(short_code)
    if not link_data:
        raise HTTPException(status_code=404, detail="Link not found")
    
    return {
        "short_code": link_data['id'],
        "long_url": link_data['long_url'],
        "expires_at": link_data.get('expires_at')
    }

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shortlinks.art - URL Shortener</title>
    <style>
        :root {
            --primary-color: #4f46e5;
            --secondary-color: #6366f1;
            --accent-color: #facc15;
            --bg-color: #f3f4f6;
            --text-color: #111827;
        }
        body { font-family: Arial,sans-serif; background: var(--bg-color); color: var(--text-color); display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0; }
        .container { background:#fff; padding:2rem; border-radius:12px; box-shadow:0 8px 24px rgba(0,0,0,0.1); width:100%; max-width:480px; text-align:center; }
        input, select { padding:0.8rem; width:100%; margin:0.5rem 0; border-radius:8px; border:1px solid #d1d5db; font-size:1rem; }
        button { background: var(--primary-color); color:white; border:none; padding:0.8rem 1.5rem; font-size:1rem; border-radius:8px; cursor:pointer; margin-top:0.5rem; }
        button:hover { background: var(--secondary-color); }
        .short-link { margin-top:1rem; display:flex; justify-content:space-between; align-items:center; padding:0.6rem; background:#f9fafb; border-radius:8px; }
        .copy-btn { background: var(--accent-color); border:none; padding:0.5rem 0.8rem; border-radius:6px; cursor:pointer; color:#111827; }
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

    shortenBtn.addEventListener("click", async () => {
        const longUrl = document.getElementById("longUrl").value.trim();
        const ttl = document.getElementById("ttl").value;
        const customCode = document.getElementById("customCode").value.trim() || undefined;
        if (!longUrl) { alert("Please enter a URL."); return; }
        try {
            const res = await fetch("/api/v1/links", {
                method:"POST",
                headers:{"Content-Type":"application/json"},
                body: JSON.stringify({long_url:longUrl, ttl:ttl, custom_code:customCode})
            });
            const data = await res.json();
            if (res.ok) {
                shortUrlSpan.textContent = data.short_url;
                resultDiv.style.display = "block";
            } else {
                alert(data.detail || "Error creating short link");
            }
        } catch(err) { console.error(err); alert("Failed to connect to the server."); }
    });

    copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(shortUrlSpan.textContent)
            .then(() => alert("Copied!"))
            .catch(() => alert("Failed to copy."));
    });
    </script>
    </body>
    </html>
    """

@app.get("/r/{short_code}")
async def redirect_short_link(short_code: str):
    link_data = database.get_link_by_id(short_code)
    if not link_data:
        raise HTTPException(status_code=404, detail="Link not found")
    expires_at = link_data.get('expires_at')
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    return RedirectResponse(url=link_data["long_url"])
@app.post("/api/v1/links")
async def api_create_link(payload: Dict[str, Any]):
    long_url = payload.get("long_url")
    ttl = payload.get("ttl", "24h")
    custom_code = payload.get("custom_code")
    if not long_url:
        raise HTTPException(status_code=400, detail="Missing long_url")
    try:
        link = create_link_in_db(long_url, ttl, custom_code)
        preview_url = f"{BASE_URL}/preview/{link['short_code']}"
        return {"short_url": preview_url}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    long_url = link["long_url"]
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Preview - {short_code}</title>
        <meta name="robots" content="noindex">
        <style>
            body {{ font-family: Arial,sans-serif; text-align:center; padding:50px; }}
            a.button {{ display:inline-block; padding:10px 20px; background:#4f46e5; color:white; text-decoration:none; border-radius:8px; margin-top:20px; }}
        </style>
    </head>
    <body>
        <h1>Preview Link</h1>
        <p>Original URL:</p>
        <p>{long_url}</p>
        <a class="button" href="{BASE_URL}/r/{short_code}" target="_blank">Go to Link</a>
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
    return RedirectResponse(url=link["long_url"])
