from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import secrets
from datetime import datetime, timezone, timedelta
import logging
import database  # your firebase/db logic

app = FastAPI(title="Shortlinks Service", version="1.0.0")
logger = logging.getLogger(__name__)

# Allow cross-origin for testing (optional)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://shortlinks.art"  # change if needed

@app.on_event("startup")
async def startup_event():
    """Initialize database connection."""
    try:
        database.init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the index.html directly from root folder."""
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/api/v1/links")
async def create_short_link(payload: dict):
    """Create short link."""
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
    # "never" -> expires_at remains None

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

@app.get("/{short_code}")
async def redirect_to_long(short_code: str):
    """Redirect to the long URL."""
    link_data = database.get_link_by_id(short_code)
    if not link_data:
        raise HTTPException(status_code=404, detail="Link not found")

    expires_at = link_data.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")

    return {"url": link_data['long_url']}  # for now, simple JSON (or RedirectResponse if you prefer)
