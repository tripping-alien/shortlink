import secrets
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database  # your Firestore logic
from schemas import LinkCreate, ShortLinkResponse
from config import get_settings, TTL_MAP, TTL

# --- FastAPI setup ---
app = FastAPI(title="Shortlinks Service", version="1.0.0")
logger = logging.getLogger(__name__)

settings = get_settings()
BASE_URL = str(settings.base_url).rstrip("/")

DB_INITIALIZED = False

def _(text: str) -> str:
    return text  # placeholder for translations

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR))
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup_event():
    global DB_INITIALIZED
    try:
        database.init_db()
        DB_INITIALIZED = True
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")


# --- Helper ---
def calculate_expiration(ttl_string: str) -> Optional[datetime]:
    if ttl_string == TTL.NEVER:
        return None
    now = datetime.now(timezone.utc)
    try:
        duration = TTL_MAP.get(TTL(ttl_string))
        if duration:
            return now + duration
    except ValueError:
        logger.warning(f"Invalid TTL: {ttl_string}")
    return now + TTL_MAP[TTL.ONE_DAY]


# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def root_redirect():
    return RedirectResponse("/ui/en/", status_code=307)


@app.get("/ui/{lang_code}/", response_class=HTMLResponse)
async def serve_index(request: Request, lang_code: str):
    return templates.TemplateResponse("index.html", {"request": request, "base_url": BASE_URL, "lang_code": lang_code, "_": _})


@app.post("/api/v1/links", response_model=ShortLinkResponse, status_code=201)
async def create_short_link(link_data: LinkCreate):
    if not DB_INITIALIZED:
        raise HTTPException(status_code=503, detail="Database not initialized")

    expiration_time = calculate_expiration(link_data.ttl)
    deletion_token = secrets.token_urlsafe(32)

    try:
        short_code = database.create_link(
            long_url=link_data.long_url,
            expires_at=expiration_time,
            deletion_token=deletion_token,
            short_code=link_data.custom_code
        )
        full_short_url = f"{BASE_URL}/{short_code}"

        return ShortLinkResponse(
            long_url=link_data.long_url,
            short_url=full_short_url,
            deletion_token=deletion_token,
        )

    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail="Failed to generate a unique ID")


@app.get("/{short_code}")
async def redirect_to_long_url(short_code: str):
    if not DB_INITIALIZED:
        raise HTTPException(status_code=503, detail="Database not initialized")

    link_data = database.get_link_by_id(short_code)
    if not link_data:
        raise HTTPException(status_code=404, detail="Short link not found")

    expires_at = link_data.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Short link has expired")

    return RedirectResponse(url=link_data["long_url"], status_code=307)
