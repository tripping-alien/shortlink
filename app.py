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
