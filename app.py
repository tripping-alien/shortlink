from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import secrets
from datetime import datetime, timezone, timedelta
import logging
import database  # your firebase/db logic

app = FastAPI(title="Shortlinks Service", version="1.0.0")
logger = logging.getLogger(__name__)

# CORS for testing (allow all origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://shortlinks.art"  # change if needed

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    """Initialize database connection."""
    try:
        database.init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

# --- Health Check ---
@app.get("/health")
async def health_check():
    """Check app and DB status."""
    try:
        _ = database.get_db_connection()
        db_status = "initialized"
    except Exception:
        db_status = "uninitialized"
    return {"status": "ok", "database": db_status}

# --- Serve index.html ---
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the index.html from root folder."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception as e:
        logger.error(f"Failed to read index.html: {e}")
        raise HTTPException(status_code=500, detail="UI not found")

# --- Create Short Link ---
@app.post("/api/v1/links")
async def create_short_link(payload: dict):
    """Create a new short link."""
    long_url = payload.get("long_url")
    ttl = payload.get("ttl")
    custom_code = payload.get("custom_code")

    if not long_url:
        raise HTTPException(status_code=400, detail="Missing URL.")

    expires_at = None
    if ttl == "1h":
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    elif ttl == "24h":
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    elif ttl == "1w":
        expires_at = datetime.now(timezone.utc) + timedelta(weeks=1)
    # "never" -> expires_at stays None

    deletion_token = secrets.token_urlsafe(32)

    try:
        short_code = database.create_link(long_url, expires_at, deletion_token, short_code=custom_code)
        full_url = f"{BASE_URL}/{short_code}"
        return JSONResponse({
            "long_url": long_url,
            "short_url": full_url,
            "deletion_token": deletion_token
        })
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating short link: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# --- Redirect Short Link ---
@app.get("/{short_code}")
async def redirect_to_long(short_code: str):
    """Redirect browser to long URL."""
    link_data = database.get_link_by_id(short_code)
    if not link_data:
        raise HTTPException(status_code=404, detail="Link not found")

    expires_at = link_data.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")

    return RedirectResponse(url=link_data['long_url'])
